from __future__ import annotations

import asyncio
import re
from typing import Any

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star

from .service import (
    IpParseError,
    parse_ip,
    resolve_ip_profile,
    try_parse_ip,
)


_IP_TEXT_PATTERN = re.compile(
    r"(?i)(?<![\w.:])(?:\d{1,3}(?:\.\d{1,3}){3}|[0-9a-f]{0,4}:[0-9a-f:.]{1,})(?:/\d{1,3})?(?![\w.:])"
)
_HELP_WORDS = {"", "help", "-h", "--help", "帮助", "怎么用", "用法"}


class Main(Star):
    def __init__(self, context: Context, config: AstrBotConfig | None = None) -> None:
        super().__init__(context, config)
        self.config = config or {}

    @filter.command("ip")
    async def ip_parse(self, event: AstrMessageEvent, target: str = ""):
        text = (target or "").strip()
        if text.lower() in _HELP_WORDS or text in _HELP_WORDS:
            yield event.plain_result(self._help_text())
            return

        candidate = self._extract_ip(text)
        if not candidate:
            yield event.plain_result("没找到 IP。用法：/ip 8.8.8.8")
            return

        logger.info(f"[IP Parser] 命令解析: {candidate}")
        result = await self._build_result(candidate)
        yield self._to_message(event, result)

    @filter.regex(r"(?i)^.*(?:\d{1,3}(?:\.\d{1,3}){3}|[0-9a-f]{0,4}:[0-9a-f:.]{1,}).*$")
    async def ip_shortcut(self, event: AstrMessageEvent):
        if not self._get_bool_config("auto_parse_plain", True):
            return

        raw = (event.get_message_str() or "").strip()
        if raw.lower().startswith(("/ip", "ip ")):
            return
        candidate = self._extract_ip(raw)
        if not candidate or try_parse_ip(candidate) is None:
            return

        logger.info(f"[IP Parser] 快捷解析: {candidate}")
        result = await self._build_result(candidate)
        yield self._to_message(event, result)

    async def _build_result(self, text: str) -> str:
        try:
            parsed = parse_ip(text)
        except IpParseError as exc:
            return f"⚠️ IP 解析失败：{exc}"
        return await self._format_result(parsed)

    async def _format_result(self, parsed) -> str:
        lines = [
            "🌐 IP 解析结果",
            f"📍 地址：{parsed.normalized}",
            f"🔢 版本：IPv{parsed.version}",
            f"🏷️ 类型：{self._scope_text(parsed)}",
        ]

        if parsed.with_prefix:
            lines.extend(
                [
                    f"📦 网段：{parsed.network}",
                    f"🎭 掩码：{parsed.netmask}",
                ]
            )

        lines.extend(await self._profile_lines(parsed))
        return "\n".join(lines)

    async def _profile_lines(self, parsed) -> list[str]:
        profile = await asyncio.to_thread(
            resolve_ip_profile,
            parsed,
            enable_profile=self._get_bool_config("enable_ip_profile", True),
            skip_non_global=self._get_bool_config("skip_non_global_lookup", True),
            provider=self._get_str_config("profile_provider", "auto"),
            timeout_sec=self._get_int_config("profile_timeout_sec", 8),
        )

        lines = []
        if profile is None:
            lines.append("📌 归属：未查询")
            return lines
        if not profile.success:
            lines.append(f"📌 归属：{profile.message or '未获取到'}")
            return lines

        location = " / ".join(
            part for part in [profile.country, profile.region, profile.city, profile.district] if part
        )
        if location:
            lines.append(f"📌 归属：{location}")
        if profile.isp:
            lines.append(f"📡 运营商：{profile.isp}")
        if profile.org:
            lines.append(f"🏢 组织：{profile.org}")
        if profile.asn or profile.as_name:
            lines.append(f"🔗 ASN：{' / '.join(v for v in [profile.asn, profile.as_name] if v)}")
        lines.append(f"🧾 来源：{profile.provider}")
        return lines

    def _scope_text(self, parsed) -> str:
        if parsed.is_unspecified:
            return "未指定地址"
        if parsed.is_loopback:
            return "本机地址"
        if parsed.is_private:
            return "内网地址"
        if parsed.is_link_local:
            return "链路本地地址"
        if parsed.is_multicast:
            return "组播地址"
        if parsed.is_reserved:
            return "保留地址"
        if parsed.is_global:
            return "公网地址"
        return "特殊地址，建议结合用途判断。"

    def _flag_text(self, parsed) -> str:
        flags = []
        if parsed.is_global:
            flags.append("公网")
        if parsed.is_private:
            flags.append("内网")
        if parsed.is_loopback:
            flags.append("本机")
        if parsed.is_link_local:
            flags.append("链路本地")
        if parsed.is_multicast:
            flags.append("组播")
        if parsed.is_reserved:
            flags.append("保留")
        if parsed.is_unspecified:
            flags.append("未指定")
        return " / ".join(flags)

    def _tech_lines(self, parsed) -> list[str]:
        lines = [f"• 反向解析名：{parsed.reverse_pointer}", f"• 十六进制：{parsed.packed_hex}"]
        if parsed.binary_value:
            lines.append(f"• 二进制：{parsed.binary_value}")
        if parsed.compressed:
            lines.append(f"• IPv6 压缩：{parsed.compressed}")
        if parsed.exploded:
            lines.append(f"• IPv6 展开：{parsed.exploded}")
        if parsed.ipv4_mapped:
            lines.append(f"• IPv4 映射：{parsed.ipv4_mapped}")
        if parsed.sixtofour:
            lines.append(f"• 6to4：{parsed.sixtofour}")
        if parsed.teredo:
            lines.append(f"• Teredo：{parsed.teredo}")
        return lines

    def _extract_ip(self, text: str) -> str | None:
        text = (text or "").strip().strip("`，。；;、")
        if try_parse_ip(text) is not None:
            return text
        for match in _IP_TEXT_PATTERN.finditer(text):
            candidate = match.group(0).strip("`，。；;、")
            if try_parse_ip(candidate) is not None:
                return candidate
        return None

    def _help_text(self) -> str:
        return (
            "IP 解析\n"
            "用法：/ip <IP 或 CIDR>\n"
            "示例：/ip 8.8.8.8\n"
            "也可以直接发送纯 IP。"
        )

    def _to_message(self, event: AstrMessageEvent, text: str):
        return event.plain_result(text)

    def _get_config_value(self, key: str, default: Any) -> Any:
        if hasattr(self.config, "get"):
            try:
                return self.config.get(key, default)
            except Exception:
                return default
        return default

    def _get_bool_config(self, key: str, default: bool) -> bool:
        value = self._get_config_value(key, default)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            text = value.strip().lower()
            if text in {"1", "true", "yes", "on", "是", "开启"}:
                return True
            if text in {"0", "false", "no", "off", "否", "关闭"}:
                return False
        return bool(value)

    def _get_str_config(self, key: str, default: str) -> str:
        value = self._get_config_value(key, default)
        return str(value).strip() if value is not None else default

    def _get_int_config(self, key: str, default: int) -> int:
        value = self._get_config_value(key, default)
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            parsed = default
        return max(1, min(60, parsed))
