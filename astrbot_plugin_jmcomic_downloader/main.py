from __future__ import annotations

import asyncio
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections.abc import AsyncGenerator
from pathlib import Path

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, StarTools, register

from .service import (
    JmcomicDownloadConfig,
    JmcomicDownloadError,
    JmcomicDownloadResult,
    JmcomicDownloaderService,
    format_size,
    validate_album_id,
)


@register(
    "JMComic Downloader",
    "cloudcranes",
    "按 JM album id 下载漫画并生成 PDF",
    "0.1.0",
    "https://github.com/cloudcranes/astrbot_plugins/astrbot_plugin_jmcomic_downloader",
)
class JmcomicDownloaderPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig | None = None) -> None:
        super().__init__(context)
        self.config = config or {}
        self.data_dir = Path(StarTools.get_data_dir("astrbot_plugin_jmcomic_downloader"))
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self._service = JmcomicDownloaderService(
            JmcomicDownloadConfig(
                data_dir=self.data_dir,
                download_root=self._get_download_root(),
                retention_days=self._get_int_config("retention_days", 7, 1, 365),
                app_domain=self._get_str_config("app_domain", ""),
                jm_username=self._get_str_config("jm_username", ""),
                jm_password=self._get_str_config("jm_password", ""),
                proxy=self._get_str_config("proxy", ""),
                cookies=self._get_str_config("cookies", ""),
                auto_install_dependencies=self._get_bool_config("auto_install_dependencies", True),
            )
        )
        self._max_send_bytes = self._get_int_config("max_send_mb", 100, 1, 2048) * 1024 * 1024
        self._semaphore = asyncio.Semaphore(self._get_int_config("max_concurrent_downloads", 1, 1, 5))
        self._running_users: set[str] = set()

    @filter.regex(r"^jm\d+$", ignorecase=True)
    async def jm_download_by_text(self, event: AstrMessageEvent):
        album_id = self._parse_jm_text(self._event_text(event))
        if not album_id:
            return
        async for result in self._download_and_send(event, album_id):
            yield result

    @filter.command_group("jm")
    def jm(self) -> None:
        """JMComic 漫画下载。"""

    @jm.command("help")
    async def jm_help(self, event: AstrMessageEvent):
        yield event.plain_result(self._help_text())

    @jm.command("dl")
    async def jm_download(self, event: AstrMessageEvent, album_id: str = ""):
        async for result in self._download_and_send(event, album_id):
            yield result

    @jm.command("clean")
    async def jm_clean(self, event: AstrMessageEvent, mode: str = ""):
        if not self._is_authorized(event):
            yield event.plain_result("无权限：下载功能仅对白名单用户开放")
            return
        clean_all = mode.strip().lower() in {"all", "全部"}
        if clean_all:
            download_count, pdf_count = await asyncio.to_thread(self._service.cleanup_all)
        else:
            download_count, pdf_count = await asyncio.to_thread(self._service.cleanup_expired)
        openlist_count = 0
        if self._get_bool_config("openlist_cleanup_on_clean", True):
            try:
                openlist_count = await asyncio.to_thread(self._cleanup_openlist_expired, clean_all)
            except JmcomicDownloadError as exc:
                yield event.plain_result(
                    f"本地清理完成：下载目录 {download_count} 项，PDF 目录 {pdf_count} 项\n"
                    f"OpenList 清理失败：{exc}"
                )
                return
        label = "全部清理完成" if clean_all else "清理完成"
        yield event.plain_result(f"{label}：下载目录 {download_count} 项，PDF 目录 {pdf_count} 项，OpenList {openlist_count} 项")

    async def _download_and_send(self, event: AstrMessageEvent, album_id: str) -> AsyncGenerator[object, None]:
        if not self._is_authorized(event):
            yield event.plain_result("无权限：下载功能仅对白名单用户开放")
            return

        try:
            album_id = validate_album_id(album_id)
        except ValueError:
            yield event.plain_result("用法：jm123456 或 /jm dl 123456")
            return

        sender_id = event.get_sender_id()
        if sender_id in self._running_users:
            yield event.plain_result("你已有下载任务正在运行，请等待完成")
            return

        task_id = uuid.uuid4().hex[:8]
        self._running_users.add(sender_id)
        yield event.plain_result(f"开始下载：{album_id}\n任务 ID：{task_id}")

        try:
            async with self._semaphore:
                result = await asyncio.to_thread(self._service.download_album, album_id, task_id)
        except JmcomicDownloadError as exc:
            logger.error(f"JMComic 下载失败 album_id={album_id}: {exc}")
            yield event.plain_result(f"下载失败：{exc}")
            return
        except Exception as exc:
            logger.error(f"JMComic 下载异常 album_id={album_id}: {exc}")
            yield event.plain_result("下载异常，请查看日志")
            return
        finally:
            self._running_users.discard(sender_id)

        try:
            safe_name = f"{result.album_id}.pdf"
            file_url = await asyncio.to_thread(self._upload_to_openlist, result.pdf_path, safe_name)
        except JmcomicDownloadError as exc:
            logger.error(f"OpenList 上传失败 album_id={album_id}: {exc}")
            yield event.plain_result(f"PDF 已生成，但上传 OpenList 失败：{exc}\n{result.pdf_path}")
            return

        import astrbot.api.message_components as Comp

        name = f"{result.album_id}.pdf"
        yield event.chain_result([
            Comp.Plain(self._done_text(result)),
            Comp.File(url=file_url, name=name),
        ])

    def _upload_to_openlist(self, file_path: Path, file_name: str) -> str:
        base_url = self._get_str_config("openlist_base_url", "").rstrip("/")
        if not base_url:
            raise JmcomicDownloadError("请先配置 openlist_base_url")

        token = self._get_openlist_token(base_url)
        upload_root = "/" + self._get_str_config("openlist_upload_dir", "/jmcomic").strip("/")
        upload_dir = f"/{file_path.parent.name}" if upload_root == "/" else f"{upload_root}/{file_path.parent.name}"
        remote_path = f"{upload_dir}/{file_name}"

        if upload_root != "/":
            self._openlist_mkdir(base_url, upload_root, token)
        self._openlist_mkdir(base_url, upload_dir, token)
        headers = {
            "Authorization": token,
            "File-Path": urllib.parse.quote(remote_path, safe="/"),
            "Content-Type": "application/octet-stream",
        }
        with file_path.open("rb") as file:
            request = urllib.request.Request(
                f"{base_url}/api/fs/put",
                data=file.read(),
                headers=headers,
                method="PUT",
            )
        self._openlist_json(request)

        public_base = self._get_str_config("openlist_public_base_url", "").rstrip("/") or base_url
        return f"{public_base}/d{urllib.parse.quote(remote_path, safe='/')}"

    def _get_openlist_token(self, base_url: str) -> str:
        token = self._get_str_config("openlist_token", "")
        if token:
            return token

        username = self._get_str_config("openlist_username", "")
        password = self._get_str_config("openlist_password", "")
        if not username or not password:
            raise JmcomicDownloadError("请配置 openlist_token，或配置 openlist_username/openlist_password")

        payload = json.dumps({"username": username, "password": password}).encode("utf-8")
        request = urllib.request.Request(
            f"{base_url}/api/auth/login",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        data = self._openlist_json(request)
        token = str(data.get("data", {}).get("token", "")).strip()
        if not token:
            raise JmcomicDownloadError("OpenList 登录成功但未返回 token")
        return token

    def _openlist_mkdir(self, base_url: str, path: str, token: str) -> None:
        payload = json.dumps({"path": path}).encode("utf-8")
        request = urllib.request.Request(
            f"{base_url}/api/fs/mkdir",
            data=payload,
            headers={"Authorization": token, "Content-Type": "application/json"},
            method="POST",
        )
        try:
            self._openlist_json(request)
        except JmcomicDownloadError as exc:
            message = str(exc)
            if "already" not in message.lower() and "exist" not in message.lower() and "已存在" not in message:
                raise

    def _cleanup_openlist_expired(self, clean_all: bool = False) -> int:
        base_url = self._get_str_config("openlist_base_url", "").rstrip("/")
        if not base_url:
            raise JmcomicDownloadError("请先配置 openlist_base_url")
        token = self._get_openlist_token(base_url)
        upload_root = "/" + self._get_str_config("openlist_upload_dir", "/jmcomic").strip("/")
        max_age = self._get_int_config("retention_days", 7, 1, 365) * 86400
        cutoff = int(time.time()) - max_age

        items = self._openlist_list(base_url, upload_root, token)
        expired: list[str] = []
        for item in items:
            name = str(item.get("name", ""))
            if not name.startswith("album_"):
                continue
            local_pdf_dir = self._service.pdf_root / name
            local_download_dir = self._service.config.download_root / name
            modified = self._openlist_modified_ts(item)
            local_missing = not local_pdf_dir.exists() and not local_download_dir.exists()
            openlist_expired = bool(modified and modified < cutoff)
            if clean_all or local_missing or openlist_expired:
                expired.append(f"{upload_root}/{name}" if upload_root != "/" else f"/{name}")

        for path in expired:
            self._openlist_remove(base_url, path, token)
        return len(expired)

    def _openlist_list(self, base_url: str, path: str, token: str) -> list[dict]:
        payload = json.dumps({"path": path, "page": 1, "per_page": 1000, "refresh": False}).encode("utf-8")
        request = urllib.request.Request(
            f"{base_url}/api/fs/list",
            data=payload,
            headers={"Authorization": token, "Content-Type": "application/json"},
            method="POST",
        )
        data = self._openlist_json(request)
        content = data.get("data", {}).get("content", [])
        return content if isinstance(content, list) else []

    def _openlist_remove(self, base_url: str, path: str, token: str) -> None:
        parent, name = path.rsplit("/", 1)
        parent = parent or "/"
        payload = json.dumps({"dir": parent, "names": [name]}).encode("utf-8")
        request = urllib.request.Request(
            f"{base_url}/api/fs/remove",
            data=payload,
            headers={"Authorization": token, "Content-Type": "application/json"},
            method="POST",
        )
        self._openlist_json(request)

    def _openlist_modified_ts(self, item: dict) -> int:
        value = item.get("modified") or item.get("updated_at") or item.get("time")
        if isinstance(value, (int, float)):
            return int(value)
        if not value:
            return 0
        text = str(value).replace("Z", "+00:00")
        try:
            from datetime import datetime

            return int(datetime.fromisoformat(text).timestamp())
        except ValueError:
            return 0

    def _openlist_json(self, request: urllib.request.Request) -> dict:
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                raw = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            raise JmcomicDownloadError(f"OpenList HTTP {exc.code}: {raw[-300:]}") from exc
        except urllib.error.URLError as exc:
            raise JmcomicDownloadError(f"OpenList 请求失败：{exc.reason}") from exc

        try:
            data = json.loads(raw) if raw else {}
        except json.JSONDecodeError as exc:
            raise JmcomicDownloadError(f"OpenList 返回非 JSON：{raw[-300:]}") from exc

        code = data.get("code", 200)
        if code not in (200, 0):
            raise JmcomicDownloadError(str(data.get("message") or data.get("msg") or data))
        return data

    def _is_authorized(self, event: AstrMessageEvent) -> bool:
        is_admin = getattr(event, "is_admin", None)
        if callable(is_admin):
            try:
                if is_admin():
                    return True
            except Exception:
                pass
        whitelist = self._get_whitelist()
        return bool(whitelist) and event.get_sender_id() in whitelist

    def _get_whitelist(self) -> set[str]:
        raw = self.config.get("whitelist", [])
        if not isinstance(raw, list):
            return set()
        return {str(item).strip() for item in raw if str(item).strip()}

    def _get_download_root(self) -> Path:
        configured = self._get_str_config("download_dir", "")
        if configured:
            return Path(configured).expanduser()
        return self.data_dir / "downloads"

    def _get_str_config(self, key: str, default: str) -> str:
        value = self.config.get(key, default)
        return str(value).strip() if value is not None else default

    def _get_int_config(self, key: str, default: int, min_value: int, max_value: int) -> int:
        try:
            value = int(self.config.get(key, default))
        except (TypeError, ValueError):
            value = default
        return max(min_value, min(max_value, value))

    def _get_bool_config(self, key: str, default: bool) -> bool:
        value = self.config.get(key, default)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on", "启用", "是"}
        return bool(value)

    def _event_text(self, event: AstrMessageEvent) -> str:
        getter = getattr(event, "get_message_str", None)
        if callable(getter):
            text = getter()
            if text:
                return str(text).strip()
        getter = getattr(event, "get_message_outline", None)
        if callable(getter):
            text = getter()
            if text:
                return str(text).strip()
        return ""

    def _parse_jm_text(self, text: str) -> str:
        match = re.fullmatch(r"jm(\d+)", str(text or "").strip(), re.IGNORECASE)
        return match.group(1) if match else ""

    def _done_text(self, result: JmcomicDownloadResult) -> str:
        return (
            "✅ 下载完成\n"
            f"📄 文件：{result.album_id}.pdf\n"
            f"📦 大小：{format_size(result.pdf_size)}"
        )

    def _path_text(self, result: JmcomicDownloadResult) -> str:
        return (
            "PDF 已生成，文件过大不发送：\n"
            f"{result.pdf_path}\n"
            f"大小：{format_size(result.pdf_size)}，发送上限：{format_size(self._max_send_bytes)}"
        )

    def _help_text(self) -> str:
        return (
            "JMComic 下载插件\n"
            "直接发送 jm123456 可下载漫画\n"
            "/jm dl <album_id> - 下载漫画并生成 PDF\n"
            "/jm clean - 清理过期文件\n"
            "/jm clean all - 清理全部缓存"
        )
