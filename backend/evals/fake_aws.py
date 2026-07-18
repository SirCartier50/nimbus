"""Hermetic stand-in for a boto3 Session — evals never touch real AWS.

The Architect's inspection tools (list_resources / get_resource_status /
get_account_info) reach AWS through a boto3 Session. Evals score the model's
PLANNING, not real deployment, so the architect gets this fake instead: every
AWS call returns an empty/benign result, which is also the correct premise for
"plan me a brand-new X" (the eval account is empty). The tool-use loop already
turns any tool error into a tool result the model reads and moves past, so even
a call this fake doesn't explicitly satisfy costs nothing but one step.
"""


class _FakeClient:
    def __init__(self, service: str):
        self._service = service

    def get_caller_identity(self):
        return {
            "Account": "000000000000",
            "Arn": "arn:aws:iam::000000000000:user/eval",
            "UserId": "EVAL",
        }

    def __getattr__(self, name):
        # Any describe_*/list_*/etc. returns an empty dict — no resources exist in
        # the eval account, the right starting point for a fresh build plan.
        def _call(*args, **kwargs):
            return {}

        return _call


class FakeAWSSession:
    """Quacks like a boto3.Session for the two things the inspection tools use:
    `.client(service, config=..., **kw)` and `.region_name`."""

    region_name = "us-east-1"

    def client(self, service, config=None, **kwargs):
        return _FakeClient(service)
