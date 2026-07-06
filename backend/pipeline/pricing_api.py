"""Live AWS Pricing API lookups for the flat-rate resources where the static table
in cost.py is weakest: EC2, RDS, ElastiCache, NAT Gateway, Load Balancer.

Everything here degrades safely. Any failure — a missing `pricing:GetProducts`
permission, an unmapped DB engine, a throttle, a parsing miss — returns None, and
cost.py falls back to its static estimate. The estimate at the approval gate must
never break, so live pricing is strictly an upgrade over the static number, never a
hard dependency.

The Pricing API is only served from a few regions, so the client is always pinned to
us-east-1. The deployment region is passed as a `regionCode` *filter* (e.g.
"us-east-1") — no region→location-name table to maintain; the API resolves it.

Prices are public list prices (account-independent) and change rarely, so results are
cached process-wide with a long TTL. No Redis yet (PROD-3); a module dict is fine here.
"""
import json
import time

_PRICING_ENDPOINT_REGION = "us-east-1"
_CACHE_TTL_SECONDS = 24 * 3600
_HOURS_PER_MONTH = 730

_cache: dict = {}

# Config-vocabulary → Pricing-API-vocabulary adapters. These are genuine name
# translations (the create-config calls a Postgres engine "postgres"; the Pricing API
# calls it "PostgreSQL") — no API exposes this mapping, so it stays a small constant.
_RDS_ENGINE = {
    "postgres": "PostgreSQL", "postgresql": "PostgreSQL",
    "mysql": "MySQL", "mariadb": "MariaDB",
    "oracle-se2": "Oracle", "oracle-ee": "Oracle",
    "sqlserver-ex": "SQL Server", "sqlserver-web": "SQL Server",
    "sqlserver-se": "SQL Server", "sqlserver-ee": "SQL Server",
}
_CACHE_ENGINE = {"redis": "Redis", "memcached": "Memcached", "valkey": "Valkey"}


def clear_cache() -> None:
    _cache.clear()


def _client(session):
    if session is not None:
        return session.client("pricing", region_name=_PRICING_ENDPOINT_REGION)
    import boto3
    return boto3.client("pricing", region_name=_PRICING_ENDPOINT_REGION)


def _parse_hourly(price_list: list) -> float | None:
    """Pull the lowest positive on-demand $/hour out of a get_products PriceList.
    Only counts dimensions billed per hour (unit "Hrs"), so per-GB / per-LCU
    dimensions on NAT Gateway and ALB products don't get mistaken for the base rate."""
    prices = []
    for item in price_list:
        try:
            data = json.loads(item)
            for offer in data["terms"]["OnDemand"].values():
                for dim in offer["priceDimensions"].values():
                    if dim.get("unit") != "Hrs":
                        continue
                    usd = float(dim["pricePerUnit"]["USD"])
                    if usd > 0:
                        prices.append(usd)
        except (KeyError, ValueError, TypeError):
            continue
    return min(prices) if prices else None


def _query_monthly_usd(session, service_code: str, filters: dict) -> float | None:
    """Look up on-demand $/hour for a filtered product and return $/month. Cached
    across users (list prices are account-independent). Returns None on any failure so
    the caller can fall back to the static table."""
    key = (service_code, tuple(sorted(filters.items())))
    hit = _cache.get(key)
    if hit and (time.time() - hit[0]) < _CACHE_TTL_SECONDS:
        hourly = hit[1]
    else:
        try:
            client = _client(session)
            resp = client.get_products(
                ServiceCode=service_code,
                Filters=[{"Type": "TERM_MATCH", "Field": k, "Value": v} for k, v in filters.items()],
                MaxResults=100,
            )
            hourly = _parse_hourly(resp.get("PriceList", []))
        except Exception:
            hourly = None
        _cache[key] = (time.time(), hourly)

    return round(hourly * _HOURS_PER_MONTH, 2) if hourly is not None else None


def ec2_monthly(instance_type: str, region: str, session) -> float | None:
    return _query_monthly_usd(session, "AmazonEC2", {
        "instanceType": instance_type,
        "regionCode": region,
        "operatingSystem": "Linux",
        "tenancy": "Shared",
        "preInstalledSw": "NA",
        "capacitystatus": "Used",
    })


def rds_monthly(instance_class: str, engine: str, region: str, session) -> float | None:
    db_engine = _RDS_ENGINE.get((engine or "").lower())
    if not db_engine:
        return None
    return _query_monthly_usd(session, "AmazonRDS", {
        "instanceType": instance_class,
        "regionCode": region,
        "databaseEngine": db_engine,
        "deploymentOption": "Single-AZ",
    })


def elasticache_monthly(node_type: str, engine: str, region: str, session) -> float | None:
    return _query_monthly_usd(session, "AmazonElastiCache", {
        "instanceType": node_type,
        "regionCode": region,
        "cacheEngine": _CACHE_ENGINE.get((engine or "redis").lower(), "Redis"),
    })


def nat_gateway_monthly(region: str, session) -> float | None:
    return _query_monthly_usd(session, "AmazonEC2", {
        "regionCode": region,
        "productFamily": "NAT Gateway",
    })


def load_balancer_monthly(region: str, session) -> float | None:
    # Application Load Balancer hourly base (LCU charges are usage-based, excluded).
    return _query_monthly_usd(session, "AWSELB", {
        "regionCode": region,
        "productFamily": "Load Balancer-Application",
    })
