from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ALBUM_ID_PATTERN = re.compile(r"^\d+$")


class JmcomicDownloadError(Exception):
    """JMComic 下载失败。"""


@dataclass(frozen=True)
class JmcomicDownloadConfig:
    data_dir: Path
    download_root: Path
    retention_days: int = 7
    app_domain: str = ""
    jm_username: str = ""
    jm_password: str = ""
    proxy: str = ""
    cookies: str = ""
    auto_install_dependencies: bool = True


@dataclass(frozen=True)
class JmcomicDownloadResult:
    album_id: str
    task_id: str
    option_path: Path
    download_dir: Path
    pdf_dir: Path
    pdf_path: Path
    pdf_size: int


def validate_album_id(album_id: str) -> str:
    album_id = str(album_id or "").strip()
    if not ALBUM_ID_PATTERN.fullmatch(album_id):
        raise ValueError("album_id 只能是纯数字")
    return album_id


def parse_cookie_header(cookie_header: str) -> dict[str, str]:
    cookies: dict[str, str] = {}
    for item in str(cookie_header or "").split(";"):
        if "=" not in item:
            continue
        key, value = item.split("=", 1)
        key = key.strip()
        if key:
            cookies[key] = value.strip()
    return cookies


def format_size(size: int) -> str:
    units = ["B", "KB", "MB", "GB"]
    value = float(size)
    index = 0
    while value >= 1024 and index < len(units) - 1:
        value /= 1024
        index += 1
    if index == 0:
        return f"{int(value)}{units[index]}"
    return f"{value:.2f}{units[index]}"


class JmcomicDownloaderService:
    def __init__(self, config: JmcomicDownloadConfig) -> None:
        self.config = config
        self.config.data_dir.mkdir(parents=True, exist_ok=True)
        self.config.download_root.mkdir(parents=True, exist_ok=True)
        self.pdf_root.mkdir(parents=True, exist_ok=True)

    @property
    def pdf_root(self) -> Path:
        return self.config.data_dir / "pdf"

    def download_album(self, album_id: str, task_id: str) -> JmcomicDownloadResult:
        album_id = validate_album_id(album_id)
        task_id = self._safe_task_id(task_id)
        cache_id = self._album_cache_id(album_id)
        download_dir = self.config.download_root / cache_id
        pdf_dir = self.pdf_root / cache_id
        cached_pdf = self.find_latest_pdf(pdf_dir)
        if cached_pdf is not None:
            return self._result_from_pdf(album_id, task_id, download_dir, pdf_dir, cached_pdf)

        started_at = time.time()
        download_dir.mkdir(parents=True, exist_ok=True)
        pdf_dir.mkdir(parents=True, exist_ok=True)

        jmcomic = self._ensure_dependencies()
        option_path = self.write_option_file(download_dir=download_dir, pdf_dir=pdf_dir, task_id=task_id)

        try:
            option = jmcomic.create_option_by_file(str(option_path))
            jmcomic.download_album(album_id, option)
        except Exception as exc:  # jmcomic 抛出的异常类型不稳定，统一转用户提示。
            raise JmcomicDownloadError(f"jmcomic APP 下载失败：{exc}") from exc

        pdf_path = self.find_latest_pdf(pdf_dir, started_at=started_at)
        if pdf_path is None:
            raise JmcomicDownloadError(f"下载完成但未生成 PDF，文件目录：{download_dir}")

        return self._result_from_pdf(album_id, task_id, download_dir, pdf_dir, pdf_path, option_path)

    def _result_from_pdf(
        self,
        album_id: str,
        task_id: str,
        download_dir: Path,
        pdf_dir: Path,
        pdf_path: Path,
        option_path: Path | None = None,
    ) -> JmcomicDownloadResult:
        return JmcomicDownloadResult(
            album_id=album_id,
            task_id=task_id,
            option_path=option_path or self.config.data_dir / "op.yml",
            download_dir=download_dir,
            pdf_dir=pdf_dir,
            pdf_path=pdf_path,
            pdf_size=pdf_path.stat().st_size,
        )

    def _normalize_domain_candidates(self, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            values = [value]
        elif isinstance(value, (list, tuple, set)):
            values = list(value)
        else:
            return []
        domains: list[str] = []
        for item in values:
            text = str(item or "").strip()
            if not text:
                continue
            text = text.removeprefix("https://").removeprefix("http://").strip("/")
            if text:
                domains.append(text)
        return domains

    def _dedupe_domains(self, domains: list[str]) -> list[str]:
        seen: set[str] = set()
        unique: list[str] = []
        for domain in domains:
            text = str(domain or "").strip()
            if not text:
                continue
            key = text.lower()
            if key in seen:
                continue
            seen.add(key)
            unique.append(text)
        return unique

    def _ensure_dependencies(self):
        try:
            import img2pdf  # noqa: F401
            import jmcomic
            return jmcomic
        except ImportError as exc:
            if not self.config.auto_install_dependencies:
                raise JmcomicDownloadError("缺少 jmcomic/img2pdf 依赖，请安装 requirements.txt") from exc

        requirements_path = Path(__file__).with_name("requirements.txt")
        if not requirements_path.exists():
            raise JmcomicDownloadError("缺少 requirements.txt，无法自动安装 jmcomic/img2pdf")

        try:
            subprocess.run(
                [sys.executable, "-m", "pip", "install", "-r", str(requirements_path)],
                check=True,
                capture_output=True,
                text=True,
                timeout=300,
            )
        except subprocess.TimeoutExpired as exc:
            raise JmcomicDownloadError("自动安装 jmcomic/img2pdf 超时，请手动安装 requirements.txt") from exc
        except subprocess.CalledProcessError as exc:
            error = (exc.stderr or exc.stdout or "").strip()
            raise JmcomicDownloadError(f"自动安装 jmcomic/img2pdf 失败：{error[-500:]}") from exc

        try:
            import img2pdf  # noqa: F401
            import jmcomic
            return jmcomic
        except ImportError as exc:
            raise JmcomicDownloadError("自动安装后仍无法导入 jmcomic/img2pdf") from exc

    def write_option_file(self, download_dir: Path, pdf_dir: Path, task_id: str) -> Path:
        option_path = self.config.data_dir / "op.yml"
        text = self.build_option_text(download_dir=download_dir, pdf_dir=pdf_dir)
        self._atomic_write_text(option_path, text)
        return option_path

    def build_option_text(self, download_dir: Path, pdf_dir: Path) -> str:
        proxy = str(self.config.proxy or "").strip()
        cookies = parse_cookie_header(self.config.cookies)
        app_domains = self._dedupe_domains(self._normalize_domain_candidates(self.config.app_domain))

        lines = [
            "version: '2.1'",
            "dir_rule:",
            f"  base_dir: {self._yaml_quote(str(download_dir))}",
            "  rule: Bd_Aid_Pindex",
            "client:",
            "  impl: api",
            "  cache: true",
            "  retry_times: 2",
        ]

        if app_domains:
            lines.append("  domain:")
            lines.append("    api:")
            for domain in app_domains:
                lines.append(f"      - {self._yaml_quote(domain)}")

        lines.extend([
            "  postman:",
            "    meta_data:",
            "      headers:",
            "        User-Agent: Mozilla/5.0",
        ])

        if proxy:
            lines.extend([
                "      proxies:",
                f"        http: {self._yaml_quote(proxy)}",
                f"        https: {self._yaml_quote(proxy)}",
            ])

        if cookies:
            lines.extend([
                "      cookies:",
            ])
            for key, value in cookies.items():
                lines.append(f"        {self._yaml_key(key)}: {self._yaml_quote(value)}")

        username = str(self.config.jm_username or "").strip()
        password = str(self.config.jm_password or "").strip()
        if not username or not password:
            raise JmcomicDownloadError("请先配置 jm_username 和 jm_password")

        lines.extend([
            "download:",
            "  image:",
            "    decode: true",
            "    suffix: null",
            "plugins:",
            "  after_init:",
            "    - plugin: login",
            "      kwargs:",
            f"        username: {self._yaml_quote(username)}",
            f"        password: {self._yaml_quote(password)}",
            "  after_album:",
            "    - plugin: img2pdf",
            "      kwargs:",
            f"        pdf_dir: {self._yaml_quote(str(pdf_dir))}",
            "        filename_rule: Aname",
            "",
        ])
        return "\n".join(lines)

    def find_latest_pdf(self, pdf_dir: Path, started_at: float = 0) -> Path | None:
        if not pdf_dir.exists():
            return None
        candidates = [
            path for path in pdf_dir.rglob("*.pdf")
            if path.is_file() and path.stat().st_mtime >= started_at - 2
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda path: path.stat().st_mtime)

    def cleanup_expired(self, now: float | None = None) -> tuple[int, int]:
        now = time.time() if now is None else now
        max_age = max(1, int(self.config.retention_days)) * 86400
        return (
            self._cleanup_children(self.config.download_root, now, max_age),
            self._cleanup_children(self.pdf_root, now, max_age),
        )

    def cleanup_all(self) -> tuple[int, int]:
        now = time.time()
        return (
            self._cleanup_children(self.config.download_root, now=now, max_age=0),
            self._cleanup_children(self.pdf_root, now=now, max_age=0),
        )

    def remove_task_files(self, task_id: str) -> None:
        task_id = self._safe_task_id(task_id)
        for path in (self.config.download_root / task_id, self.pdf_root / task_id):
            if path.exists():
                shutil.rmtree(path, ignore_errors=True)

    @staticmethod
    def _album_cache_id(album_id: str) -> str:
        return f"album_{validate_album_id(album_id)}"

    def _cleanup_children(self, root: Path, now: float, max_age: int) -> int:
        if not root.exists():
            return 0
        count = 0
        for child in root.iterdir():
            try:
                age = now - child.stat().st_mtime
                if age < max_age:
                    continue
                if child.is_dir():
                    shutil.rmtree(child)
                else:
                    child.unlink()
                count += 1
            except OSError:
                continue
        return count

    def _atomic_write_text(self, path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as file:
                file.write(text)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temp_name, path)
        except Exception:
            try:
                Path(temp_name).unlink(missing_ok=True)
            except OSError:
                pass
            raise

    @staticmethod
    def _safe_task_id(task_id: str) -> str:
        task_id = re.sub(r"[^0-9A-Za-z_-]", "", str(task_id or ""))
        if not task_id:
            raise ValueError("task_id 不能为空")
        return task_id

    @staticmethod
    def _yaml_quote(value: str) -> str:
        escaped = value.replace("\\", "\\\\").replace("'", "''")
        return f"'{escaped}'"

    @staticmethod
    def _yaml_key(value: str) -> str:
        if re.fullmatch(r"[A-Za-z0-9_-]+", value):
            return value
        return JmcomicDownloaderService._yaml_quote(value)
