"""Generic, read-only AWS dispatch shared by architect.py (inspection/Q&A)
and executor.py (post-create verification). Pure registry-driven, no
tagging or create-time fallbacks — those are executor-specific mutating
concerns and stay there.
"""
import datetime
from decimal import Decimal

import botocore

from providers import aws_registry as registry
from utils.aws_clients import make_client


def client_for(resource_type: str, session=None):
    spec = registry.get_spec(resource_type)
    return make_client(spec.service, session)


def call(client, operation: str, **kwargs):
    """boto3 client methods are snake_case; botocore operation names (and
    everything in the registry) are PascalCase. xform_name is the exact
    converter boto3 itself uses to generate its method names."""
    return getattr(client, botocore.xform_name(operation))(**kwargs)


def json_safe(obj):
    """Recursively strip types Bedrock's tool-result JSON can't carry
    (datetime, Decimal, bytes) so a raw boto3 response can be handed straight
    back to the model instead of hand-curating a response shape per resource type."""
    if isinstance(obj, dict):
        return {k: json_safe(v) for k, v in obj.items() if k != "ResponseMetadata"}
    if isinstance(obj, list):
        return [json_safe(v) for v in obj]
    if isinstance(obj, (datetime.datetime, datetime.date)):
        return obj.isoformat()
    if isinstance(obj, bytes):
        return obj.decode("utf-8", errors="replace")
    if isinstance(obj, Decimal):
        return float(obj)
    return obj


def get_resource_status(resource_type: str, resource_id: str, session=None) -> dict:
    spec = registry.get_spec(resource_type)
    client = client_for(resource_type, session)
    kwargs = registry.build_id_kwargs(resource_type, resource_id, "describe")
    response = call(client, spec.describe_operation, **kwargs)
    return json_safe(response)


def list_resources(resource_type: str, session=None) -> dict:
    spec = registry.get_spec(resource_type)
    client = client_for(resource_type, session)
    operation = spec.list_operation or spec.describe_operation
    response = call(client, operation)
    return json_safe(response)
