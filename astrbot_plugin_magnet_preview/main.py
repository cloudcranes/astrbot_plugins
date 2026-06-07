import hashlib
import re
import math
import time
from typing import Any, AsyncGenerator
import aiohttp
from astrbot.api import logger, AstrBotConfig
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Star, register, Context
import astrbot.api.message_components as comp
from .analysis import analysis, analysis_with_fallback
from .downloader import (
    BaseDownloader,
    DownloadError,
    DownloadResult,
    XunleiDownloader,
    parse_info_hash,
)

FILE_TYPE_MAP = {
    'folder': '📁 文件夹',
    'video': '🎥 视频',
    'image': '🖼 图片',
    'text': '📄 文本',
    'audio': '🎵 音频',
    'archive': '📦 压缩包',
    'document': '📑 文档',
    'unknown': '❓ 其他'
}


@register(
    "Magnet Previewer",
    "cloudcranes",
    "预览磁力链接",
    "1.0.0",
    "https://github.com/cloudcranes/astrbot_plugins/astrbot_plugin_magnet_preview",
)
class MagnetPreviewer(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        logger.info("Magnet Previewer initialized",
                    extra={"version": config.version})

        self.config = config
        # 图片域名替换配置 - 用于替换返回的图片URL域名
        self.image_domain_replacement = config.get("IMAGE_DOMAIN_REPLACEMENT", "").rstrip('/')
        # API请求地址配置 - 用于磁力链接解析的API请求
        self.whatslink_url = config.get("WHATSLINK_URL", "").rstrip('/')
        # 合并转发配置 - 控制是否使用合并转发消息格式
        self.use_forward_message = config.get("USE_FORWARD_MESSAGE", True)

        try:
            max_images = int(config.get("MAX_IMAGES", 9))
        except (TypeError, ValueError):
            max_images = 9
        self.max_screenshots = max(0, min(max_images, 9))

        self.default_downloader = "xunlei"
        self._session = None
        self._downloaders = {}
        self._cache = {}
        self._pending = {}
        try:
            self.pending_ttl_seconds = max(1, int(config.get("PENDING_TTL_SECONDS", 600)))
        except (TypeError, ValueError):
            self.pending_ttl_seconds = 600
    # ---- download confirm ----

    @filter.event_message_type(filter.EventMessageType.ALL)
    @filter.regex(r"^(yes|y|no|n|.*)$", ignorecase=True)
    async def handle_download_confirm(self, event: AstrMessageEvent):
        text_candidates = []
        for attr_name in ("get_message_str", "message_str", "raw_message"):
            value = getattr(event, attr_name, None)
            if callable(value):
                try:
                    value = value()
                except Exception:
                    value = None
            if isinstance(value, str) and value.strip():
                text_candidates.append(value.strip())
        try:
            messages = event.get_messages()
            if messages:
                text_candidates.append(str(messages[0]).strip())
        except Exception:
            pass
        confirm_words = {"yes", "y", "是", "好"}
        reject_words = {"no", "n", "否", "不用", "取消", "不下"}
        normalized_texts = [text.strip().lower() for text in text_candidates if text.strip()]
        confirm = any(text in confirm_words for text in normalized_texts)
        reject = any(text in reject_words for text in normalized_texts)
        if not confirm and not reject:
            return
        logger.info("handle_download_confirm triggered")
        pending_key = f"{event.get_session_id()}:{event.get_sender_id()}"
        pending = self._pending.get(pending_key)
        if not pending:
            return
        if time.monotonic() - pending.get("created_at", 0) > self.pending_ttl_seconds:
            self._pending.pop(pending_key, None)
            yield event.plain_result("⏰ 下载确认已超时，请重新发送磁链")
            return
        if reject:
            self._pending.pop(pending_key, None)
            yield event.plain_result("🚫 已取消本次下载")
            return
        self._pending.pop(pending_key, None)
        magnet = pending.get("magnetic_link", "")
        if not magnet:
            yield event.plain_result("⚠️ 未找到待下载的磁力链接，请重新发送磁链")
            return
        yield event.plain_result("🚀 正在提交到迅雷下载...")
        try:
            result = await self._add_magnet_to_downloader(magnet)
            yield event.plain_result(result)
        except DownloadError as exc:
            yield event.plain_result(f"❌ 迅雷提交失败：{exc}")
        except Exception as exc:
            yield event.plain_result(f"❌ 迅雷提交失败：{exc}")


    async def _get_session(self):
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30))
        return self._session

    async def terminate(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
        self._session = None
        self._cache.clear()
        self._pending.clear()
        await super().terminate()

    async def _ensure_downloaders(self):
        if self._downloaders:
            return self._downloaders
        session = await self._get_session()
        self._downloaders = {"xunlei": XunleiDownloader(
            session=session,
            host=str(self.config.get("XUNLEI_HOST", "")).strip(),
            port=str(self.config.get("XUNLEI_PORT", "")).strip(),
            ssl=bool(self.config.get("XUNLEI_SSL", False)),
            platform=str(self.config.get("XUNLEI_PLATFORM", "docker")).strip(),
        )}
        return self._downloaders

    async def _select_downloader(self):
        downloaders = await self._ensure_downloaders()
        dl = downloaders.get("xunlei")
        if dl and dl.is_enabled():
            return dl
        raise DownloadError("⚙️ 迅雷未配置，请设置 XUNLEI_HOST 和 XUNLEI_PORT")

    async def _add_magnet_to_downloader(self, magnet, display_name=""):
        await self._get_session()
        downloader = await self._select_downloader()
        result = await downloader.add(magnet, display_name=display_name)
        lines = ["✅ 下载任务已提交", f"📥 下载器：{result.downloader}", f"🆔 任务ID：{result.task_id}"]
        if result.name:
            lines.append("📝 名称：" + result.name)
        if result.message:
            lines.append("💬 备注：" + result.message)
        return chr(10).join(lines)

    @filter.event_message_type(filter.EventMessageType.ALL)
    @filter.regex(r"magnet:\?xt=urn:btih:[a-zA-Z0-9]{40}.*")
    async def handle_magnet(self, event: AstrMessageEvent) -> AsyncGenerator[Any, Any]:
        """处理磁力链接请求(优化版)"""
        messages = event.get_messages()
        plain = str(messages[0])
        m = re.search(r"magnet:\?xt=urn:btih:[a-zA-Z0-9]{40}", plain)
        if not m:
            yield event.plain_result("⚠️ 无效的磁力链接格式")
            return
        link = m.group(0)
        yield event.plain_result("正在分析磁力链接，请稍后...")

        # 解析链接
        result = None
        async with aiohttp.ClientSession() as session:
            # 使用配置的WHATSLINK_URL进行API调用
            result = await analysis_with_fallback(link, session, self.whatslink_url)
            
            # 如果配置URL解析失败，尝试使用默认的whatslink.info作为备用方案
            if result is None:
                logger.info("配置URL解析失败，尝试使用默认URL")
                result = await analysis(link, "https://whatslink.info", session)

        # 处理错误情况
        if not result or (isinstance(result, dict) and result.get('error')):
            self._cache.pop(link, None)
            self._pending.pop(f"{event.get_session_id()}:{event.get_sender_id()}", None)
            error_msg = result.get('name', '未知错误') if isinstance(result, dict) else 'API无响应'
            yield event.plain_result(f"⚠️ 解析失败：{error_msg.split('contact')[0] if isinstance(error_msg, str) else '未知错误'}")
            return

        # 确保result是有效的字典
        if not isinstance(result, dict):
            self._cache.pop(link, None)
            self._pending.pop(f"{event.get_session_id()}:{event.get_sender_id()}", None)
            yield event.plain_result("⚠️ 解析失败：API返回无效数据")
            return

        # 生成结果消息
        infos, screenshots = self._sort_infos(result)
        
        # 根据配置决定是否使用合并转发
        if self.use_forward_message:
            logger.info("使用合并转发消息格式")
            async for msg in self._send_forward_messages(event, infos, screenshots):
                yield msg
        else:
            logger.info("使用普通消息格式")
            # 发送文本消息
            if infos:
                yield event.plain_result("\n".join(infos))
            # 发送图片消息
            for screenshot in screenshots:
                yield event.image_result(screenshot)

        # Ask whether to download
        pending_key = f"{event.get_session_id()}:{event.get_sender_id()}"
        self._pending[pending_key] = {"magnetic_link": link, "created_at": time.monotonic()}
        yield event.plain_result(
            "✅ 确认下载：回复 yes / y / 是 / 好\n"
            "🚫 取消下载：回复 no / n / 否 / 取消\n"
            f"⏰ 有效时间：{self.pending_ttl_seconds // 60} 分钟"
        )

    async def _send_forward_messages(self, event: AstrMessageEvent, content: list[str], screenshots: list[str]) -> AsyncGenerator[Any, None]:
        """使用AstrBot自带合并转发功能发送消息"""
        uin = event.get_self_id()
        bot_name = "CloudCrane Bot"
        messages = []
        
        # 添加文本消息作为单独的Node
        for message in content:
            messages.append(
                comp.Node(
                    uin=uin,
                    name=bot_name,
                    content=[comp.Plain(str(message))]
                )
            )
        
        # 添加每张图片作为单独的Node
        for screenshot in screenshots:
            messages.append(
                comp.Node(
                    uin=uin,
                    name=bot_name,
                    content=[comp.Image.fromURL(screenshot)]
                )
            )
        
        merged_forward = comp.Nodes(messages)
        logger.info(f"创建了1个合并转发，包含 {len(messages)} 条消息")
        yield event.chain_result([merged_forward])

    def _sort_infos(self, info: dict) -> tuple[list[str], list[str]]:
        """整理信息(优化版)"""
        # 确保info是有效的字典
        if not isinstance(info, dict):
            return ["⚠️ 数据格式错误：无法解析磁力链接信息"], []
        
        file_type = info.get('file_type', 'unknown').lower()
        base_info = [
            f"🔍 解析结果：\r"
            f"📝 名称：{info.get('name', '未知')}\r"
            f"📦 类型：{FILE_TYPE_MAP.get(file_type, FILE_TYPE_MAP['unknown'])}\r"
            f"📏 大小：{self._format_file_size(info.get('size', 0))}\r"
            f"📚 包含文件：{info.get('count', 0)}个"
        ]

        screenshots = [
            self.replace_image_url(s["screenshot"])
            for s in (info.get('screenshots') or [])[:self.max_screenshots]
            if isinstance(s, dict) and s.get("screenshot")
        ]
        logger.info("Screenshots:", extra={"count": len(screenshots)})
        logger.info(screenshots)

        return base_info, screenshots

    @staticmethod
    def _format_file_size(size_bytes: int) -> str:
        """格式化文件大小(优化版)"""
        if not size_bytes:
            return "0B"

        units = ["B", "KB", "MB", "GB", "TB"]
        unit_index = min(int(math.log(size_bytes, 1024)), len(units) - 1)
        size = size_bytes / (1024 ** unit_index)
        return f"{size:.2f} {units[unit_index]}"

    def replace_image_url(self, image_url: str) -> str:
        """替换图片URL域名(优化版)"""
        if not image_url:
            return ""
        
        # 优先使用IMAGE_DOMAIN_REPLACEMENT进行图片域名替换
        if self.image_domain_replacement:
            return image_url.replace("https://whatslink.info", self.image_domain_replacement)
        
        # 保持向后兼容性，如果没有配置IMAGE_DOMAIN_REPLACEMENT，使用WHATSLINK_URL
        return image_url.replace("https://whatslink.info", self.whatslink_url) if self.whatslink_url else image_url



