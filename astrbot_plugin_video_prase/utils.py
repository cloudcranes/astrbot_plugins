import json
import re
import urllib.parse
from dataclasses import dataclass

from .constants import SUPPORTED_DOMAINS, URL_PATTERN


@dataclass
class NormalizedVideoInfo:
    author_uid: str = ""
    author_name: str = "unknown"
    author_avatar: str = ""
    title: str = "No title"
    video_url: str = ""
    music_url: str = ""
    cover_url: str = ""
    images: list[str] | None = None
    live_photos: list[str] | None = None
    source_platform: str = ""

    def __post_init__(self) -> None:
        if self.images is None:
            self.images = []
        if self.live_photos is None:
            self.live_photos = []


@dataclass
class NormalizeResult:
    info: NormalizedVideoInfo | None
    error_message: str = ""
    warning_message: str = ""


_TRAILING_PUNCTUATION = ",.?!;:)]}。，！？；：）】》」』"


def clean_url(url: str) -> str:
    if not url:
        return ""
    cleaned = url.strip().strip("`").strip().strip("\"'")
    while cleaned and cleaned[-1] in _TRAILING_PUNCTUATION:
        cleaned = cleaned[:-1]
    return cleaned


def apply_image_proxy(url: str, proxy_prefix: str, enabled: bool) -> str:
    if not url or not proxy_prefix or not enabled:
        return url
    cleaned_url = clean_url(url)
    if not cleaned_url:
        return url
    return f"{proxy_prefix.rstrip('/')}/{cleaned_url.lstrip('/')}"


def is_supported_url(url: str) -> bool:
    try:
        parsed = urllib.parse.urlparse(url)
        host = (parsed.hostname or "").lower().rstrip(".")
        if not host:
            return False
        return any(host == domain or host.endswith("." + domain) for domain in SUPPORTED_DOMAINS)
    except Exception:
        return False


def extract_first_supported_url(text: str) -> str:
    if not text:
        return ""
    for match in URL_PATTERN.finditer(text):
        url = clean_url(match.group(0))
        if url and is_supported_url(url):
            return url
    return ""


def should_apply_proxy(source_platform: str, source_url: str) -> bool:
    sp = (source_platform or "").strip().lower()
    if sp in {"twitter", "x"}:
        return True

    try:
        host = (urllib.parse.urlparse(source_url).hostname or "").lower()
    except Exception:
        host = ""
    return host.endswith("twitter.com") or host.endswith("x.com") or host == "t.co"


def _find_qqdocurl(data: dict) -> str:
    meta = data.get("meta")
    if not isinstance(meta, dict):
        return ""

    for _, val in meta.items():
        if isinstance(val, dict):
            url = val.get("qqdocurl", "") or val.get("url", "")
            url = clean_url(url)
            if url and is_supported_url(url):
                return url
    return ""


def _try_parse_json(text: str) -> str:
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return _find_qqdocurl(data)
    except (json.JSONDecodeError, TypeError):
        pass
    return ""


def _extract_from_raw_message(raw) -> str:
    if raw is None:
        return ""

    if isinstance(raw, dict):
        url = _find_qqdocurl(raw)
        if url:
            return url
        if raw.get("type") == "json":
            inner = raw.get("data", {})
            if isinstance(inner, dict):
                json_str = inner.get("data", "")
                if isinstance(json_str, str):
                    url = _try_parse_json(json_str)
                    if url:
                        return url

    if isinstance(raw, list):
        for seg in raw:
            if not isinstance(seg, dict):
                continue
            if seg.get("type") == "json":
                inner = seg.get("data", {})
                if isinstance(inner, dict):
                    json_str = inner.get("data", "")
                    if isinstance(json_str, str):
                        url = _try_parse_json(json_str)
                        if url:
                            return url
                elif isinstance(inner, str):
                    url = _try_parse_json(inner)
                    if url:
                        return url

    if isinstance(raw, str):
        raw_str = raw.strip()
        if raw_str.startswith("{"):
            url = _try_parse_json(raw_str)
            if url:
                return url
        cq_match = re.search(r"\[CQ:json,data=(.*?)\]", raw_str, re.S)
        if cq_match:
            cq_data = (
                cq_match.group(1)
                .replace("&amp;", "&")
                .replace("&#44;", ",")
                .replace("&#91;", "[")
                .replace("&#93;", "]")
            )
            url = _try_parse_json(cq_data)
            if url:
                return url

    return ""


def _str_value(value, default: str = "") -> str:
    if value is None:
        return default
    text = str(value).strip()
    return text if text else default


def _parse_media_fields(data: dict) -> tuple[list[str], list[str]]:
    images: list[str] = []
    live_photos: list[str] = []

    raw_images = data.get("images")
    if isinstance(raw_images, list):
        for item in raw_images:
            if isinstance(item, dict):
                image_url = clean_url(_str_value(item.get("url")))
                live_url = clean_url(_str_value(item.get("live_photo_url")))
                if image_url:
                    images.append(image_url)
                if live_url:
                    live_photos.append(live_url)
            elif isinstance(item, str):
                image_url = clean_url(item)
                if image_url:
                    images.append(image_url)

    raw_live_photos = data.get("image_live_photos")
    if isinstance(raw_live_photos, list):
        for item in raw_live_photos:
            if isinstance(item, dict):
                live_url = clean_url(_str_value(item.get("live_photo_url") or item.get("url")))
                if live_url:
                    live_photos.append(live_url)
            elif isinstance(item, str):
                live_url = clean_url(item)
                if live_url:
                    live_photos.append(live_url)

    return images, live_photos


def normalize_response(payload: dict) -> NormalizeResult:
    if not isinstance(payload, dict):
        return NormalizeResult(info=None, error_message="Parse failed: invalid response format")

    if "code" in payload:
        code = payload.get("code")
        if code != 200:
            msg = _str_value(payload.get("msg"), "unknown error")
            return NormalizeResult(info=None, error_message=f"Parse failed: {msg}")
        raw_data = payload.get("data")
    else:
        raw_data = payload

    warning = ""
    if not isinstance(raw_data, dict):
        raw_data = {}
        warning = "Parsed with incomplete data"

    author = raw_data.get("author") if isinstance(raw_data.get("author"), dict) else {}

    images, live_photos = _parse_media_fields(raw_data)

    source_platform = _str_value(
        raw_data.get("source_platform")
        or raw_data.get("source")
        or raw_data.get("platform")
    )

    info = NormalizedVideoInfo(
        author_uid=_str_value(author.get("uid")),
        author_name=_str_value(author.get("name"), "unknown"),
        author_avatar=clean_url(_str_value(author.get("avatar"))),
        title=_str_value(raw_data.get("title"), "No title"),
        video_url=clean_url(_str_value(raw_data.get("video_url"))),
        music_url=clean_url(_str_value(raw_data.get("music_url"))),
        cover_url=clean_url(_str_value(raw_data.get("cover_url"))),
        images=images,
        live_photos=live_photos,
        source_platform=source_platform,
    )

    if not warning and not any(
        [info.video_url, info.images, info.cover_url, info.music_url, info.title != "No title"]
    ):
        warning = "Parsed with incomplete data"

    return NormalizeResult(info=info, warning_message=warning)
