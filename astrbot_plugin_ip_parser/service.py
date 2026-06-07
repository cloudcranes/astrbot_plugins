from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import json
import urllib.parse
import urllib.request
from typing import Any, Callable


class IpParseError(Exception):
    """IP 解析异常。"""


JsonFetcher = Callable[[str, int], dict[str, Any]]


@dataclass(frozen=True)
class IpParseResult:
    original_input: str
    normalized: str
    version: int
    with_prefix: bool
    prefix_len: int | None
    network: str | None
    netmask: str | None
    hostmask: str | None
    reverse_pointer: str
    is_private: bool
    is_global: bool
    is_reserved: bool
    is_loopback: bool
    is_link_local: bool
    is_multicast: bool
    is_unspecified: bool
    compressed: str | None
    exploded: str | None
    ipv4_mapped: str | None
    sixtofour: str | None
    teredo: str | None
    integer_value: int
    packed_hex: str
    binary_value: str | None


@dataclass(frozen=True)
class IpProfileResult:
    success: bool
    provider: str | None
    query_ip: str
    country: str | None = None
    country_code: str | None = None
    region: str | None = None
    city: str | None = None
    district: str | None = None
    postal: str | None = None
    timezone: str | None = None
    isp: str | None = None
    org: str | None = None
    asn: str | None = None
    as_name: str | None = None
    domain: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    mobile: bool | None = None
    proxy: bool | None = None
    hosting: bool | None = None
    message: str | None = None


def _to_binary_ipv4(addr: ipaddress.IPv4Address) -> str:
    return ".".join(f"{octet:08b}" for octet in addr.packed)


def parse_ip(target: str) -> IpParseResult:
    text = (target or "").strip()
    if not text:
        raise IpParseError("IP 地址不能为空。")

    try:
        if "/" in text:
            interface = ipaddress.ip_interface(text)
            addr = interface.ip
            network = interface.network
            with_prefix = True
            prefix_len = int(network.prefixlen)
            network_text = network.with_prefixlen
            netmask = str(network.netmask)
            hostmask = str(network.hostmask)
        else:
            addr = ipaddress.ip_address(text)
            with_prefix = False
            prefix_len = None
            network_text = None
            netmask = None
            hostmask = None
    except ValueError as exc:
        raise IpParseError(f"无效的 IP 地址: {text}") from exc

    compressed = None
    exploded = None
    ipv4_mapped = None
    sixtofour = None
    teredo = None
    binary_value = None

    if isinstance(addr, ipaddress.IPv6Address):
        compressed = addr.compressed
        exploded = addr.exploded
        ipv4_mapped = str(addr.ipv4_mapped) if addr.ipv4_mapped else None
        sixtofour = str(addr.sixtofour) if addr.sixtofour else None
        teredo_value = addr.teredo
        if teredo_value:
            teredo = f"{teredo_value[0]} / {teredo_value[1]}"
    else:
        binary_value = _to_binary_ipv4(addr)

    return IpParseResult(
        original_input=text,
        normalized=str(addr),
        version=addr.version,
        with_prefix=with_prefix,
        prefix_len=prefix_len,
        network=network_text,
        netmask=netmask,
        hostmask=hostmask,
        reverse_pointer=addr.reverse_pointer,
        is_private=addr.is_private,
        is_global=addr.is_global,
        is_reserved=addr.is_reserved,
        is_loopback=addr.is_loopback,
        is_link_local=addr.is_link_local,
        is_multicast=addr.is_multicast,
        is_unspecified=addr.is_unspecified,
        compressed=compressed,
        exploded=exploded,
        ipv4_mapped=ipv4_mapped,
        sixtofour=sixtofour,
        teredo=teredo,
        integer_value=int(addr),
        packed_hex=addr.packed.hex(),
        binary_value=binary_value,
    )


def try_parse_ip(text: str) -> IpParseResult | None:
    try:
        return parse_ip(text)
    except IpParseError:
        return None


def _default_fetch_json(url: str, timeout_sec: int) -> dict[str, Any]:
    req = urllib.request.Request(
        url=url,
        headers={"User-Agent": "astrbot-plugin-ip-parser/0.2"},
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=timeout_sec) as response:
        body = response.read().decode("utf-8", errors="replace")
    data = json.loads(body)
    if not isinstance(data, dict):
        raise ValueError("接口返回不是 JSON 对象")
    return data


def _split_as_field(as_field: str | None, as_name: str | None) -> tuple[str | None, str | None]:
    text = (as_field or "").strip()
    if not text:
        return None, (as_name or None)

    parts = text.split(maxsplit=1)
    if len(parts) == 1:
        if parts[0].upper().startswith("AS"):
            return parts[0].upper(), (as_name or None)
        return None, text

    head, tail = parts[0], parts[1]
    if head.upper().startswith("AS"):
        return head.upper(), (as_name or tail)
    return None, (as_name or text)


def _as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return None


def _lookup_ip_api(
    ip: str,
    *,
    timeout_sec: int,
    fetch_json: JsonFetcher,
) -> IpProfileResult:
    encoded_ip = urllib.parse.quote(ip, safe="")
    fields = ",".join(
        [
            "status",
            "message",
            "country",
            "countryCode",
            "regionName",
            "city",
            "district",
            "zip",
            "lat",
            "lon",
            "timezone",
            "isp",
            "org",
            "as",
            "asname",
            "mobile",
            "proxy",
            "hosting",
            "query",
        ]
    )
    url = f"http://ip-api.com/json/{encoded_ip}?lang=zh-CN&fields={fields}"
    data = fetch_json(url, timeout_sec)

    status = str(data.get("status", "")).lower()
    if status != "success":
        msg = str(data.get("message", "查询失败"))
        return IpProfileResult(
            success=False,
            provider="ip-api",
            query_ip=ip,
            message=f"ip-api: {msg}",
        )

    asn, as_name = _split_as_field(
        as_field=str(data.get("as", "") or ""),
        as_name=str(data.get("asname", "") or "") or None,
    )

    return IpProfileResult(
        success=True,
        provider="ip-api",
        query_ip=str(data.get("query", ip)),
        country=str(data.get("country", "") or "") or None,
        country_code=str(data.get("countryCode", "") or "") or None,
        region=str(data.get("regionName", "") or "") or None,
        city=str(data.get("city", "") or "") or None,
        district=str(data.get("district", "") or "") or None,
        postal=str(data.get("zip", "") or "") or None,
        timezone=str(data.get("timezone", "") or "") or None,
        isp=str(data.get("isp", "") or "") or None,
        org=str(data.get("org", "") or "") or None,
        asn=asn,
        as_name=as_name,
        latitude=_as_float(data.get("lat")),
        longitude=_as_float(data.get("lon")),
        mobile=_as_bool(data.get("mobile")),
        proxy=_as_bool(data.get("proxy")),
        hosting=_as_bool(data.get("hosting")),
    )


def _lookup_ipinfo(
    ip: str,
    *,
    timeout_sec: int,
    fetch_json: JsonFetcher,
) -> IpProfileResult:
    encoded_ip = urllib.parse.quote(ip, safe="")
    url = f"https://ipinfo.io/{encoded_ip}/json"
    data = fetch_json(url, timeout_sec)

    if "bogon" in data and data.get("bogon"):
        return IpProfileResult(
            success=False,
            provider="ipinfo",
            query_ip=ip,
            message="ipinfo: 非公网地址或不可路由地址",
        )

    if data.get("error"):
        error_data = data.get("error")
        if isinstance(error_data, dict):
            title = str(error_data.get("title", "查询失败"))
            message = str(error_data.get("message", "")).strip()
            msg = f"{title}: {message}".strip(": ")
        else:
            msg = str(error_data)
        return IpProfileResult(
            success=False,
            provider="ipinfo",
            query_ip=ip,
            message=f"ipinfo: {msg}",
        )

    loc = str(data.get("loc", "") or "")
    lat = None
    lon = None
    if "," in loc:
        p1, p2 = loc.split(",", 1)
        lat = _as_float(p1)
        lon = _as_float(p2)

    asn, as_name = _split_as_field(
        as_field=str(data.get("org", "") or ""),
        as_name=None,
    )

    return IpProfileResult(
        success=True,
        provider="ipinfo",
        query_ip=str(data.get("ip", ip)),
        country=str(data.get("country", "") or "") or None,
        country_code=str(data.get("country", "") or "") or None,
        region=str(data.get("region", "") or "") or None,
        city=str(data.get("city", "") or "") or None,
        postal=str(data.get("postal", "") or "") or None,
        timezone=str(data.get("timezone", "") or "") or None,
        org=str(data.get("org", "") or "") or None,
        asn=asn,
        as_name=as_name,
        latitude=lat,
        longitude=lon,
    )


def lookup_ip_profile(
    ip: str,
    *,
    provider: str = "auto",
    timeout_sec: int = 8,
    fetch_json: JsonFetcher | None = None,
) -> IpProfileResult:
    fetcher = fetch_json or _default_fetch_json
    provider_text = str(provider or "auto").strip().lower()

    providers: list[str]
    if provider_text == "auto":
        providers = ["ip-api", "ipinfo"]
    elif provider_text in {"ip-api", "ipinfo"}:
        providers = [provider_text]
    else:
        return IpProfileResult(
            success=False,
            provider=None,
            query_ip=ip,
            message=f"不支持的画像提供方: {provider}",
        )

    errors: list[str] = []
    for item in providers:
        try:
            if item == "ip-api":
                result = _lookup_ip_api(ip, timeout_sec=timeout_sec, fetch_json=fetcher)
            else:
                result = _lookup_ipinfo(ip, timeout_sec=timeout_sec, fetch_json=fetcher)
        except Exception as exc:
            errors.append(f"{item}: {exc}")
            continue

        if result.success:
            return result
        errors.append(result.message or f"{item}: 查询失败")

    return IpProfileResult(
        success=False,
        provider=providers[0] if providers else None,
        query_ip=ip,
        message="; ".join(errors) if errors else "运营商归属地查询失败",
    )


def resolve_ip_profile(
    parsed: IpParseResult,
    *,
    enable_profile: bool = True,
    skip_non_global: bool = True,
    provider: str = "auto",
    timeout_sec: int = 8,
    fetch_json: JsonFetcher | None = None,
) -> IpProfileResult | None:
    if not enable_profile:
        return None

    if skip_non_global and not parsed.is_global:
        return IpProfileResult(
            success=False,
            provider=None,
            query_ip=parsed.normalized,
            message="当前地址不是公网地址，已跳过运营商归属地查询。",
        )

    return lookup_ip_profile(
        parsed.normalized,
        provider=provider,
        timeout_sec=timeout_sec,
        fetch_json=fetch_json,
    )


def bool_to_cn(value: Any) -> str:
    return "是" if bool(value) else "否"
