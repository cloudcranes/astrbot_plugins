from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path


PLUGIN_DIR = Path(__file__).resolve().parents[1]
PACKAGE_NAME = "astrbot_plugin_jmcomic_downloader"


class _Logger:
    def info(self, *args, **kwargs):
        pass

    def warning(self, *args, **kwargs):
        pass

    def error(self, *args, **kwargs):
        pass


class _CommandGroup:
    def __call__(self, fn):
        return self

    def command(self, *args, **kwargs):
        def decorator(fn):
            return fn
        return decorator


class _Filter:
    def command_group(self, *args, **kwargs):
        return _CommandGroup()

    def regex(self, *args, **kwargs):
        def decorator(fn):
            return fn
        return decorator


class _Star:
    def __init__(self, context):
        self.context = context


class _StarTools:
    data_dir: Path | None = None

    @classmethod
    def get_data_dir(cls, name: str) -> Path:
        assert cls.data_dir is not None
        return cls.data_dir / name


class _Event:
    def __init__(self, sender_id: str, is_admin: bool = False):
        self.sender_id = sender_id
        self._is_admin = is_admin

    def is_admin(self) -> bool:
        return self._is_admin

    def get_sender_id(self) -> str:
        return self.sender_id

    def get_session_id(self) -> str:
        return "session"

    def get_message_outline(self) -> str:
        return self.sender_id


def _install_astrbot_stubs(tmp_path: Path) -> None:
    _StarTools.data_dir = tmp_path

    api = types.ModuleType("astrbot.api")
    api.AstrBotConfig = dict
    api.logger = _Logger()

    event = types.ModuleType("astrbot.api.event")
    event.AstrMessageEvent = object
    event.filter = _Filter()

    star = types.ModuleType("astrbot.api.star")
    star.Context = object
    star.Star = _Star
    star.StarTools = _StarTools
    star.register = lambda *args, **kwargs: (lambda cls: cls)

    sys.modules["astrbot"] = types.ModuleType("astrbot")
    sys.modules["astrbot.api"] = api
    sys.modules["astrbot.api.event"] = event
    sys.modules["astrbot.api.star"] = star


def _load_main(tmp_path: Path):
    _install_astrbot_stubs(tmp_path)
    package = types.ModuleType(PACKAGE_NAME)
    package.__path__ = [str(PLUGIN_DIR)]
    sys.modules[PACKAGE_NAME] = package
    spec = importlib.util.spec_from_file_location(f"{PACKAGE_NAME}.main", PLUGIN_DIR / "main.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_admin_authorized_even_with_empty_whitelist(tmp_path: Path) -> None:
    module = _load_main(tmp_path)
    plugin = module.JmcomicDownloaderPlugin(object(), {"whitelist": []})

    assert plugin._is_authorized(_Event("10001", is_admin=True)) is True
    assert plugin._is_authorized(_Event("10001", is_admin=False)) is False


def test_whitelist_authorizes_download(tmp_path: Path) -> None:
    module = _load_main(tmp_path)
    plugin = module.JmcomicDownloaderPlugin(object(), {"whitelist": ["10001"]})
    admin_event = _Event("10001")

    assert plugin._is_authorized(admin_event) is True
    assert plugin._is_authorized(_Event("20002")) is False


def test_prefixed_album_id_can_be_parsed_from_event_text(tmp_path: Path) -> None:
    module = _load_main(tmp_path)
    plugin = module.JmcomicDownloaderPlugin(object(), {"whitelist": ["10001"]})

    assert plugin._parse_jm_text(plugin._event_text(_Event("jm123456"))) == "123456"
    assert plugin._parse_jm_text("123456") == ""
