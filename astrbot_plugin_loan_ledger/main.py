from __future__ import annotations

from decimal import Decimal
from pathlib import Path
import re
from typing import Any

from astrbot.api import AstrBotConfig
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, StarTools

from .service import LoanLedgerService, LoanLedgerError


class Main(Star):
    _INTEREST_TRUE_TOKENS = {"interest", "yes", "true", "计息", "是"}
    _INTEREST_FALSE_TOKENS = {"nointerest", "no", "false", "不计息", "否"}
    _NO_PERMISSION_MESSAGE = "无权限：你不在白名单且非管理员"

    def __init__(self, context: Context, config: AstrBotConfig | None = None) -> None:
        super().__init__(context, config)
        self.config = config or {}

        data_dir = StarTools.get_data_dir("astrbot_plugin_loan_ledger")
        data_file = Path(data_dir) / "ledger.json"
        lpr_options = {
            "pboc_index_url": self._get_str_config(
                "pboc_index_url",
                "https://www.pbc.gov.cn/zhengcehuobisi/125207/125213/125440/3876551/index.html",
            ),
            "chinamoney_api_url": self._get_str_config(
                "chinamoney_api_url",
                "https://www.chinamoney.com.cn/ags/ms/cm-u-bk-currency/LprHis?lang=CN",
            ),
            "timeout_sec": self._get_int_config("http_timeout_sec", 15, min_value=3, max_value=60),
            "enable_chinamoney_fallback": self._get_bool_config("enable_chinamoney_fallback", True),
        }
        self._service = LoanLedgerService(data_file=data_file, lpr_options=lpr_options)

    @filter.command_group("loan")
    def loan(self) -> None:
        """借款记录命令组。"""

    @loan.command("help")
    async def loan_help(self, event: AstrMessageEvent):
        if not self._is_authorized(event):
            yield event.plain_result(self._NO_PERMISSION_MESSAGE)
            return
        yield event.plain_result(self._help_text())

    @loan.command("add")
    async def loan_add(
        self,
        event: AstrMessageEvent,
        borrower: str = "",
        amount: str = "",
        arg3: str = "",
        arg4: str = "",
    ):
        """新增借款：/loan add <借款人> <金额> [借款日期] [计息开关]"""
        if not self._is_authorized(event):
            yield event.plain_result(self._NO_PERMISSION_MESSAGE)
            return

        try:
            loan_date_text, interest_enabled = self._parse_add_optional_args(arg3, arg4)
            result = self._service.add_loan(
                session_id=self._session_id(event),
                borrower=borrower,
                amount_text=amount,
                loan_date_text=loan_date_text,
                interest_enabled=interest_enabled,
            )
        except LoanLedgerError as exc:
            yield event.plain_result(f"新增借款失败：{exc}")
            return

        text = (
            "借款录入成功\n"
            f"借款人：{result['borrower']}\n"
            f"借款金额：{self._fmt_money(result['amount'])} 元\n"
            f"借款日期：{result['loan_date'].isoformat()}\n"
            f"计息：{'是' if result.get('interest_enabled', True) else '否'}\n"
            f"年化利率（1Y LPR）：{self._fmt_rate(result['annual_rate'])}%\n"
            f"利率生效日：{result['rate_effective_date'].isoformat()}\n"
            f"来源：{result['rate_source_url'] or '不计息'}"
        )
        yield event.plain_result(text)

    @loan.command("repay")
    async def loan_repay(self, event: AstrMessageEvent, borrower: str = "", amount: str = "", repay_date: str = ""):
        """记录还款：/loan repay <借款人> <金额> [还款日期]"""
        if not self._is_authorized(event):
            yield event.plain_result(self._NO_PERMISSION_MESSAGE)
            return

        try:
            result = self._service.record_repayment(
                session_id=self._session_id(event),
                borrower=borrower,
                amount_text=amount,
                repay_date_text=(repay_date or None),
            )
        except LoanLedgerError as exc:
            yield event.plain_result(f"记录还款失败：{exc}")
            return

        lines = [
            "还款录入成功",
            f"借款人：{result['borrower']}",
            f"还款金额：{self._fmt_money(result['amount'])} 元",
            f"还款日期：{result['repay_date'].isoformat()}",
            f"本次利息：{self._fmt_money(result['total_interest'])} 元",
            "分配明细（FIFO，含起不含止）：",
        ]

        allocations = result.get("allocations", [])
        if not allocations:
            lines.append("- 无分配记录")
        else:
            for idx, item in enumerate(allocations, start=1):
                lines.append(
                    f"{idx}. tranche={item['tranche_id']} | 冲本金={item['principal_paid']} 元"
                    f" | 计息={'是' if item.get('interest_enabled', True) else '否'}"
                    f" | 年化={self._fmt_rate(Decimal(item['annual_rate']))}%"
                    f" | 天数={item['days']}"
                    f" | 利息={item['interest']} 元"
                )

        yield event.plain_result("\n".join(lines))

    @loan.command("show")
    async def loan_show(self, event: AstrMessageEvent, borrower: str = "", cutoff_date: str = ""):
        """查询借款人：/loan show <借款人> [截止日期]"""
        if not self._is_authorized(event):
            yield event.plain_result(self._NO_PERMISSION_MESSAGE)
            return

        try:
            result = self._service.show_borrower(
                session_id=self._session_id(event),
                borrower=borrower,
                cutoff_date_text=(cutoff_date or None),
            )
        except LoanLedgerError as exc:
            yield event.plain_result(f"查询失败：{exc}")
            return

        summary = result["summary"]
        lines = [
            f"借款人：{result['borrower']}",
            f"截止日期：{result['cutoff'].isoformat()}",
            "总览：",
            f"- 累计借款：{self._fmt_money(summary['total_loaned'])} 元",
            f"- 累计还款：{self._fmt_money(summary['total_repaid'])} 元",
            f"- 未还本金：{self._fmt_money(summary['outstanding'])} 元",
            f"- 历史已记录利息：{self._fmt_money(summary['interest_recorded'])} 元",
            f"- 未还本金应计利息：{self._fmt_money(summary['interest_open'])} 元",
            f"- 利息合计：{self._fmt_money(summary['interest_all'])} 元",
            "借款层明细：",
        ]

        tranches = result.get("tranches", [])
        if not tranches:
            lines.append("- 无借款层")
        else:
            for idx, t in enumerate(tranches, start=1):
                lines.append(
                    f"{idx}. id={t['tranche_id']} | 借款日={t['loan_date'].isoformat()} | 本金={self._fmt_money(t['principal_total'])}"
                    f" | 剩余={self._fmt_money(t['principal_outstanding'])} | 计息={'是' if t.get('interest_enabled', True) else '否'}"
                    f" | 年化={self._fmt_rate(t['annual_rate'])}%"
                    f" | 生效日={t['rate_effective_date'].isoformat()} | 截至计息天数={t['accrual_days']}"
                    f" | 截至应计={self._fmt_money(t['accrued_interest'])} 元"
                )

        lines.append("还款明细：")
        repayments = result.get("repayments", [])
        if not repayments:
            lines.append("- 无还款记录")
        else:
            for idx, r in enumerate(repayments, start=1):
                lines.append(
                    f"{idx}. 日期={r['repay_date']} | 还款={r['amount']} 元 | 本次利息={r['total_interest']} 元"
                )

        yield event.plain_result("\n".join(lines))

    @loan.command("list")
    async def loan_list(self, event: AstrMessageEvent, cutoff_date: str = ""):
        """全部汇总：/loan list [截止日期]"""
        if not self._is_authorized(event):
            yield event.plain_result(self._NO_PERMISSION_MESSAGE)
            return

        try:
            result = self._service.list_borrowers(
                session_id=self._session_id(event),
                cutoff_date_text=(cutoff_date or None),
            )
        except LoanLedgerError as exc:
            yield event.plain_result(f"查询失败：{exc}")
            return

        rows = result.get("rows", [])
        if not rows:
            yield event.plain_result("当前会话暂无借款记录")
            return

        lines = [f"借款汇总（截止 {result['cutoff'].isoformat()}）", "按借款人名称排序："]
        for idx, row in enumerate(rows, start=1):
            lines.append(
                f"{idx}. {row['borrower']} | 未还本金={self._fmt_money(row['outstanding'])} 元"
                f" | 历史利息={self._fmt_money(row['interest_recorded'])} 元"
                f" | 应计利息={self._fmt_money(row['interest_open'])} 元"
                f" | 利息合计={self._fmt_money(row['interest_all'])} 元"
            )

        yield event.plain_result("\n".join(lines))

    @staticmethod
    def _session_id(event: AstrMessageEvent) -> str:
        session_id = event.get_session_id() or event.get_group_id() or event.get_sender_id() or "default"
        return str(session_id)

    @staticmethod
    def _fmt_money(value: Decimal) -> str:
        return f"{value:.2f}"

    @staticmethod
    def _fmt_rate(value: Decimal) -> str:
        return f"{value:.4f}"

    @staticmethod
    def _help_text() -> str:
        return (
            "借款记录插件（LPR 官网自动利率）\n"
            "权限：管理员可用；非管理员需在配置白名单内\n"
            "命令：\n"
            "1) /loan add <借款人> <金额> [借款日期] [计息开关]\n"
            "   示例A: /loan add 张三 200000\n"
            "   示例B: /loan add 张三 200000 2026-01-01\n"
            "   示例C: /loan add 张三 200000 nointerest\n"
            "   示例D: /loan add 张三 200000 2026-01-01 计息\n"
            "2) /loan repay <借款人> <金额> [还款日期]\n"
            "   示例A: /loan repay 张三 20000\n"
            "   示例B: /loan repay 张三 20000 2026-02-01\n"
            "3) /loan show <借款人> [截止日期]\n"
            "4) /loan list [截止日期]\n"
            "日期支持: YYYY-MM-DD 或 M月D日（默认当前年，不填日期默认当天）\n"
            "计息开关支持: interest/nointerest/yes/no/true/false/计息/不计息/是/否\n"
            "规则: 按天单利、含起不含止、还款只冲本金、FIFO 冲抵"
        )

    def _is_authorized(self, event: AstrMessageEvent) -> bool:
        if event.is_admin():
            return True

        if not self._get_bool_config("enable_user_whitelist", True):
            return False

        sender_id = str(event.get_sender_id() or "").strip()
        if not sender_id:
            return False
        return sender_id in self._parse_user_whitelist(self._get_str_config("user_whitelist", ""))

    @staticmethod
    def _parse_user_whitelist(raw_text: str) -> set[str]:
        # 支持逗号与换行混合配置，自动去空格并去重。
        normalized = (raw_text or "").replace("，", ",")
        items = re.split(r"[\r\n,]+", normalized)
        return {item.strip() for item in items if item and item.strip()}

    def _parse_add_optional_args(self, arg3: str, arg4: str) -> tuple[str | None, bool]:
        token3 = (arg3 or "").strip()
        token4 = (arg4 or "").strip()
        default_interest_enabled = self._get_bool_config("default_interest_enabled", True)

        if token3 == "":
            if token4:
                raise LoanLedgerError("参数格式错误：第四个参数仅在第三个参数为日期时可用")
            return None, default_interest_enabled

        if self._is_date_token(token3):
            if token4 == "":
                return token3, default_interest_enabled
            parsed4 = self._parse_interest_flag(token4)
            if parsed4 is None:
                raise LoanLedgerError("计息开关无效，支持：interest/nointerest/yes/no/true/false/计息/不计息/是/否")
            return token3, parsed4

        parsed3 = self._parse_interest_flag(token3)
        if parsed3 is not None:
            if token4:
                raise LoanLedgerError("参数格式错误：第三个参数为计息开关时，不可再传第四个参数")
            return None, parsed3

        raise LoanLedgerError("第三个参数必须是日期或计息开关")

    @staticmethod
    def _is_date_token(text: str) -> bool:
        return bool(
            re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", text)
            or re.fullmatch(r"(\d{1,2})月(\d{1,2})日", text)
        )

    def _parse_interest_flag(self, text: str) -> bool | None:
        token = (text or "").strip().lower()
        if token in self._INTEREST_TRUE_TOKENS:
            return True
        if token in self._INTEREST_FALSE_TOKENS:
            return False
        return None

    def _get_config_value(self, key: str, default: Any) -> Any:
        if hasattr(self.config, "get"):
            try:
                return self.config.get(key, default)
            except Exception:
                return default
        return default

    def _get_str_config(self, key: str, default: str) -> str:
        value = self._get_config_value(key, default)
        return str(value).strip() if value is not None else default

    def _get_bool_config(self, key: str, default: bool) -> bool:
        value = self._get_config_value(key, default)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            text = value.strip().lower()
            if text in {"1", "true", "yes", "on"}:
                return True
            if text in {"0", "false", "no", "off"}:
                return False
        return bool(value)

    def _get_int_config(self, key: str, default: int, *, min_value: int, max_value: int) -> int:
        value = self._get_config_value(key, default)
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            parsed = default
        return max(min_value, min(max_value, parsed))
