"""Converts botocore API shapes into JSON-Schema-compatible dicts.

botocore ships AWS's machine-readable API specs locally — the same data that
generates the AWS console's creation forms and the CLI's --help text. Walking
those shapes (instead of hand-writing a schema per resource type) means every
required field, type, and enum constraint the model sees is sourced directly
from AWS, not from our memory of it.

Two schemas come out of the same shape, for two different audiences:
  - generate_tool_schema()       -> sent to Bedrock as toolSpec.inputSchema on
                                     every model call. Scalar fields (string,
                                     int, bool, ...) always render with their
                                     real type/enum/docs regardless of depth —
                                     they're cheap. Nested structures/lists/maps
                                     are capped by `max_depth` and collapse to a
                                     placeholder beyond it, since AWS shapes
                                     like EC2's RunInstances nest deeply enough
                                     to blow up the token budget if fully
                                     expanded on every call.
  - generate_validation_schema() -> never leaves this process. Full fidelity
                                     (every enum value, deep nesting, untruncated
                                     docs), used to check the model's config
                                     dict locally before it ever reaches boto3.
"""
import re

import botocore.session

_TAG_RE = re.compile(r"<[^>]+>")
_session = botocore.session.get_session()

# Sentinel placeholder for nested structures/lists/maps collapsed by the depth cap.
# Public (not underscore-prefixed) so callers can detect "did this schema actually fit
# in the depth budget?" without hardcoding the marker text themselves.
COLLAPSED_DESCRIPTION = "Nested structure collapsed for brevity — call describe_resource_schema(resource_type) for the full shape."


def _clean_doc(doc: str, max_len: int) -> str:
    if not doc:
        return ""
    text = _TAG_RE.sub("", doc)
    text = " ".join(text.split())
    return text[:max_len]


def get_operation_input_shape(service: str, operation: str):
    service_model = _session.get_service_model(service)
    return service_model.operation_model(operation).input_shape


def get_operation_summary(service: str, operation: str, max_len: int = 300) -> str:
    """One-line, HTML-stripped summary of what an operation does — used as a
    Bedrock tool's top-level `description`, separate from its per-field docs."""
    service_model = _session.get_service_model(service)
    doc = service_model.operation_model(operation).documentation
    return _clean_doc(doc, max_len)


def _convert(shape, seen: frozenset, remaining: int, enum_cap, doc_len: int) -> dict:
    if shape is None:
        return {"type": "object"}

    type_name = shape.type_name

    # Scalar leaf types are cheap — always render fully, regardless of depth budget.
    if type_name == "string":
        schema = {"type": "string"}
        enum = getattr(shape, "enum", None)
        if enum:
            if enum_cap is None or len(enum) <= enum_cap:
                schema["enum"] = list(enum)
            else:
                sample = ", ".join(enum[:8])
                schema["description"] = f"One of {len(enum)} allowed values, e.g. {sample}, ... (see AWS docs for the full list)"
        return schema
    if type_name in ("integer", "long"):
        return {"type": "integer"}
    if type_name in ("double", "float"):
        return {"type": "number"}
    if type_name == "boolean":
        return {"type": "boolean"}
    if type_name == "blob":
        return {"type": "string", "description": "Base64-encoded binary data"}
    if type_name == "timestamp":
        return {"type": "string", "description": "ISO 8601 timestamp"}

    # structure / list / map are the recursive, potentially-large types — gate by
    # remaining depth budget and a cycle guard for self-referential shapes.
    if remaining < 0 or (shape.name and shape.name in seen):
        return {"type": "object", "description": COLLAPSED_DESCRIPTION}

    seen = seen | {shape.name} if shape.name else seen

    if type_name == "structure":
        properties = {}
        for member_name, member_shape in shape.members.items():
            sub = _convert(member_shape, seen, remaining - 1, enum_cap, doc_len)
            doc = _clean_doc(getattr(member_shape, "documentation", "") or "", doc_len)
            # Don't let the field's own AWS doc overwrite the "collapsed" sentinel —
            # that would silently swallow the only signal that this field's real
            # shape didn't fit in the depth budget, since most fields have docs.
            if doc and sub.get("description") != COLLAPSED_DESCRIPTION:
                sub["description"] = doc
            properties[member_name] = sub
        schema = {"type": "object", "properties": properties}
        if shape.required_members:
            schema["required"] = list(shape.required_members)
        return schema

    if type_name == "list":
        return {"type": "array", "items": _convert(shape.member, seen, remaining - 1, enum_cap, doc_len)}

    if type_name == "map":
        return {"type": "object", "additionalProperties": _convert(shape.value, seen, remaining - 1, enum_cap, doc_len)}

    return {"type": "string"}


def generate_tool_schema(service: str, operation: str, max_depth: int = 2, enum_cap: int = 40, doc_len: int = 180) -> dict:
    """Compact schema for Bedrock's toolSpec — token-budget-conscious.

    The operation's top-level fields are always fully named and typed
    regardless of max_depth; nested structures/lists/maps collapse to a
    placeholder once max_depth is exhausted. Depth=2 covers every resource
    type in the registry with zero collapsed nodes except a couple of
    single-wrapper operations (e.g. CloudFront's CreateDistribution, which
    has exactly one top-level field — DistributionConfig — holding all the
    real content); callers needing guaranteed full fidelity for a specific
    operation should check the result for COLLAPSED_DESCRIPTION and retry
    with a higher max_depth.
    """
    shape = get_operation_input_shape(service, operation)
    return _convert(shape, frozenset(), max_depth, enum_cap, doc_len)


def generate_validation_schema(service: str, operation: str, max_depth: int = 12) -> dict:
    """Full-fidelity schema (every enum value, untruncated docs) for local validation only."""
    shape = get_operation_input_shape(service, operation)
    return _convert(shape, frozenset(), max_depth, enum_cap=None, doc_len=10_000)
