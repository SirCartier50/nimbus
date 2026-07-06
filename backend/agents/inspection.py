"""Read-only AWS inspection tools, shared by the Requirements agent (front-door
Q&A / "show my resources") and the Architect agent (checking current state before
planning). Generic across all 15 registry resource types — list/describe plus
account identity. No mutation happens here; creation/deletion lives in executor.py.
"""
import os

from providers import aws_dispatch
from providers.aws_registry import REGISTRY
from utils.aws_clients import get_sts_client

_RESOURCE_TYPE_ENUM = sorted(REGISTRY)

INSPECTION_TOOL_CONFIG = {
    "tools": [
        {
            "toolSpec": {
                "name": "list_resources",
                "description": "List every resource of a given type that currently exists in this AWS account.",
                "inputSchema": {
                    "json": {
                        "type": "object",
                        "properties": {"resource_type": {"type": "string", "enum": _RESOURCE_TYPE_ENUM}},
                        "required": ["resource_type"],
                    }
                },
            }
        },
        {
            "toolSpec": {
                "name": "get_resource_status",
                "description": "Look up the current live status/details of one specific resource by its id.",
                "inputSchema": {
                    "json": {
                        "type": "object",
                        "properties": {
                            "resource_type": {"type": "string", "enum": _RESOURCE_TYPE_ENUM},
                            "resource_id": {"type": "string"},
                        },
                        "required": ["resource_type", "resource_id"],
                    }
                },
            }
        },
        {
            "toolSpec": {
                "name": "get_account_info",
                "description": "Get the current AWS account ID, region, and caller identity.",
                "inputSchema": {"json": {"type": "object", "properties": {}, "required": []}},
            }
        },
    ]
}


def _handle_get_account_info(params: dict, session=None) -> dict:
    sts = get_sts_client(session)
    identity = sts.get_caller_identity()
    return {
        "account_id": identity["Account"],
        "arn": identity["Arn"],
        "region": session.region_name if session else os.getenv("AWS_REGION", "us-east-1"),
    }


# Handler functions take (params, session); build_handlers() binds the session per
# call via a closure so concurrent requests from different users never share state.
_HANDLER_FUNCS = {
    "list_resources": lambda p, session=None: aws_dispatch.list_resources(p["resource_type"], session),
    "get_resource_status": lambda p, session=None: aws_dispatch.get_resource_status(
        p["resource_type"], p["resource_id"], session
    ),
    "get_account_info": _handle_get_account_info,
}


def build_handlers(aws_session=None) -> dict:
    return {name: (lambda p, fn=fn: fn(p, aws_session)) for name, fn in _HANDLER_FUNCS.items()}
