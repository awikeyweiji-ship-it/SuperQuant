# -*- coding: utf-8 -*-

"""capital_engine.py
Step5: Capital/flow intelligence (optional)
- Provides extra money-flow and capital-operation features with graceful fallback.
"""

from __future__ import annotations

import re

from typing import Any, Dict, List, Optional

from logging_utils import get_data_logger, make_result, build_error, FetchResult
from data_sources.capital_eastmoney import (
    fetch_capital_flow_em,
    fetch_margin_balance_em,
    fetch_northbound_market_em,
)

try:
    import akshare as ak
except Exception:
    ak = None


def _safe_float(x, default=0.0) -> float:
    try:
        if x is None:
            return float(default)
        s = str(x).strip().replace(',', '').replace('%', '')
        if s in ('', '--', 'nan', 'None', 'NaN'):
            return float(default)
        return float(s)
    except Exception:
        return float(default)


class CapitalEngine:
    """Fetch capital-flow related features.

    Notes:
    - AkShare interfaces vary by version. This engine tries multiple function names
      and returns best-effort outputs, never raising to callers.
    """

    def __init__(self):
        self.logger = get_data_logger("superquant.capital")

    def _standardize_code(self, code: str) -> str:
        code = str(code).strip()
        code = re.sub(r"\.(SH|SZ|BJ|sh|sz|bj)$", "", code)
        if code.isdigit() and len(code) < 6:
            code = code.zfill(6)
        market = "SH" if code.startswith("6") else "SZ"
        if code.startswith(("8", "4")):
            market = "BJ"
        return f"{code}.{market}"

    def _try(self, fn_name: str, **kwargs):
        if ak is None:
            return None
        fn = getattr(ak, fn_name, None)
        if not callable(fn):
            return None
        try:
            return fn(**kwargs)
        except Exception as e:
            self.logger.warning("AkShare 资金接口 %s 异常: %s", fn_name, e)
            return None

    def _fetch_capital_akshare(self, code: str, errors: List[Dict[str, str]]) -> Optional[Dict[str, Any]]:
        for fn in (
            "stock_individual_fund_flow",
            "stock_individual_fund_flow_em",
            "stock_individual_fund_flow_rank",
        ):
            df = self._try(fn, symbol=code) or self._try(fn, stock=code)
            if df is None or getattr(df, "empty", True):
                continue
            try:
                last = df.iloc[-1].to_dict()
                mapped = {
                    "main_net_inflow": _safe_float(last.get("主力净流入-净额") or last.get("主力净流入") or last.get("净流入") or last.get("主力净流入净额")),
                    "super_large_net_inflow": _safe_float(last.get("超大单净流入-净额") or last.get("超大单净流入")),
                    "large_net_inflow": _safe_float(last.get("大单净流入-净额") or last.get("大单净流入")),
                    "medium_net_inflow": _safe_float(last.get("中单净流入-净额") or last.get("中单净流入")),
                    "small_net_inflow": _safe_float(last.get("小单净流入-净额") or last.get("小单净流入")),
                }
                if any(mapped.values()):
                    mapped["source_detail"] = fn
                    return mapped
            except Exception as e:  # noqa: BLE001
                errors.append(build_error(fn, "parse_error", str(e)))
        errors.append(build_error("akshare", "empty", "个股资金流为空"))
        return None

    def _fetch_capital_eastmoney(self, code: str, errors: List[Dict[str, str]]) -> Optional[Dict[str, Any]]:
        try:
            data = fetch_capital_flow_em(code)
            if data:
                data["source_detail"] = "eastmoney_fflow"
                return data
            errors.append(build_error("eastmoney", "empty", "东财资金接口为空"))
        except Exception as e:  # noqa: BLE001
            errors.append(build_error("eastmoney", "exception", str(e)))
        return None

    def _fetch_northbound(self, errors: List[Dict[str, str]]) -> Optional[Dict[str, Any]]:
        if ak is not None:
            for fn in (
                "stock_hsgt_fund_flow_summary_em",
                "stock_hsgt_fund_flow_summary",
            ):
                df = self._try(fn)
                if df is None or getattr(df, "empty", True):
                    continue
                try:
                    row0 = df.iloc[0].to_dict()
                    for k in ["当日资金流入", "当日资金净流入", "净流入", "资金净流入"]:
                        if k in row0:
                            return {"northbound_net_inflow": _safe_float(row0.get(k)), "source_detail": fn}
                except Exception as e:  # noqa: BLE001
                    errors.append(build_error(fn, "parse_error", str(e)))
        try:
            data = fetch_northbound_market_em()
            if data:
                data["source_detail"] = "eastmoney_northbound"
                return data
        except Exception as e:  # noqa: BLE001
            errors.append(build_error("eastmoney", "exception", str(e)))
        errors.append(build_error("northbound", "empty", "北向资金汇总为空"))
        return None

    def _fetch_margin(self, code: str, errors: List[Dict[str, str]]) -> Optional[Dict[str, Any]]:
        if ak is not None:
            for fn in ("stock_margin_sse", "stock_margin_detail_szse"):
                df = self._try(fn)
                if df is None or getattr(df, "empty", True):
                    continue
                try:
                    c = df.copy()
                    if "SECURITY_CODE" in c.columns:
                        code_col = "SECURITY_CODE"
                    elif "股票代码" in c.columns:
                        code_col = "股票代码"
                    else:
                        continue
                    plain = self._standardize_code(code).split(".")[0]
                    row = c[c[code_col].astype(str).str.contains(plain)]
                    if row.empty:
                        continue
                    r = row.iloc[-1].to_dict()
                    balance = r.get("融资余额") or r.get("RZYE") or r.get("rzye")
                    short_balance = r.get("融券余量金额") or r.get("RQYLJE") or r.get("rqylje")
                    return {
                        "margin_balance": _safe_float(balance),
                        "short_balance": _safe_float(short_balance),
                        "margin_date": r.get("日期") or r.get("TRADE_DATE") or r.get("trade_date"),
                        "source_detail": fn,
                    }
                except Exception as e:  # noqa: BLE001
                    errors.append(build_error(fn, "parse_error", str(e)))
        try:
            data = fetch_margin_balance_em(code)
            if data:
                data["source_detail"] = "eastmoney_margin"
                return data
        except Exception as e:  # noqa: BLE001
            errors.append(build_error("eastmoney", "exception", str(e)))
        errors.append(build_error("margin", "empty", "融资融券数据缺失"))
        return None

    def _offline_stub(self, code_std: str) -> Dict[str, Any]:
        samples = {
            "600519.SH": {
                "main_net_inflow": 1.5e9,
                "large_net_inflow": 8.8e8,
                "super_large_net_inflow": 4.2e8,
                "northbound_net_inflow": 3.1e8,
                "margin_balance": 2.3e10,
                "margin_date": "离线样本",  # noqa: EM101
            },
            "000001.SZ": {
                "main_net_inflow": 6.6e8,
                "large_net_inflow": 3.3e8,
                "super_large_net_inflow": 1.1e8,
                "northbound_net_inflow": 2.5e8,
                "margin_balance": 1.5e10,
                "margin_date": "离线样本",  # noqa: EM101
            },
        }
        return samples.get(code_std, {})

    def get_capital_features_structured(self, code: str) -> FetchResult:
        code_std = self._standardize_code(code)
        out: Dict[str, Any] = {}
        errors: List[Dict[str, str]] = []
        fallback_used = False
        source = ""

        # 1) AkShare 主力/大单
        ak_data = self._fetch_capital_akshare(code_std, errors)
        if ak_data:
            out.update({k: v for k, v in ak_data.items() if v is not None})
            source = "akshare"

        # 2) 东财兜底
        if not out.get("main_net_inflow"):
            em_data = self._fetch_capital_eastmoney(code_std, errors)
            if em_data:
                out.update({k: v for k, v in em_data.items() if v is not None})
                source = source or "eastmoney"
                fallback_used = True

        # 3) 北向市场级
        nb = self._fetch_northbound(errors)
        if nb:
            out.update({k: v for k, v in nb.items() if v is not None})
            if source:
                fallback_used = True
            source = source or nb.get("source_detail", "northbound")

        # 4) 融资融券
        margin = self._fetch_margin(code_std, errors)
        if margin:
            out.update({k: v for k, v in margin.items() if v is not None})
            if source:
                fallback_used = True
            source = source or margin.get("source_detail", "margin")

        # 5) 离线兜底
        if not out.get("main_net_inflow"):
            stub = self._offline_stub(code_std)
            if stub:
                out.update(stub)
                fallback_used = True
                source = source or "offline_stub"
                errors.append(build_error("offline", "fallback", "使用离线资金样本，数据可能过期"))

        if not out:
            errors.append(build_error("capital", "empty", "资金数据为空"))

        return make_result(out, source=source or "capital_flow", errors=errors, fallback_used=fallback_used or bool(errors))

    def get_capital_features(self, code: str) -> Dict[str, Any]:
        return self.get_capital_features_structured(code).data
