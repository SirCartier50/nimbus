"""Post-deploy health validation (PIPELINE_PLAN.md §2, Validator).

Plain code — after the Executor runs, confirm each successfully created resource
actually exists in AWS instead of trusting the create call's response. Never raises:
a check that errors is reported as not-healthy with detail, so a flaky describe can't
crash the deploy flow.
"""
from providers import aws_dispatch


def run_validator(results: list, aws_session=None) -> list:
    health = []
    for r in results or []:
        if not (r.get("success") and r.get("resource_id") and r.get("resource_type")):
            continue
        rt, rid = r["resource_type"], r["resource_id"]
        try:
            aws_dispatch.get_resource_status(rt, rid, aws_session)
            health.append({"resource_type": rt, "resource_id": rid, "healthy": True})
        except Exception as e:
            health.append({"resource_type": rt, "resource_id": rid, "healthy": False, "detail": str(e)[:200]})
    return health
