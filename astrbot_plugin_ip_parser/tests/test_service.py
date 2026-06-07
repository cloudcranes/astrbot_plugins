from __future__ import annotations

from pathlib import Path
import sys

import pytest

PLUGIN_DIR = Path(__file__).resolve().parents[1]
if str(PLUGIN_DIR) not in sys.path:
    sys.path.insert(0, str(PLUGIN_DIR))

from service import (  # noqa: E402
    IpParseError,
    bool_to_cn,
    lookup_ip_profile,
    parse_ip,
    resolve_ip_profile,
    try_parse_ip,
)


def test_parse_ipv4_basic():
    result = parse_ip("8.8.8.8")
    assert result.version == 4
    assert result.normalized == "8.8.8.8"
    assert result.with_prefix is False
    assert result.binary_value == "00001000.00001000.00001000.00001000"


def test_parse_ipv4_cidr():
    result = parse_ip("192.168.1.10/24")
    assert result.version == 4
    assert result.with_prefix is True
    assert result.network == "192.168.1.0/24"
    assert result.netmask == "255.255.255.0"
    assert result.hostmask == "0.0.0.255"


def test_parse_ipv6_basic():
    result = parse_ip("2001:db8::1")
    assert result.version == 6
    assert result.compressed == "2001:db8::1"
    assert result.exploded == "2001:0db8:0000:0000:0000:0000:0000:0001"
    assert result.binary_value is None


def test_parse_ipv6_cidr():
    result = parse_ip("2001:db8::1/64")
    assert result.version == 6
    assert result.with_prefix is True
    assert result.network == "2001:db8::/64"


def test_try_parse_ip_invalid():
    assert try_parse_ip("not-an-ip") is None


def test_parse_ip_invalid_raise():
    with pytest.raises(IpParseError):
        parse_ip("999.999.999.999")


def test_bool_to_cn():
    assert bool_to_cn(True) == "是"
    assert bool_to_cn(False) == "否"


def test_lookup_profile_ip_api_success():
    def fake_fetch(url: str, timeout: int):
        assert "ip-api.com" in url
        assert timeout == 8
        return {
            "status": "success",
            "query": "8.8.8.8",
            "country": "United States",
            "countryCode": "US",
            "regionName": "California",
            "city": "Mountain View",
            "zip": "94043",
            "lat": 37.386,
            "lon": -122.0838,
            "timezone": "America/Los_Angeles",
            "isp": "Google LLC",
            "org": "Google Public DNS",
            "as": "AS15169 Google LLC",
            "asname": "GOOGLE",
            "mobile": False,
            "proxy": False,
            "hosting": True,
        }

    result = lookup_ip_profile("8.8.8.8", provider="ip-api", timeout_sec=8, fetch_json=fake_fetch)
    assert result.success is True
    assert result.provider == "ip-api"
    assert result.asn == "AS15169"
    assert result.as_name == "GOOGLE"
    assert result.isp == "Google LLC"
    assert result.city == "Mountain View"


def test_lookup_profile_auto_fallback_to_ipinfo():
    state = {"count": 0}

    def fake_fetch(url: str, timeout: int):
        state["count"] += 1
        if "ip-api.com" in url:
            raise RuntimeError("ip-api blocked")
        return {
            "ip": "1.1.1.1",
            "city": "Sydney",
            "region": "New South Wales",
            "country": "AU",
            "loc": "-33.8591,151.2002",
            "org": "AS13335 Cloudflare, Inc.",
            "postal": "2000",
            "timezone": "Australia/Sydney",
        }

    result = lookup_ip_profile("1.1.1.1", provider="auto", timeout_sec=5, fetch_json=fake_fetch)
    assert result.success is True
    assert result.provider == "ipinfo"
    assert result.asn == "AS13335"
    assert result.city == "Sydney"
    assert state["count"] == 2


def test_lookup_profile_fail():
    def fake_fetch(url: str, timeout: int):
        if "ip-api.com" in url:
            return {"status": "fail", "message": "private range"}
        return {"error": {"title": "Rate limit", "message": "too many requests"}}

    result = lookup_ip_profile("10.0.0.1", provider="auto", timeout_sec=5, fetch_json=fake_fetch)
    assert result.success is False
    assert "private range" in (result.message or "")


def test_resolve_profile_skip_non_global():
    parsed = parse_ip("192.168.0.1")
    result = resolve_ip_profile(parsed, enable_profile=True, skip_non_global=True)
    assert result is not None
    assert result.success is False
    assert "已跳过" in (result.message or "")
