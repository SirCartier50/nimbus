"""AWS Pricing API wrapper — boto3 pricing client mocked. Verifies parsing, the
$/hr→$/month conversion, in-process caching, regionCode filtering, and safe
degradation to None."""
import json
from unittest.mock import MagicMock, patch

import pytest

from pipeline import pricing_api


@pytest.fixture(autouse=True)
def _clear_cache():
    pricing_api.clear_cache()
    yield
    pricing_api.clear_cache()


def _dim(usd, unit="Hrs"):
    return {"unit": unit, "pricePerUnit": {"USD": f"{usd}"}}


def _price_list(*dims):
    return [json.dumps({"terms": {"OnDemand": {"OFFER": {"priceDimensions": {f"D{i}": d for i, d in enumerate(dims)}}}}})]


def test_parse_hourly_picks_lowest_positive_hourly_dimension():
    pl = _price_list(_dim(0.00), _dim(0.0104))
    assert pricing_api._parse_hourly(pl) == 0.0104


def test_parse_hourly_ignores_non_hourly_dimensions():
    # a NAT-gateway-style product with an hourly base AND a per-GB charge
    pl = _price_list(_dim(0.045, unit="Hrs"), _dim(0.045, unit="GB"))
    # only the Hrs dimension counts (here they coincide, but unit filtering is what matters)
    assert pricing_api._parse_hourly(pl) == 0.045
    # a product with ONLY a per-GB dimension yields no hourly rate
    assert pricing_api._parse_hourly(_price_list(_dim(0.09, unit="GB"))) is None


def test_parse_hourly_returns_none_for_garbage():
    assert pricing_api._parse_hourly(["not json", "{}"]) is None


def test_ec2_monthly_filters_by_region_code_and_converts_to_month():
    client = MagicMock()
    client.get_products.return_value = {"PriceList": _price_list(_dim(0.0104))}
    with patch("pipeline.pricing_api._client", return_value=client):
        monthly = pricing_api.ec2_monthly("t3.micro", "eu-west-2", session=MagicMock())
    assert monthly == round(0.0104 * 730, 2)
    filters = {f["Field"]: f["Value"] for f in client.get_products.call_args.kwargs["Filters"]}
    assert filters["instanceType"] == "t3.micro"
    assert filters["regionCode"] == "eu-west-2"   # region passed straight through, no name map
    assert "location" not in filters


def test_result_is_cached_second_call_does_not_hit_api():
    client = MagicMock()
    client.get_products.return_value = {"PriceList": _price_list(_dim(0.10))}
    with patch("pipeline.pricing_api._client", return_value=client):
        a = pricing_api.ec2_monthly("m5.large", "us-east-1", session=MagicMock())
        b = pricing_api.ec2_monthly("m5.large", "us-east-1", session=MagicMock())
    assert a == b
    client.get_products.assert_called_once()  # second call served from cache


def test_api_error_degrades_to_none():
    client = MagicMock()
    client.get_products.side_effect = Exception("AccessDenied: pricing:GetProducts")
    with patch("pipeline.pricing_api._client", return_value=client):
        assert pricing_api.ec2_monthly("t3.micro", "us-east-1", session=MagicMock()) is None


def test_rds_unmapped_engine_returns_none_without_calling_api():
    with patch("pipeline.pricing_api._client") as m:
        assert pricing_api.rds_monthly("db.t3.micro", "cassandra", "us-east-1", session=MagicMock()) is None
    m.assert_not_called()


def test_nat_gateway_and_load_balancer_query_by_product_family():
    client = MagicMock()
    client.get_products.return_value = {"PriceList": _price_list(_dim(0.045))}
    with patch("pipeline.pricing_api._client", return_value=client):
        nat = pricing_api.nat_gateway_monthly("us-east-1", session=MagicMock())
        pricing_api.load_balancer_monthly("us-east-1", session=MagicMock())
    assert nat == round(0.045 * 730, 2)
    families = [
        {f["Field"]: f["Value"] for f in call.kwargs["Filters"]}["productFamily"]
        for call in client.get_products.call_args_list
    ]
    assert "NAT Gateway" in families
    assert "Load Balancer-Application" in families
