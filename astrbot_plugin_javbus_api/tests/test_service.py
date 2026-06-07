from __future__ import annotations

from pathlib import Path
import sys
import urllib.error

import pytest

PLUGIN_DIR = Path(__file__).resolve().parents[1]
if str(PLUGIN_DIR) not in sys.path:
    sys.path.insert(0, str(PLUGIN_DIR))

from service import (  # noqa: E402
    JavBusAuthError,
    JavBusClient,
    JavBusNotFoundError,
    JavBusRequestError,
    JavBusResponseError,
    JavBusTimeoutError,
    MissingMagnetParamsError,
    normalize_movie_id,
    try_normalize_movie_id,
)


def test_normalize_movie_id():
    assert normalize_movie_id("ssis960") == "SSIS-960"
    assert normalize_movie_id("SSIS-960") == "SSIS-960"
    assert try_normalize_movie_id("IPX585") == "IPX-585"
    assert try_normalize_movie_id("bad-id") is None


def test_list_movies_url_and_params():
    captured = {}

    def fake_fetch(url: str, headers: dict[str, str], timeout: int):
        captured["url"] = url
        captured["headers"] = headers
        captured["timeout"] = timeout
        return {"movies": [], "pagination": {"currentPage": 2}}

    client = JavBusClient(
        base_url="https://example.com",
        timeout_sec=15,
        fetch_json=fake_fetch,
    )
    data = client.list_movies(
        page=2,
        magnet="all",
        filter_type="star",
        filter_value="qs6",
    )
    assert isinstance(data, dict)
    assert captured["timeout"] == 15
    assert captured["url"].startswith("https://example.com/api/movies?")
    assert "page=2" in captured["url"]
    assert "magnet=all" in captured["url"]
    assert "filterType=star" in captured["url"]
    assert "filterValue=qs6" in captured["url"]
    assert "type=normal" in captured["url"]


def test_auth_header_injection():
    captured = {}

    def fake_fetch(url: str, headers: dict[str, str], timeout: int):
        captured["headers"] = headers
        return {"movies": [], "pagination": {"currentPage": 1}}

    client = JavBusClient(
        base_url="https://example.com",
        auth_token="token-123",
        fetch_json=fake_fetch,
    )
    client.list_movies()
    assert captured["headers"]["j-auth-token"] == "token-123"


def test_magnets_auto_success():
    seen = []

    def fake_fetch(url: str, headers: dict[str, str], timeout: int):
        seen.append(url)
        if "/api/movies/" in url:
            return {"id": "SSIS-960", "gid": "123456", "uc": "0"}
        return [{"title": "M1", "link": "magnet:?xt=urn:btih:abc"}]

    client = JavBusClient(base_url="https://example.com", fetch_json=fake_fetch)
    detail, magnets, ctx = client.magnets_by_movie_auto(movie_id="SSIS960")
    assert detail["gid"] == "123456"
    assert isinstance(magnets, list) and len(magnets) == 1
    assert ctx.movie_id == "SSIS-960"
    assert any("/api/magnets/SSIS-960" in item for item in seen)


def test_magnets_auto_missing_gid_uc():
    def fake_fetch(url: str, headers: dict[str, str], timeout: int):
        return {"id": "SSIS-960", "gid": "", "uc": ""}

    client = JavBusClient(base_url="https://example.com", fetch_json=fake_fetch)
    with pytest.raises(MissingMagnetParamsError):
        client.magnets_by_movie_auto(movie_id="SSIS-960")


def test_error_mapping_auth_401():
    def fake_fetch(url: str, headers: dict[str, str], timeout: int):
        raise urllib.error.HTTPError(url=url, code=401, msg="Unauthorized", hdrs=None, fp=None)

    client = JavBusClient(base_url="https://example.com", fetch_json=fake_fetch)
    with pytest.raises(JavBusAuthError):
        client.list_movies()


def test_error_mapping_not_found_404():
    def fake_fetch(url: str, headers: dict[str, str], timeout: int):
        raise urllib.error.HTTPError(url=url, code=404, msg="Not Found", hdrs=None, fp=None)

    client = JavBusClient(base_url="https://example.com", fetch_json=fake_fetch)
    with pytest.raises(JavBusNotFoundError):
        client.movie_detail("SSIS-960")


def test_error_mapping_timeout():
    def fake_fetch(url: str, headers: dict[str, str], timeout: int):
        raise urllib.error.URLError("timed out")

    client = JavBusClient(base_url="https://example.com", fetch_json=fake_fetch)
    with pytest.raises(JavBusTimeoutError):
        client.search_movies(keyword="SSIS")


def test_response_error_shape():
    def fake_fetch(url: str, headers: dict[str, str], timeout: int):
        return []

    client = JavBusClient(base_url="https://example.com", fetch_json=fake_fetch)
    with pytest.raises(JavBusResponseError):
        client.list_movies()


def test_request_error_generic():
    def fake_fetch(url: str, headers: dict[str, str], timeout: int):
        raise RuntimeError("boom")

    client = JavBusClient(base_url="https://example.com", fetch_json=fake_fetch)
    with pytest.raises(JavBusRequestError):
        client.list_movies()
