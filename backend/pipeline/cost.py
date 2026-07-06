"""Monthly cost estimate for a plan (replaces the LLM's guessed number — see
PIPELINE_PLAN.md §6).

Two sources, in order: when an AWS session is available we query the live AWS Pricing
API (`pricing_api`) for the instance-type-driven resources (EC2/RDS/ElastiCache) where
prices drift and vary most; for everything else, and whenever the live lookup is
unavailable (no `pricing:GetProducts` permission, unmapped region, throttle, etc.), we
fall back to a static us-east-1 price table. Each breakdown line records which source
produced it, so the number at the approval gate is always traceable.

Usage-based services (S3, Lambda, DynamoDB, API Gateway, CloudFront, ECS/Fargate) have
no flat base we can know at plan time, so they're reported as $0 base + a "usage-based"
note rather than a fabricated number — neither source can help there.
"""
from pipeline import pricing_api

HOURS_PER_MONTH = 730

_EC2_HOURLY = {
    "t2.micro": 0.0116, "t3.micro": 0.0104, "t2.small": 0.023, "t3.small": 0.0208,
    "t2.medium": 0.0464, "t3.medium": 0.0416, "m5.large": 0.096, "m5.xlarge": 0.192,
    "c5.large": 0.085, "c5.xlarge": 0.17,
}
_HOURLY = {            # flat hourly resources -> * 730
    "load_balancer": 0.0225,   # ALB base
    "nat_gateway": 0.045,
}
_FLAT_MONTHLY = {
    "rds_instance": 15.0,      # ~ db.t3.micro
    "elasticache": 12.0,       # ~ cache.t3.micro
}
_FREE = {"vpc", "subnet", "security_group", "iam_role"}
_USAGE_BASED = {"s3_bucket", "lambda_function", "dynamodb_table", "api_gateway", "cloudfront", "ecs_cluster"}

_FREE_TIER_EC2 = {"t2.micro", "t3.micro"}


def _step_cost(step: dict, free_tier_mode: bool, aws_session, region: str) -> tuple[float, str, str]:
    """Return (monthly_usd, note, source). `source` is one of: aws_pricing_api,
    static_table, usage-based, free, free-tier, none."""
    if step.get("action") != "create":
        return 0.0, "no ongoing cost", "none"
    rt = step.get("resource_type")
    config = step.get("config") or {}

    if rt in _FREE:
        return 0.0, "no charge", "free"
    if rt in _USAGE_BASED:
        return 0.0, "usage-based (depends on traffic/storage)", "usage-based"

    if rt == "ec2_instance":
        itype = config.get("InstanceType", "t3.micro")
        if free_tier_mode and itype in _FREE_TIER_EC2:
            return 0.0, f"{itype} (free tier)", "free-tier"
        live = pricing_api.ec2_monthly(itype, region, aws_session) if aws_session else None
        if live is not None:
            return live, itype, "aws_pricing_api"
        return round(_EC2_HOURLY.get(itype, 0.05) * HOURS_PER_MONTH, 2), itype, "static_table"

    if rt == "rds_instance":
        db_class = config.get("DBInstanceClass", "db.t3.micro")
        live = pricing_api.rds_monthly(db_class, config.get("Engine"), region, aws_session) if aws_session else None
        if live is not None:
            return live, db_class, "aws_pricing_api"
        return _FLAT_MONTHLY["rds_instance"], "approximate", "static_table"

    if rt == "elasticache":
        node = config.get("CacheNodeType", "cache.t3.micro")
        live = pricing_api.elasticache_monthly(node, config.get("Engine"), region, aws_session) if aws_session else None
        if live is not None:
            return live, node, "aws_pricing_api"
        return _FLAT_MONTHLY["elasticache"], "approximate", "static_table"

    if rt == "nat_gateway":
        live = pricing_api.nat_gateway_monthly(region, aws_session) if aws_session else None
        if live is not None:
            return live, "hourly base (plus data transfer)", "aws_pricing_api"
        return round(_HOURLY["nat_gateway"] * HOURS_PER_MONTH, 2), "hourly base (plus data transfer)", "static_table"

    if rt == "load_balancer":
        live = pricing_api.load_balancer_monthly(region, aws_session) if aws_session else None
        if live is not None:
            return live, "hourly base (plus LCU usage)", "aws_pricing_api"
        return round(_HOURLY["load_balancer"] * HOURS_PER_MONTH, 2), "hourly base (plus LCU usage)", "static_table"

    if rt in _FLAT_MONTHLY:
        return _FLAT_MONTHLY[rt], "approximate", "static_table"
    # Generic CloudFormation-typed resource — we can't price arbitrary types. Be honest
    # (don't fabricate a number); the plan's cost_warning covers it.
    return 0.0, "not estimated — non-standard resource type", "unknown"


def estimate_plan_cost(plan: dict, free_tier_mode: bool = True, aws_session=None) -> dict:
    region = getattr(aws_session, "region_name", None) or "us-east-1"
    breakdown = []
    total = 0.0
    for i, step in enumerate(plan.get("plan", []), 1):
        cost, note, source = _step_cost(step, free_tier_mode, aws_session, region)
        total += cost
        breakdown.append({
            "step": step.get("step", i),
            "resource_type": step.get("resource_type"),
            "monthly_usd": cost,
            "note": note,
            "source": source,
        })

    has_usage = any(b["note"].startswith("usage-based") for b in breakdown)
    has_unknown = any(b["source"] == "unknown" for b in breakdown)
    total = round(total, 2)
    if total == 0 and not has_usage and not has_unknown:
        formatted = "$0.00/month (free)"
    else:
        formatted = f"${total:.2f}/month"
        extras = []
        if has_usage:
            extras.append("usage-based charges")
        if has_unknown:
            extras.append("unestimated resources")
        if extras:
            formatted += " + " + " + ".join(extras)

    return {"total_monthly": total, "formatted": formatted, "breakdown": breakdown}
