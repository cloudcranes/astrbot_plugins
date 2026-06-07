from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
import json
from pathlib import Path
import re
from typing import Any, Callable
from urllib.error import URLError, HTTPError
from urllib.parse import urljoin
from urllib.request import Request, urlopen


class LoanLedgerError(Exception):
    """借款账本业务异常。"""


class ValidationError(LoanLedgerError):
    """用户输入校验异常。"""


class RateFetchError(LoanLedgerError):
    """官网利率抓取异常。"""


@dataclass
class RateSnapshot:
    annual_rate: Decimal
    effective_date: date
    source_url: str
    source_name: str


@dataclass
class PboCNoticeEntry:
    notice_date: date
    notice_url: str


class LprRateService:
    """LPR 利率服务（官方源：人行优先，拆借中心兜底）。"""

    PBOC_INDEX_URL = "https://www.pbc.gov.cn/zhengcehuobisi/125207/125213/125440/3876551/index.html"
    CHINAMONEY_API_URL = "https://www.chinamoney.com.cn/ags/ms/cm-u-bk-currency/LprHis?lang=CN"

    _ENTRY_PATTERN = re.compile(
        r'href="(?P<href>/zhengcehuobisi/125207/125213/125440/3876551/[^" ]+/index\.html)"[^>]*>.*?</a>\s*</font><span class="hui12">(?P<date>\d{4}-\d{2}-\d{2})</span>',
        re.S,
    )
    _NEXT_PAGE_PATTERN = re.compile(
        r"queryArticleByCondition\(this,'(?P<path>/zhengcehuobisi/125207/125213/125440/3876551/[^']+\.html)'\)",
        re.S,
    )

    def __init__(
        self,
        cache_root: dict[str, Any],
        *,
        pboc_index_url: str | None = None,
        chinamoney_api_url: str | None = None,
        timeout_sec: int = 15,
        enable_chinamoney_fallback: bool = True,
        fetch_text: Callable[[str], str] | None = None,
        fetch_json: Callable[[str, str | None], dict[str, Any]] | None = None,
    ) -> None:
        self._cache_root = cache_root
        self._pboc_index_url = (pboc_index_url or self.PBOC_INDEX_URL).strip()
        self._chinamoney_api_url = (chinamoney_api_url or self.CHINAMONEY_API_URL).strip()
        self._timeout_sec = max(3, min(60, int(timeout_sec)))
        self._enable_chinamoney_fallback = bool(enable_chinamoney_fallback)
        self._fetch_text = fetch_text or self._default_fetch_text
        self._fetch_json = fetch_json or self._default_fetch_json

    def get_effective_1y_rate(self, as_of_date: date) -> RateSnapshot:
        """获取指定日期生效的 1Y LPR（失败直接报错，不使用缓存兜底）。"""
        errors: list[str] = []

        try:
            snapshot = self._get_from_pboc(as_of_date)
            self._remember_snapshot("pboc", snapshot)
            return snapshot
        except Exception as exc:  # noqa: BLE001
            errors.append(f"人行官网抓取失败: {exc}")

        if not self._enable_chinamoney_fallback:
            raise RateFetchError("；".join(errors))

        try:
            snapshot = self._get_from_chinamoney(as_of_date)
            self._remember_snapshot("chinamoney", snapshot)
            return snapshot
        except Exception as exc:  # noqa: BLE001
            errors.append(f"拆借中心官网抓取失败: {exc}")

        raise RateFetchError("；".join(errors))

    def _get_from_pboc(self, as_of_date: date) -> RateSnapshot:
        entries = self._collect_pboc_entries(as_of_date)
        if not entries:
            raise RateFetchError("未在官网目录中找到 LPR 公告")

        target = self._choose_effective_entry(entries, as_of_date)
        if target is None:
            raise RateFetchError(f"官网目录中缺少 {as_of_date.isoformat()} 之前的 LPR 公告")

        article_html = self._fetch_text(target.notice_url)
        rate_1y, _rate_5y = self._extract_lpr_pair(article_html)
        return RateSnapshot(
            annual_rate=rate_1y,
            effective_date=target.notice_date,
            source_url=target.notice_url,
            source_name="中国人民银行",
        )

    def _get_from_chinamoney(self, as_of_date: date) -> RateSnapshot:
        start = date(as_of_date.year - 1, as_of_date.month, min(as_of_date.day, 28))
        query = (
            f"{self._chinamoney_api_url}&strStartDate={start.isoformat()}"
            f"&strEndDate={date.today().isoformat()}"
        )
        payload = self._fetch_json(query, method="POST")
        records = payload.get("records", [])
        if not isinstance(records, list) or not records:
            message = payload.get("data", {}).get("message", "无可用数据")
            raise RateFetchError(f"拆借中心无有效数据: {message}")

        parsed: list[tuple[date, Decimal, str]] = []
        for item in records:
            if not isinstance(item, dict):
                continue
            try:
                d = _parse_iso_date(str(item.get("showDateCN", "")))
                rate = _to_decimal(str(item.get("1Y", "")))
            except Exception:  # noqa: BLE001
                continue
            parsed.append((d, rate, query))

        if not parsed:
            raise RateFetchError("拆借中心返回数据无法解析")

        parsed.sort(key=lambda x: x[0], reverse=True)
        for d, rate, src in parsed:
            if d <= as_of_date:
                return RateSnapshot(
                    annual_rate=rate,
                    effective_date=d,
                    source_url=src,
                    source_name="全国银行间同业拆借中心",
                )

        raise RateFetchError(f"拆借中心缺少 {as_of_date.isoformat()} 之前的 LPR 数据")

    def _collect_pboc_entries(self, as_of_date: date) -> list[PboCNoticeEntry]:
        entries: list[PboCNoticeEntry] = []
        seen: set[str] = set()
        page_url = self._pboc_index_url

        while page_url:
            html = self._fetch_text(page_url)
            page_entries = self._extract_entries_from_list_page(html)
            if not page_entries:
                break

            for item in page_entries:
                if item.notice_url not in seen:
                    entries.append(item)
                    seen.add(item.notice_url)

            page_entries.sort(key=lambda x: x.notice_date, reverse=True)
            newest = page_entries[0].notice_date
            oldest = page_entries[-1].notice_date

            if as_of_date >= newest:
                break
            if oldest <= as_of_date <= newest:
                break

            if as_of_date < oldest:
                page_url = self._extract_next_page_url(html)
                continue

            break

        entries.sort(key=lambda x: x.notice_date, reverse=True)
        return entries

    def _extract_entries_from_list_page(self, html: str) -> list[PboCNoticeEntry]:
        rows: list[PboCNoticeEntry] = []
        for match in self._ENTRY_PATTERN.finditer(html):
            href = match.group("href")
            date_text = match.group("date")
            try:
                d = _parse_iso_date(date_text)
            except Exception:  # noqa: BLE001
                continue
            rows.append(
                PboCNoticeEntry(
                    notice_date=d,
                    notice_url=urljoin("https://www.pbc.gov.cn", href),
                )
            )
        rows.sort(key=lambda x: x.notice_date, reverse=True)
        return rows

    def _extract_next_page_url(self, html: str) -> str | None:
        candidates = [m.group("path") for m in self._NEXT_PAGE_PATTERN.finditer(html)]
        if not candidates:
            return None
        # 列表里通常有“下一页”和“尾页”，优先下一页（页码最小）。
        candidates.sort(key=self._page_sort_key)
        return urljoin("https://www.pbc.gov.cn", candidates[0])

    @staticmethod
    def _page_sort_key(path: str) -> int:
        match = re.search(r"-(\d+)\.html$", path)
        if not match:
            return 10**9
        return int(match.group(1))

    @staticmethod
    def _choose_effective_entry(
        entries: list[PboCNoticeEntry],
        as_of_date: date,
    ) -> PboCNoticeEntry | None:
        for item in entries:
            if item.notice_date <= as_of_date:
                return item
        return None

    @staticmethod
    def _extract_lpr_pair(text: str) -> tuple[Decimal, Decimal]:
        # 常见公告文本: 1年期LPR为3.0%，5年期以上LPR为3.5%。
        pattern = re.compile(
            r"1\s*年\s*期\s*LPR[^0-9]{0,40}([0-9]+(?:\.[0-9]+)?)%[\s\S]{0,160}?"
            r"5\s*年\s*期(?:以\s*上)?\s*LPR[^0-9]{0,40}([0-9]+(?:\.[0-9]+)?)%",
            re.I,
        )
        match = pattern.search(text)
        if not match:
            raise RateFetchError("公告正文未匹配到 1Y/5Y LPR 数值")
        return _to_decimal(match.group(1)), _to_decimal(match.group(2))

    def _remember_snapshot(self, source_key: str, snapshot: RateSnapshot) -> None:
        cache = self._cache_root.setdefault("snapshots", {})
        if not isinstance(cache, dict):
            cache = {}
            self._cache_root["snapshots"] = cache
        cache[source_key] = {
            "annual_rate": str(snapshot.annual_rate),
            "effective_date": snapshot.effective_date.isoformat(),
            "source_url": snapshot.source_url,
            "source_name": snapshot.source_name,
            "fetched_at": datetime.now().isoformat(timespec="seconds"),
        }

    def _default_fetch_text(self, url: str) -> str:
        req = Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; AstrBotLoanLedger/1.0)",
                "Accept": "text/html,application/xhtml+xml",
            },
            method="GET",
        )
        try:
            with urlopen(req, timeout=self._timeout_sec) as resp:
                raw = resp.read()
        except (HTTPError, URLError) as exc:
            raise RateFetchError(str(exc)) from exc

        # 人行/拆借中心页面可能声明 utf-8，也可能由网关返回其他编码，这里做稳健解码。
        for encoding in ("utf-8", "gb18030", "gbk"):
            try:
                return raw.decode(encoding)
            except UnicodeDecodeError:
                continue
        return raw.decode("utf-8", errors="ignore")

    def _default_fetch_json(self, url: str, method: str | None = None) -> dict[str, Any]:
        req = Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; AstrBotLoanLedger/1.0)",
                "Accept": "application/json,text/plain,*/*",
            },
            method=(method or "GET"),
        )
        try:
            with urlopen(req, timeout=self._timeout_sec) as resp:
                raw = resp.read()
        except (HTTPError, URLError) as exc:
            raise RateFetchError(str(exc)) from exc

        text = raw.decode("utf-8", errors="ignore")
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise RateFetchError("JSON 解析失败") from exc
        if not isinstance(parsed, dict):
            raise RateFetchError("JSON 结构异常")
        return parsed


class LoanLedgerService:
    """借款账本服务（会话隔离）。"""

    def __init__(
        self,
        data_file: Path,
        *,
        today_provider: Callable[[], date] | None = None,
        rate_service_factory: Callable[[dict[str, Any]], LprRateService] | None = None,
        lpr_options: dict[str, Any] | None = None,
    ) -> None:
        self._data_file = data_file
        self._today_provider = today_provider or date.today
        self._rate_service_factory = rate_service_factory
        self._lpr_options = dict(lpr_options or {})

    def add_loan(
        self,
        session_id: str,
        borrower: str,
        amount_text: str,
        loan_date_text: str | None = None,
        *,
        interest_enabled: bool = True,
    ) -> dict[str, Any]:
        borrower = self._normalize_borrower(borrower)
        amount = self._parse_amount(amount_text)
        loan_date = self._parse_date(loan_date_text) if loan_date_text else self._today_provider()
        interest_enabled = bool(interest_enabled)

        if interest_enabled:
            store = self._load_store()
            lpr_service = self._build_rate_service(store)
            snapshot = lpr_service.get_effective_1y_rate(loan_date)
            annual_rate = snapshot.annual_rate
            rate_effective_date = snapshot.effective_date
            rate_source_url = snapshot.source_url
            rate_source_name = snapshot.source_name
        else:
            store = self._load_store()
            annual_rate = Decimal("0")
            rate_effective_date = loan_date
            rate_source_url = ""
            rate_source_name = "不计息"

        session = self._ensure_session(store, session_id)
        account = self._ensure_borrower(session, borrower)

        tranche = {
            "tranche_id": _new_id("tranche"),
            "loan_date": loan_date.isoformat(),
            "principal_total": _fmt_money(amount),
            "principal_outstanding": _fmt_money(amount),
            "annual_rate": _fmt_rate(annual_rate),
            "rate_effective_date": rate_effective_date.isoformat(),
            "rate_source_url": rate_source_url,
            "rate_source_name": rate_source_name,
            "interest_enabled": interest_enabled,
            "created_at": _now_text(),
        }
        account["tranches"].append(tranche)
        account["updated_at"] = _now_text()

        self._save_store(store)
        return {
            "borrower": borrower,
            "amount": amount,
            "loan_date": loan_date,
            "annual_rate": annual_rate,
            "rate_effective_date": rate_effective_date,
            "rate_source_url": rate_source_url,
            "interest_enabled": interest_enabled,
        }

    def record_repayment(
        self,
        session_id: str,
        borrower: str,
        amount_text: str,
        repay_date_text: str | None = None,
    ) -> dict[str, Any]:
        borrower = self._normalize_borrower(borrower)
        amount = self._parse_amount(amount_text)
        repay_date = self._parse_date(repay_date_text) if repay_date_text else self._today_provider()

        store = self._load_store()
        session = self._ensure_session(store, session_id)
        account = self._get_borrower(session, borrower)
        if account is None:
            raise ValidationError(f"借款人 {borrower} 不存在")

        tranches = self._sorted_tranches(account)
        total_outstanding = sum(_to_decimal(t["principal_outstanding"]) for t in tranches)
        if amount > total_outstanding:
            raise ValidationError(
                f"还款金额超过未还本金，当前最多可还 {_fmt_money(total_outstanding)} 元"
            )

        allocations: list[dict[str, Any]] = []
        remaining = amount
        total_interest = Decimal("0")

        for tranche in tranches:
            if remaining <= Decimal("0"):
                break
            outstanding = _to_decimal(tranche["principal_outstanding"])
            if outstanding <= Decimal("0"):
                continue

            principal_paid = min(outstanding, remaining)
            tranche_loan_date = _parse_iso_date(tranche["loan_date"])
            if repay_date < tranche_loan_date:
                raise ValidationError("还款日期不能早于借款日期")

            days = (repay_date - tranche_loan_date).days
            interest_enabled = bool(tranche.get("interest_enabled", True))
            annual_rate = _to_decimal(tranche["annual_rate"]) if interest_enabled else Decimal("0")
            interest = _money_round(principal_paid * annual_rate * Decimal(days) / Decimal("36500"))

            tranche["principal_outstanding"] = _fmt_money(outstanding - principal_paid)
            remaining -= principal_paid
            total_interest += interest

            allocations.append(
                {
                    "tranche_id": tranche["tranche_id"],
                    "period_start": tranche_loan_date.isoformat(),
                    "period_end": repay_date.isoformat(),
                    "days": days,
                    "annual_rate": _fmt_rate(annual_rate),
                    "interest_enabled": interest_enabled,
                    "principal_paid": _fmt_money(principal_paid),
                    "interest": _fmt_money(interest),
                }
            )

        repayment = {
            "repayment_id": _new_id("repay"),
            "repay_date": repay_date.isoformat(),
            "amount": _fmt_money(amount),
            "total_interest": _fmt_money(total_interest),
            "allocations": allocations,
            "created_at": _now_text(),
        }
        account["repayments"].append(repayment)
        account["updated_at"] = _now_text()

        self._save_store(store)
        return {
            "borrower": borrower,
            "repay_date": repay_date,
            "amount": amount,
            "total_interest": total_interest,
            "allocations": allocations,
        }

    def show_borrower(
        self,
        session_id: str,
        borrower: str,
        cutoff_date_text: str | None = None,
    ) -> dict[str, Any]:
        borrower = self._normalize_borrower(borrower)
        cutoff = self._parse_date(cutoff_date_text) if cutoff_date_text else self._today_provider()

        store = self._load_store()
        session = self._ensure_session(store, session_id)
        account = self._get_borrower(session, borrower)
        if account is None:
            raise ValidationError(f"借款人 {borrower} 不存在")

        tranches = self._sorted_tranches(account)
        repayments = sorted(account["repayments"], key=lambda r: r["repay_date"])

        outstanding = sum(_to_decimal(t["principal_outstanding"]) for t in tranches)
        total_loaned = sum(_to_decimal(t["principal_total"]) for t in tranches)
        total_repaid = sum(_to_decimal(r["amount"]) for r in repayments)
        total_interest_recorded = sum(_to_decimal(r["total_interest"]) for r in repayments)

        accrual_open = Decimal("0")
        tranche_views: list[dict[str, Any]] = []
        for t in tranches:
            loan_date = _parse_iso_date(t["loan_date"])
            current_outstanding = _to_decimal(t["principal_outstanding"])
            if cutoff < loan_date:
                days = 0
            else:
                days = (cutoff - loan_date).days

            annual_rate = _to_decimal(t["annual_rate"])
            interest_enabled = bool(t.get("interest_enabled", True))
            if not interest_enabled:
                annual_rate = Decimal("0")
            accrued = Decimal("0")
            if current_outstanding > Decimal("0") and days > 0:
                accrued = _money_round(current_outstanding * annual_rate * Decimal(days) / Decimal("36500"))
                accrual_open += accrued

            tranche_views.append(
                {
                    "tranche_id": t["tranche_id"],
                    "loan_date": loan_date,
                    "principal_total": _to_decimal(t["principal_total"]),
                    "principal_outstanding": current_outstanding,
                    "annual_rate": annual_rate,
                    "interest_enabled": interest_enabled,
                    "rate_effective_date": _parse_iso_date(t["rate_effective_date"]),
                    "rate_source_url": t.get("rate_source_url", ""),
                    "accrual_days": days,
                    "accrued_interest": accrued,
                }
            )

        return {
            "borrower": borrower,
            "cutoff": cutoff,
            "summary": {
                "total_loaned": total_loaned,
                "total_repaid": total_repaid,
                "outstanding": outstanding,
                "interest_recorded": total_interest_recorded,
                "interest_open": accrual_open,
                "interest_all": total_interest_recorded + accrual_open,
            },
            "tranches": tranche_views,
            "repayments": repayments,
        }

    def list_borrowers(self, session_id: str, cutoff_date_text: str | None = None) -> dict[str, Any]:
        cutoff = self._parse_date(cutoff_date_text) if cutoff_date_text else self._today_provider()

        store = self._load_store()
        session = self._ensure_session(store, session_id)
        borrowers = session.get("borrowers", {})
        if not isinstance(borrowers, dict):
            borrowers = {}

        rows: list[dict[str, Any]] = []
        for borrower in sorted(borrowers.keys(), key=self._borrower_sort_key):
            detail = self.show_borrower(session_id, borrower, cutoff.isoformat())
            summary = detail["summary"]
            rows.append(
                {
                    "borrower": borrower,
                    "outstanding": summary["outstanding"],
                    "interest_recorded": summary["interest_recorded"],
                    "interest_open": summary["interest_open"],
                    "interest_all": summary["interest_all"],
                    "total_loaned": summary["total_loaned"],
                    "total_repaid": summary["total_repaid"],
                }
            )

        return {"cutoff": cutoff, "rows": rows}

    def _load_store(self) -> dict[str, Any]:
        if not self._data_file.exists():
            return {"sessions": {}, "lpr_cache": {}}
        try:
            raw = self._data_file.read_text(encoding="utf-8")
            parsed = json.loads(raw)
        except Exception as exc:  # noqa: BLE001
            raise LoanLedgerError(f"账本文件读取失败: {exc}") from exc

        if not isinstance(parsed, dict):
            raise LoanLedgerError("账本文件结构错误")
        parsed.setdefault("sessions", {})
        parsed.setdefault("lpr_cache", {})
        return parsed

    def _save_store(self, store: dict[str, Any]) -> None:
        self._data_file.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self._data_file.with_suffix(self._data_file.suffix + ".tmp")
        text = json.dumps(store, ensure_ascii=False, indent=2)
        tmp_path.write_text(text, encoding="utf-8")
        tmp_path.replace(self._data_file)

    def _build_rate_service(self, store: dict[str, Any]) -> LprRateService:
        cache_root = store.setdefault("lpr_cache", {})
        if not isinstance(cache_root, dict):
            cache_root = {}
            store["lpr_cache"] = cache_root

        if self._rate_service_factory is not None:
            return self._rate_service_factory(cache_root)
        return LprRateService(cache_root=cache_root, **self._lpr_options)

    @staticmethod
    def _normalize_borrower(borrower: str) -> str:
        text = (borrower or "").strip()
        if not text:
            raise ValidationError("借款人不能为空")
        return text

    @staticmethod
    def _parse_amount(amount_text: str) -> Decimal:
        text = (amount_text or "").strip()
        if not re.fullmatch(r"\d+(?:\.\d+)?", text):
            raise ValidationError("金额只支持纯数字，例如 200000 或 200000.50")
        amount = _money_round(_to_decimal(text))
        if amount <= Decimal("0"):
            raise ValidationError("金额必须大于 0")
        return amount

    def _parse_date(self, raw: str | None) -> date:
        text = (raw or "").strip()
        if not text:
            raise ValidationError("日期不能为空")

        iso_match = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", text)
        if iso_match:
            return self._build_date(int(iso_match.group(1)), int(iso_match.group(2)), int(iso_match.group(3)))

        cn_md_match = re.fullmatch(r"(\d{1,2})月(\d{1,2})日", text)
        if cn_md_match:
            today_year = self._today_provider().year
            return self._build_date(today_year, int(cn_md_match.group(1)), int(cn_md_match.group(2)))

        raise ValidationError("日期格式错误，仅支持 YYYY-MM-DD 或 M月D日")

    @staticmethod
    def _build_date(y: int, m: int, d: int) -> date:
        try:
            return date(y, m, d)
        except ValueError as exc:
            raise ValidationError(f"非法日期: {y:04d}-{m:02d}-{d:02d}") from exc

    @staticmethod
    def _ensure_session(store: dict[str, Any], session_id: str) -> dict[str, Any]:
        sessions = store.setdefault("sessions", {})
        if not isinstance(sessions, dict):
            sessions = {}
            store["sessions"] = sessions

        sid = (session_id or "").strip() or "default"
        session = sessions.get(sid)
        if not isinstance(session, dict):
            session = {"borrowers": {}}
            sessions[sid] = session
        session.setdefault("borrowers", {})
        return session

    @staticmethod
    def _ensure_borrower(session: dict[str, Any], borrower: str) -> dict[str, Any]:
        borrowers = session.setdefault("borrowers", {})
        if not isinstance(borrowers, dict):
            borrowers = {}
            session["borrowers"] = borrowers

        account = borrowers.get(borrower)
        if not isinstance(account, dict):
            account = {
                "borrower": borrower,
                "tranches": [],
                "repayments": [],
                "created_at": _now_text(),
                "updated_at": _now_text(),
            }
            borrowers[borrower] = account
        account.setdefault("tranches", [])
        account.setdefault("repayments", [])
        return account

    @staticmethod
    def _get_borrower(session: dict[str, Any], borrower: str) -> dict[str, Any] | None:
        borrowers = session.get("borrowers", {})
        if not isinstance(borrowers, dict):
            return None
        account = borrowers.get(borrower)
        return account if isinstance(account, dict) else None

    @staticmethod
    def _sorted_tranches(account: dict[str, Any]) -> list[dict[str, Any]]:
        tranches = account.get("tranches", [])
        if not isinstance(tranches, list):
            return []
        return sorted(tranches, key=lambda t: (t.get("loan_date", ""), t.get("created_at", "")))

    @staticmethod
    def _borrower_sort_key(name: str) -> bytes:
        # 中文场景下优先按 GBK 字节序排序，更接近日常中文排序直觉。
        try:
            return str(name).encode("gbk")
        except Exception:  # noqa: BLE001
            return str(name).encode("utf-8", errors="ignore")


def _parse_iso_date(text: str) -> date:
    return datetime.strptime(text, "%Y-%m-%d").date()


def _money_round(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _fmt_money(value: Decimal) -> str:
    return f"{_money_round(value):.2f}"


def _fmt_rate(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP):.4f}"


def _to_decimal(value: str) -> Decimal:
    return Decimal(str(value).strip())


def _now_text() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _new_id(prefix: str) -> str:
    stamp = datetime.now().strftime("%Y%m%d%H%M%S%f")
    return f"{prefix}_{stamp}"
