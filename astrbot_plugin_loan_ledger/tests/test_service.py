from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
import sys

import pytest

PLUGIN_DIR = Path(__file__).resolve().parents[1]
if str(PLUGIN_DIR) not in sys.path:
    sys.path.insert(0, str(PLUGIN_DIR))

from service import (  # noqa: E402
    LoanLedgerService,
    RateFetchError,
    RateSnapshot,
    ValidationError,
    LprRateService,
)


class FixedRateService:
    def __init__(self, annual_rate: str = "12.0000") -> None:
        self._rate = Decimal(annual_rate)

    def get_effective_1y_rate(self, as_of_date: date) -> RateSnapshot:
        return RateSnapshot(
            annual_rate=self._rate,
            effective_date=as_of_date,
            source_url="https://example.com/lpr",
            source_name="测试源",
        )


class FailingRateService:
    def get_effective_1y_rate(self, as_of_date: date) -> RateSnapshot:
        raise RuntimeError(f"should not fetch rate at {as_of_date}")


def build_service(tmp_path: Path, today: date = date(2026, 2, 1)) -> LoanLedgerService:
    data_file = tmp_path / "ledger.json"
    return LoanLedgerService(
        data_file=data_file,
        today_provider=lambda: today,
        rate_service_factory=lambda _cache: FixedRateService(),
    )


def test_add_and_repay_interest_month_case(tmp_path: Path):
    svc = build_service(tmp_path)
    sid = "group_1"

    add_res = svc.add_loan(sid, "张三", "200000", "2026-01-01")
    assert add_res["annual_rate"] == Decimal("12.0000")

    repay_res = svc.record_repayment(sid, "张三", "20000", "2026-02-01")
    assert repay_res["total_interest"] == Decimal("203.84")
    assert repay_res["allocations"][0]["days"] == 31

    detail = svc.show_borrower(sid, "张三", "2026-02-01")
    assert detail["summary"]["outstanding"] == Decimal("180000.00")
    assert detail["summary"]["interest_recorded"] == Decimal("203.84")


def test_fifo_across_multi_tranches(tmp_path: Path):
    svc = build_service(tmp_path, today=date(2026, 3, 1))
    sid = "group_2"

    svc.add_loan(sid, "李四", "100000", "2026-01-01")
    svc.add_loan(sid, "李四", "50000", "2026-01-15")

    repay = svc.record_repayment(sid, "李四", "120000", "2026-03-01")
    assert len(repay["allocations"]) == 2
    assert repay["allocations"][0]["principal_paid"] == "100000.00"
    assert repay["allocations"][1]["principal_paid"] == "20000.00"

    detail = svc.show_borrower(sid, "李四", "2026-03-01")
    assert detail["summary"]["outstanding"] == Decimal("30000.00")


def test_overpay_rejected(tmp_path: Path):
    svc = build_service(tmp_path)
    sid = "group_3"

    svc.add_loan(sid, "王五", "1000", "2026-01-01")
    with pytest.raises(ValidationError):
        svc.record_repayment(sid, "王五", "1000.01", "2026-01-02")


def test_chinese_date_supported(tmp_path: Path):
    svc = build_service(tmp_path, today=date(2026, 8, 15))
    sid = "group_4"

    res = svc.add_loan(sid, "赵六", "5000", "1月1日")
    assert res["loan_date"].isoformat() == "2026-01-01"


def test_list_sorted_by_borrower_name(tmp_path: Path):
    svc = build_service(tmp_path)
    sid = "group_5"

    svc.add_loan(sid, "张三", "1000", "2026-01-01")
    svc.add_loan(sid, "李四", "1000", "2026-01-01")

    rows = svc.list_borrowers(sid, "2026-01-02")["rows"]
    assert [r["borrower"] for r in rows] == ["李四", "张三"]


def test_add_loan_date_optional_defaults_today(tmp_path: Path):
    svc = build_service(tmp_path, today=date(2026, 5, 17))
    sid = "group_6"

    res = svc.add_loan(sid, "钱七", "3000")
    assert res["loan_date"].isoformat() == "2026-05-17"


def test_add_loan_nointerest_skip_rate_fetch(tmp_path: Path):
    data_file = tmp_path / "ledger.json"
    svc = LoanLedgerService(
        data_file=data_file,
        today_provider=lambda: date(2026, 2, 1),
        rate_service_factory=lambda _cache: FailingRateService(),
    )

    res = svc.add_loan("group_7", "孙八", "5000", interest_enabled=False)
    assert res["annual_rate"] == Decimal("0")
    assert res["interest_enabled"] is False


def test_nointerest_repayment_interest_is_zero(tmp_path: Path):
    svc = build_service(tmp_path, today=date(2026, 2, 1))
    sid = "group_8"

    svc.add_loan(sid, "周九", "10000", "2026-01-01", interest_enabled=False)
    repay_res = svc.record_repayment(sid, "周九", "1000", "2026-02-01")
    assert repay_res["total_interest"] == Decimal("0.00")
    assert repay_res["allocations"][0]["interest"] == "0.00"


def test_lpr_service_pboc_first_success():
    list_html = '''
    <a href="/zhengcehuobisi/125207/125213/125440/3876551/abc/index.html">x</a></font><span class="hui12">2026-04-20</span>
    '''
    article_html = "1年期LPR为3.0%，5年期以上LPR为3.5%。"

    def fake_fetch_text(url: str) -> str:
        if url.endswith("index.html") and "3876551/index.html" in url:
            return list_html
        return article_html

    service = LprRateService(cache_root={}, fetch_text=fake_fetch_text)
    snapshot = service.get_effective_1y_rate(date(2026, 4, 21))

    assert snapshot.annual_rate == Decimal("3.0")
    assert snapshot.effective_date.isoformat() == "2026-04-20"
    assert snapshot.source_name == "中国人民银行"


def test_lpr_service_fallback_to_chinamoney():
    def fail_fetch_text(_url: str) -> str:
        raise RateFetchError("pbc down")

    def fake_fetch_json(_url: str, method: str | None = None):
        assert method == "POST"
        return {
            "data": {"message": ""},
            "records": [
                {"showDateCN": "2026-04-20", "1Y": "3.00", "5Y": "3.50"},
                {"showDateCN": "2026-03-20", "1Y": "3.00", "5Y": "3.50"},
            ],
        }

    service = LprRateService(cache_root={}, fetch_text=fail_fetch_text, fetch_json=fake_fetch_json)
    snapshot = service.get_effective_1y_rate(date(2026, 4, 21))
    assert snapshot.source_name == "全国银行间同业拆借中心"
    assert snapshot.annual_rate == Decimal("3.00")


def test_lpr_service_both_fail():
    def fail_fetch_text(_url: str) -> str:
        raise RateFetchError("pbc down")

    def fail_fetch_json(_url: str, method: str | None = None):
        raise RateFetchError("cm down")

    service = LprRateService(cache_root={}, fetch_text=fail_fetch_text, fetch_json=fail_fetch_json)
    with pytest.raises(RateFetchError):
        service.get_effective_1y_rate(date(2026, 4, 21))
