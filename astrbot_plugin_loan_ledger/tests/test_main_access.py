from __future__ import annotations

from pathlib import Path
import sys
import types


def _install_astrbot_stubs() -> None:
    if "astrbot.api" in sys.modules:
        return

    astrbot = types.ModuleType("astrbot")
    api = types.ModuleType("astrbot.api")
    event = types.ModuleType("astrbot.api.event")
    star = types.ModuleType("astrbot.api.star")

    class DummyGroup:
        def __call__(self, func):
            return self

        def command(self, _name: str):
            def deco(func):
                return func

            return deco

    class DummyFilter:
        @staticmethod
        def command_group(_name: str):
            return DummyGroup()

    class DummyStar:
        def __init__(self, _context=None, _config=None) -> None:
            pass

    class DummyStarTools:
        @staticmethod
        def get_data_dir(_name: str) -> str:
            return "."

    api.AstrBotConfig = dict
    event.AstrMessageEvent = object
    event.filter = DummyFilter()
    star.Context = object
    star.Star = DummyStar
    star.StarTools = DummyStarTools

    sys.modules["astrbot"] = astrbot
    sys.modules["astrbot.api"] = api
    sys.modules["astrbot.api.event"] = event
    sys.modules["astrbot.api.star"] = star


_install_astrbot_stubs()

PLUGIN_PARENT = Path(__file__).resolve().parents[2]
if str(PLUGIN_PARENT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_PARENT))

from astrbot_plugin_loan_ledger.main import Main  # noqa: E402


class FakeEvent:
    def __init__(self, sender_id: str, is_admin: bool = False) -> None:
        self._sender_id = sender_id
        self._is_admin = is_admin

    def is_admin(self) -> bool:
        return self._is_admin

    def get_sender_id(self) -> str:
        return self._sender_id


def _build_main(config: dict) -> Main:
    obj = Main.__new__(Main)
    obj.config = config
    return obj


def test_parse_user_whitelist_mixed_separators_and_dedup():
    parsed = Main._parse_user_whitelist("10001, 10002\n10003\r\n10002，10004,,")
    assert parsed == {"10001", "10002", "10003", "10004"}


def test_authorized_for_admin_even_if_whitelist_disabled():
    main = _build_main({"enable_user_whitelist": False, "user_whitelist": ""})
    assert main._is_authorized(FakeEvent(sender_id="20001", is_admin=True)) is True


def test_authorized_for_whitelisted_non_admin():
    main = _build_main({"enable_user_whitelist": True, "user_whitelist": "20001,20002"})
    assert main._is_authorized(FakeEvent(sender_id="20002", is_admin=False)) is True


def test_denied_when_non_admin_not_in_whitelist():
    main = _build_main({"enable_user_whitelist": True, "user_whitelist": "20001,20002"})
    assert main._is_authorized(FakeEvent(sender_id="20003", is_admin=False)) is False


def test_denied_when_whitelist_disabled_for_non_admin():
    main = _build_main({"enable_user_whitelist": False, "user_whitelist": "20003"})
    assert main._is_authorized(FakeEvent(sender_id="20003", is_admin=False)) is False
