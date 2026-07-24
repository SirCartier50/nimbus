"""Tier-1 plan validation — deterministic, code-only (see PIPELINE_PLAN.md §3).

These checks can't hallucinate false positives, so the orchestrator may safely loop
a flagged plan back to the Architect to fix. Scope is deliberately narrow: only
things that are unambiguously wrong regardless of the executor's create-time
fallbacks (which fill in AMI ids, IAM roles, Lambda code, etc.). Fuzzy judgment
("is this over-provisioned?") is the LLM Critic's job (Tier-2), not this.
"""
from providers.aws_registry import REGISTRY

_VALID_ACTIONS = {"create", "delete", "stop"}
_FREE_TIER_DISALLOWED = {"rds_instance", "elasticache", "nat_gateway", "ecs_cluster", "load_balancer", "cloudfront"}
_FREE_TIER_EC2 = {"t2.micro", "t3.micro"}

# Within a single plan, if a resource and its prerequisite type are BOTH created,
# the prerequisite must come first. (A prerequisite absent from the plan is fine —
# it may already exist in the account, referenced by id in the config.)
_PREREQS = {
    "subnet": {"vpc"},
    "security_group": {"vpc"},
    "ec2_instance": {"subnet", "security_group"},
    "nat_gateway": {"subnet"},
}


def validate_plan(plan: dict, free_tier_mode: bool = True) -> list[str]:
    """Return a list of blocking-issue strings (empty == clean)."""
    issues: list[str] = []
    steps = plan.get("plan")
    if not isinstance(steps, list) or not steps:
        return ["The plan has no steps."]

    create_types = {s.get("resource_type") for s in steps if s.get("action") == "create"}
    created_so_far: set = set()

    for idx, step in enumerate(steps, 1):
        action = step.get("action")
        rt = step.get("resource_type")

        if action not in _VALID_ACTIONS:
            issues.append(f"Step {idx}: unknown action '{action}' (must be create, delete, or stop).")
            continue
        known = rt in REGISTRY
        generic = isinstance(rt, str) and "::" in rt   # CloudFormation type name, e.g. AWS::SQS::Queue
        if not known and not generic:
            issues.append(f"Step {idx}: unknown resource_type '{rt}'.")
            continue

        if action == "create":
            if not isinstance(step.get("config"), dict):
                issues.append(f"Step {idx}: create {rt} is missing a config object.")

            # Free-tier and prerequisite-ordering checks only apply to the curated types —
            # we don't have per-service knowledge of arbitrary CloudFormation types.
            if known and free_tier_mode:
                if rt in _FREE_TIER_DISALLOWED:
                    issues.append(f"Step {idx}: {rt} is not free-tier eligible, but free-tier mode is on.")
                if rt == "ec2_instance":
                    itype = (step.get("config") or {}).get("InstanceType")
                    if itype and itype not in _FREE_TIER_EC2:
                        issues.append(
                            f"Step {idx}: EC2 InstanceType '{itype}' is not free-tier eligible "
                            "(use t2.micro or t3.micro)."
                        )

            if known:
                for prereq in _PREREQS.get(rt, set()):
                    if prereq in create_types and prereq not in created_so_far:
                        issues.append(
                            f"Step {idx}: {rt} is created before its prerequisite '{prereq}', "
                            "which appears later in the plan — reorder so the prerequisite comes first."
                        )
            created_so_far.add(rt)
        else:  # delete / stop
            if not step.get("resource_id"):
                issues.append(f"Step {idx}: {action} {rt} is missing a resource_id.")

    return issues


# ---------------------------------------------------------------------------
# Exfiltration-intent advisories (P3-2, docs/security/prompt-injection.md)
#
# Deterministic, code-only checks for resource shapes that open a data-egress or
# public-exposure channel — the exact shapes a successful prompt injection would
# use to leak a user's data (public bucket, world-open security group). Unlike
# validate_plan these are NOT blocking: a public bucket / open port is sometimes
# genuinely intended, so we surface them as high-risk ADVISORIES at the human
# approval gate ("confirm this is intended") rather than silently refining them
# away. Defense-in-depth on top of the plan-subset + managed-only invariants.
# ---------------------------------------------------------------------------

_OPEN_CIDRS = {"0.0.0.0/0", "::/0"}
_PUBLIC_S3_ACLS = {"public-read", "public-read-write", "authenticated-read"}


def _walk(obj):
    """Yield every dict nested anywhere in a config, so a check finds the field
    regardless of how deeply the model nested it (CFN vs. flat API shape)."""
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v)


def check_exfil_intent(plan: dict) -> list[str]:
    """Return a list of high-risk-egress advisory strings (empty == none). Never
    blocking; meant for the approval gate."""
    warnings: list[str] = []
    steps = plan.get("plan") if isinstance(plan, dict) else None
    if not isinstance(steps, list):
        return warnings

    for idx, step in enumerate(steps, 1):
        if not isinstance(step, dict) or step.get("action") != "create":
            continue
        rt = step.get("resource_type")
        config = step.get("config") or {}
        rt_l = rt.lower() if isinstance(rt, str) else ""

        # Public S3 bucket — a canonical exfil channel.
        if "s3" in rt_l or "bucket" in rt_l:
            for d in _walk(config):
                acl = d.get("ACL") or d.get("AccessControl")
                if isinstance(acl, str) and acl.lower() in _PUBLIC_S3_ACLS:
                    warnings.append(
                        f"Step {idx}: S3 bucket is created with a public ACL "
                        f"('{acl}') - anyone on the internet could read its contents. "
                        "Confirm this is intended."
                    )
                pab = d.get("PublicAccessBlockConfiguration")
                if isinstance(pab, dict) and any(v is False for v in pab.values()):
                    warnings.append(
                        f"Step {idx}: S3 bucket disables part of its public-access block "
                        "- it may be publicly reachable. Confirm this is intended."
                    )

        # Security group opened to the whole internet.
        if "security" in rt_l or "securitygroup" in rt_l or rt == "security_group":
            for d in _walk(config):
                cidr = d.get("CidrIp") or d.get("CidrIpv6")
                if isinstance(cidr, str) and cidr in _OPEN_CIDRS:
                    port = d.get("ToPort", d.get("FromPort", "any"))
                    warnings.append(
                        f"Step {idx}: security group allows inbound access from {cidr} "
                        f"(the entire internet) on port {port} - confirm this is intended."
                    )

    return warnings
