from __future__ import annotations

import importlib.util
import os
import sys
import time
from pathlib import Path

import pytest


PLUGIN_DIR = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("jm_service", PLUGIN_DIR / "service.py")
service = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = service
SPEC.loader.exec_module(service)


def test_validate_album_id() -> None:
    assert service.validate_album_id("12345") == "12345"
    assert service.validate_album_id(" 12345 ") == "12345"
    with pytest.raises(ValueError):
        service.validate_album_id("")
    with pytest.raises(ValueError):
        service.validate_album_id("abc123")


def test_build_option_text_contains_pdf_plugin_and_optional_config(tmp_path: Path) -> None:
    cfg = service.JmcomicDownloadConfig(
        data_dir=tmp_path,
        download_root=tmp_path / "downloads",
        app_domain="https://app.example.test",
        jm_username="user1",
        jm_password="pass1",
        proxy="http://127.0.0.1:7890",
        cookies="AVS=secret; token=abc",
    )
    downloader = service.JmcomicDownloaderService(cfg)
    text = downloader.build_option_text(tmp_path / "downloads" / "t1", tmp_path / "pdf" / "t1")

    assert "plugin: img2pdf" in text
    assert "plugin: login" in text
    assert "impl: api" in text
    assert "filename_rule: Aname" in text
    assert "pdf_dir:" in text
    assert "app.example.test" in text
    assert "username: 'user1'" in text
    assert "password: 'pass1'" in text
    assert "http://127.0.0.1:7890" in text
    assert "AVS: 'secret'" in text
    assert "token: 'abc'" in text


def test_build_option_text_requires_account(tmp_path: Path) -> None:
    cfg = service.JmcomicDownloadConfig(data_dir=tmp_path, download_root=tmp_path / "downloads")
    downloader = service.JmcomicDownloaderService(cfg)

    with pytest.raises(service.JmcomicDownloadError):
        downloader.build_option_text(tmp_path / "downloads" / "t1", tmp_path / "pdf" / "t1")


def test_normalize_domain_candidates(tmp_path: Path) -> None:
    cfg = service.JmcomicDownloadConfig(
        data_dir=tmp_path,
        download_root=tmp_path / "downloads",
        jm_username="user1",
        jm_password="pass1",
    )
    downloader = service.JmcomicDownloaderService(cfg)

    assert downloader._normalize_domain_candidates(["https://a.test/", "http://b.test", ""]) == ["a.test", "b.test"]


def test_find_latest_pdf_selects_newest_after_start_time(tmp_path: Path) -> None:
    cfg = service.JmcomicDownloadConfig(data_dir=tmp_path, download_root=tmp_path / "downloads")
    downloader = service.JmcomicDownloaderService(cfg)
    pdf_dir = tmp_path / "pdfs"
    pdf_dir.mkdir()
    old_pdf = pdf_dir / "old.pdf"
    new_pdf = pdf_dir / "new.pdf"
    old_pdf.write_bytes(b"old")
    new_pdf.write_bytes(b"new")
    old_time = time.time() - 100
    new_time = time.time()
    os.utime(old_pdf, (old_time, old_time))
    os.utime(new_pdf, (new_time, new_time))

    assert downloader.find_latest_pdf(pdf_dir, started_at=new_time - 10) == new_pdf

def test_download_album_uses_cached_pdf_before_jmcomic(tmp_path: Path) -> None:
    cfg = service.JmcomicDownloadConfig(data_dir=tmp_path / "data", download_root=tmp_path / "downloads")
    downloader = service.JmcomicDownloaderService(cfg)
    pdf_dir = downloader.pdf_root / "album_12345"
    pdf_dir.mkdir(parents=True)
    cached_pdf = pdf_dir / "cached.pdf"
    cached_pdf.write_bytes(b"pdf")

    result = downloader.download_album("12345", "task1")

    assert result.pdf_path == cached_pdf
    assert result.download_dir == cfg.download_root / "album_12345"
    assert result.task_id == "task1"


def test_cleanup_expired_removes_old_task_dirs(tmp_path: Path) -> None:
    cfg = service.JmcomicDownloadConfig(data_dir=tmp_path / "data", download_root=tmp_path / "downloads", retention_days=7)
    downloader = service.JmcomicDownloaderService(cfg)
    old_dir = cfg.download_root / "old"
    new_dir = cfg.download_root / "new"
    old_dir.mkdir(parents=True)
    new_dir.mkdir(parents=True)
    old_time = time.time() - 8 * 86400
    os.utime(old_dir, (old_time, old_time))

    download_count, _ = downloader.cleanup_expired(now=time.time())

    assert download_count == 1
    assert not old_dir.exists()
    assert new_dir.exists()

def test_cleanup_all_removes_current_task_dirs(tmp_path: Path) -> None:
    cfg = service.JmcomicDownloadConfig(data_dir=tmp_path / "data", download_root=tmp_path / "downloads", retention_days=7)
    downloader = service.JmcomicDownloaderService(cfg)
    download_dir = cfg.download_root / "album_1"
    pdf_dir = downloader.pdf_root / "album_1"
    download_dir.mkdir(parents=True)
    pdf_dir.mkdir(parents=True)

    download_count, pdf_count = downloader.cleanup_all()

    assert download_count == 1
    assert pdf_count == 1
    assert not download_dir.exists()
    assert not pdf_dir.exists()
