import asyncio
import random
import re
from functools import lru_cache

import aiohttp
from astrbot.api import logger
from tenacity import retry, stop_after_attempt, wait_exponential

_MAGNET_EXTRACT_PATTERN = re.compile(
    r"magnet:\?xt=urn:btih:[a-zA-Z0-9]{40}[^\s\"'<>]*", re.IGNORECASE
)
_MAGNET_VALIDATE_PATTERN = re.compile(
    r"^magnet:\?xt=urn:btih:[a-zA-Z0-9]{40}[^\s\"'<>]*$", re.IGNORECASE
)
_REFERER_OPTIONS = [
    "https://whatslink.smartapi.com.cn/",
    "https://whatslink.info/",
    "https://whatslink.info/#/",
    "https://www.google.com/",
    "https://www.bing.com/",
    "https://duckduckgo.com/",
    "https://www.baidu.com/",
    "https://www.sogou.com/",
    "https://www.javbus.com/",
    "https://www.javlibrary.com/",
]
_USER_AGENT_OPTIONS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_6) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
]
_RATE_LIMIT_KEYWORDS = ("too fast", "too many", "rate", "frequency", "频率", "过快", "稍后", "limit")
_REQUIRED_KEYS = {"type", "file_type", "name", "size", "count", "screenshots"}


def _browser_headers(referer: str) -> dict[str, str]:
    return {
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "User-Agent": random.choice(_USER_AGENT_OPTIONS),
        "Referer": referer,
        "Origin": referer.rstrip("/"),
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
    }


async def _warmup_session(session: aiohttp.ClientSession, base_url: str, referer: str) -> None:
    """Visit site root first so aiohttp session keeps cookies like a browser."""
    try:
        async with session.get(
            f"{base_url}/",
            headers={
                **_browser_headers(referer),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
            },
            ssl=False,
            timeout=aiohttp.ClientTimeout(total=15),
        ):
            pass
    except Exception as exc:
        logger.debug("api warmup failed", extra={"category": "warmup", "error": str(exc), "base_url": base_url})


def normalize_magnet(raw: str) -> str:
    """Normalize magnet text from message payload."""
    if not raw:
        return ""
    magnet = raw.strip().strip("<>").strip().strip("\"'")
    return magnet


def extract_magnet_from_text(text: str) -> str | None:
    """Extract first magnet link from arbitrary text."""
    if not text:
        return None
    match = _MAGNET_EXTRACT_PATTERN.search(text)
    if not match:
        return None
    magnet = normalize_magnet(match.group(0))
    return magnet or None


@lru_cache(maxsize=1024)
def validate_magnet(magnet: str) -> bool:
    """Validate magnet format with cache."""
    return bool(_MAGNET_VALIDATE_PATTERN.match(magnet))


def _validate_api_response(data: dict) -> bool:
    """Validate key structure from whatslink API."""
    return isinstance(data, dict) and all(key in data for key in _REQUIRED_KEYS)


def _looks_rate_limited(data: object) -> bool:
    """Detect frequency/rate-limit payloads returned as JSON."""
    text = str(data).lower()
    return any(keyword in text for keyword in _RATE_LIMIT_KEYWORDS)


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
async def analysis(link: str, url: str, session: aiohttp.ClientSession | None = None) -> dict | None:
    """Analyze magnet link with one endpoint."""
    magnet = normalize_magnet(link)
    if not validate_magnet(magnet):
        logger.error("invalid magnet format", extra={"category": "invalid_magnet", "link": magnet})
        return None

    base_url = (url or "").strip().rstrip("/")
    if not base_url:
        logger.error("api url missing", extra={"category": "api_url_missing", "link": magnet})
        return None

    api_url = f"{base_url}/api/v1/link"
    params = {"url": magnet}

    own_session = session is None
    current_session = session if session is not None else aiohttp.ClientSession()
    referers = random.sample(_REFERER_OPTIONS, k=len(_REFERER_OPTIONS))

    try:
        for attempt, referer in enumerate(referers, start=1):
            await _warmup_session(current_session, base_url, referer)
            headers = _browser_headers(referer)
            async with current_session.get(
                api_url,
                headers=headers,
                params=params,
                ssl=False,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as response:
                if response.status != 200:
                    logger.warning(
                        "api non-200 response, rotating referer",
                        extra={
                            "category": "api_status_error",
                            "status": response.status,
                            "api_url": api_url,
                            "referer": referer,
                            "attempt": attempt,
                            "link": magnet,
                        },
                    )
                    await asyncio.sleep(random.uniform(0.6, 1.8))
                    continue

                try:
                    data = await response.json(content_type=None)
                except Exception as exc:
                    logger.warning(
                        "api response parse failed",
                        extra={
                            "category": "response_parse_error",
                            "error": str(exc),
                            "api_url": api_url,
                            "referer": referer,
                            "attempt": attempt,
                            "link": magnet,
                        },
                    )
                    return None

                if isinstance(data, dict) and (data.get("error") or _looks_rate_limited(data)):
                    logger.warning(
                        "api rate-limit/error payload, rotating referer",
                        extra={
                            "category": "api_rate_limited",
                            "api_url": api_url,
                            "referer": referer,
                            "attempt": attempt,
                            "link": magnet,
                        },
                    )
                    await asyncio.sleep(random.uniform(1.5, 3.5))
                    continue

                if _validate_api_response(data):
                    return data

                logger.warning(
                    "api response schema invalid, rotating referer",
                    extra={
                        "category": "schema_error",
                        "api_url": api_url,
                        "referer": referer,
                        "attempt": attempt,
                        "rate_limited": _looks_rate_limited(data),
                        "link": magnet,
                    },
                )
                if not _looks_rate_limited(data):
                    return None
                await asyncio.sleep(random.uniform(1.0, 2.5))
    except asyncio.TimeoutError:
        logger.warning(
            "api timeout",
            extra={"category": "timeout", "api_url": api_url, "link": magnet},
        )
    except aiohttp.ClientError as exc:
        logger.warning(
            "api network error",
            extra={
                "category": "network_error",
                "error": str(exc),
                "api_url": api_url,
                "link": magnet,
            },
        )
    except Exception as exc:
        logger.exception(
            "api unknown error",
            extra={
                "category": "unknown_error",
                "error": str(exc),
                "api_url": api_url,
                "link": magnet,
            },
        )
    finally:
        if own_session:
            await current_session.close()

    return None


async def analysis_with_fallback(
    link: str,
    session: aiohttp.ClientSession | None = None,
    config_url: str | None = None,
    fallback_url: str = "https://whatslink.info",
) -> dict | None:
    """Analyze magnet with config URL first, then fallback URL."""
    magnet = normalize_magnet(link)
    if not validate_magnet(magnet):
        logger.error("invalid magnet format", extra={"category": "invalid_magnet", "link": magnet})
        return None

    urls: list[str] = []
    if config_url:
        urls.append(config_url.strip().rstrip("/"))
    if fallback_url:
        fallback = fallback_url.strip().rstrip("/")
        if fallback and fallback not in urls:
            urls.append(fallback)

    if not urls:
        logger.error("no api url available", extra={"category": "api_url_missing", "link": magnet})
        return None

    for index, url in enumerate(urls):
        result = await analysis(magnet, url, session=session)
        if result is not None:
            return result
        if index < len(urls) - 1:
            logger.warning(
                "analysis fallback triggered",
                extra={
                    "category": "fallback",
                    "failed_url": url,
                    "next_url": urls[index + 1],
                    "link": magnet,
                },
            )

    return None
