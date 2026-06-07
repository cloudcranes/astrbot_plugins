from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any, Callable
import urllib.error
import urllib.parse
import urllib.request


JsonFetcher = Callable[[str, dict[str, str], int], Any]


class JavBusError(Exception):
    """JavBus 插件异常基类。"""


class JavBusAuthError(JavBusError):
    """鉴权失败。"""


class JavBusNotFoundError(JavBusError):
    """资源不存在。"""


class JavBusTimeoutError(JavBusError):
    """请求超时。"""


class JavBusResponseError(JavBusError):
    """响应结构异常。"""


class JavBusRequestError(JavBusError):
    """请求失败。"""


class MissingMagnetParamsError(JavBusError):
    """详情中缺少 gid/uc，无法查询磁力。"""


_MOVIE_ID_RE = re.compile(r"(?i)^([a-z]{2,10})-?(\d{2,6})$")


@dataclass(frozen=True)
class MagnetQueryContext:
    movie_id: str
    gid: str
    uc: str


def normalize_movie_id(raw: str) -> str:
    """
    将番号标准化为 `ABC-123` 形式。
    支持输入：
    - `SSIS-960`
    - `SSIS960`
    """
    text = (raw or "").strip().upper()
    matched = _MOVIE_ID_RE.fullmatch(text)
    if not matched:
        raise ValueError(f"无效番号: {raw}")
    return f"{matched.group(1)}-{matched.group(2)}"


def try_normalize_movie_id(raw: str) -> str | None:
    try:
        return normalize_movie_id(raw)
    except Exception:
        return None


class JavBusClient:
    def __init__(
        self,
        *,
        base_url: str,
        auth_token: str = "",
        timeout_sec: int = 20,
        fetch_json: JsonFetcher | None = None,
    ) -> None:
        self.base_url = (base_url or "").strip().rstrip("/")
        if not self.base_url:
            raise ValueError("base_url 不能为空")
        self.auth_token = (auth_token or "").strip()
        self.timeout_sec = max(1, int(timeout_sec))
        self._fetch_json = fetch_json or _default_fetch_json

    def list_movies(
        self,
        *,
        page: int = 1,
        magnet: str = "exist",
        filter_type: str | None = None,
        filter_value: str | None = None,
        movie_type: str = "normal",
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "page": max(1, page),
            "magnet": magnet or "exist",
            "type": movie_type or "normal",
        }
        if filter_type and filter_value:
            params["filterType"] = filter_type
            params["filterValue"] = filter_value
        data = self._request_json("/api/movies", params=params)
        return _ensure_object(data, "影片列表")

    def search_movies(
        self,
        *,
        keyword: str,
        page: int = 1,
        magnet: str = "exist",
        movie_type: str = "normal",
    ) -> dict[str, Any]:
        kw = (keyword or "").strip()
        if not kw:
            raise ValueError("keyword 不能为空")

        params: dict[str, Any] = {
            "keyword": kw,
            "page": max(1, page),
            "magnet": magnet or "exist",
            "type": movie_type or "normal",
        }
        data = self._request_json("/api/movies/search", params=params)
        return _ensure_object(data, "搜索结果")

    def movie_detail(self, movie_id: str) -> dict[str, Any]:
        normalized = normalize_movie_id(movie_id)
        data = self._request_json(f"/api/movies/{urllib.parse.quote(normalized)}")
        return _ensure_object(data, "影片详情")

    def star_detail(self, star_id: str, *, movie_type: str = "normal") -> dict[str, Any]:
        sid = (star_id or "").strip()
        if not sid:
            raise ValueError("star_id 不能为空")
        data = self._request_json(
            f"/api/stars/{urllib.parse.quote(sid)}",
            params={"type": movie_type or "normal"},
        )
        return _ensure_object(data, "演员详情")

    def magnets(
        self,
        *,
        movie_id: str,
        gid: str,
        uc: str,
        sort_by: str | None = None,
        sort_order: str | None = None,
    ) -> list[dict[str, Any]]:
        normalized = normalize_movie_id(movie_id)
        params: dict[str, Any] = {"gid": gid, "uc": uc}
        if sort_by and sort_order:
            params["sortBy"] = sort_by
            params["sortOrder"] = sort_order

        data = self._request_json(
            f"/api/magnets/{urllib.parse.quote(normalized)}",
            params=params,
        )
        return _ensure_array_of_object(data, "磁力列表")

    def magnets_by_movie_auto(
        self,
        *,
        movie_id: str,
        sort_by: str | None = None,
        sort_order: str | None = None,
    ) -> tuple[dict[str, Any], list[dict[str, Any]], MagnetQueryContext]:
        detail = self.movie_detail(movie_id)
        gid = str(detail.get("gid", "") or "").strip()
        uc = str(detail.get("uc", "") or "").strip()
        if not gid or not uc:
            raise MissingMagnetParamsError("影片详情缺少 gid 或 uc，无法查询磁力链接。")

        normalized = normalize_movie_id(movie_id)
        magnets = self.magnets(
            movie_id=normalized,
            gid=gid,
            uc=uc,
            sort_by=sort_by,
            sort_order=sort_order,
        )
        return detail, magnets, MagnetQueryContext(movie_id=normalized, gid=gid, uc=uc)

    def _request_json(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> Any:
        url = _build_url(self.base_url, path, params=params)
        headers = {"Accept": "application/json"}
        if self.auth_token:
            headers["j-auth-token"] = self.auth_token

        try:
            return self._fetch_json(url, headers, self.timeout_sec)
        except JavBusError:
            raise
        except urllib.error.HTTPError as exc:
            code = int(getattr(exc, "code", 0) or 0)
            if code in {401, 403}:
                raise JavBusAuthError("鉴权失败，请检查 auth_token 配置。") from exc
            if code == 404:
                raise JavBusNotFoundError("资源不存在。") from exc
            raise JavBusRequestError(f"接口请求失败（HTTP {code}）。") from exc
        except urllib.error.URLError as exc:
            message = str(getattr(exc, "reason", "") or exc)
            if "timed out" in message.lower():
                raise JavBusTimeoutError("接口请求超时，请稍后重试。") from exc
            raise JavBusRequestError(f"网络请求失败：{message}") from exc
        except TimeoutError as exc:
            raise JavBusTimeoutError("接口请求超时，请稍后重试。") from exc
        except json.JSONDecodeError as exc:
            raise JavBusResponseError("接口响应不是有效 JSON。") from exc
        except Exception as exc:
            raise JavBusRequestError(f"请求失败：{exc}") from exc


def _default_fetch_json(url: str, headers: dict[str, str], timeout_sec: int) -> Any:
    req = urllib.request.Request(url=url, headers=headers, method="GET")
    with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
        body = resp.read().decode("utf-8", errors="replace")
    return json.loads(body)


def _build_url(base_url: str, path: str, *, params: dict[str, Any] | None = None) -> str:
    if not path.startswith("/"):
        path = f"/{path}"
    url = f"{base_url}{path}"
    if not params:
        return url

    clean_params: dict[str, Any] = {}
    for key, value in params.items():
        if value is None:
            continue
        text = str(value).strip()
        if text == "":
            continue
        clean_params[key] = value

    if not clean_params:
        return url
    return f"{url}?{urllib.parse.urlencode(clean_params)}"


def _ensure_object(value: Any, scene: str) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    raise JavBusResponseError(f"{scene}响应格式异常：期望对象。")


def _ensure_array_of_object(value: Any, scene: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise JavBusResponseError(f"{scene}响应格式异常：期望数组。")
    result: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            raise JavBusResponseError(f"{scene}响应格式异常：数组元素不是对象。")
        result.append(item)
    return result
