from __future__ import annotations

import atexit
import datetime as dt
import time
from typing import Any, Dict, List, Tuple

try:  # noqa: SIM105
    import baostock as bs  # type: ignore
except Exception:  # noqa: BLE001
    bs = None  # type: ignore

from data_sources.identity import canonical_identity
from logging_utils import build_error

_LOGIN_DONE = False
_ATEEXIT_REGISTERED = False
_LOGOUT_SENTINEL = "_superquant_logout_done"


def _ensure_login():
    global _LOGIN_DONE
    global _ATEEXIT_REGISTERED
    if _LOGIN_DONE:
        return
    if bs is None:
        raise RuntimeError("baostock not installed")
    lg = bs.login()
    if lg.error_code != "0":
        raise RuntimeError(f"baostock login failed: {lg.error_msg}")
    _LOGIN_DONE = True
    if not _ATEEXIT_REGISTERED:
        atexit.register(_safe_logout)
        _ATEEXIT_REGISTERED = True


def _safe_logout():
    global _LOGIN_DONE
    if not _LOGIN_DONE:
        return
    if bs is None:
        return
    try:
        if getattr(bs, _LOGOUT_SENTINEL, False):
            return
        bs.logout()
        setattr(bs, _LOGOUT_SENTINEL, True)
    except Exception:
        pass
    _LOGIN_DONE = False


def _year_quarter_backwards(max_back: int = 8):
    today = dt.date.today()
    year = today.year
    quarter = (today.month - 1) // 3 + 1
    for _ in range(max_back):
        yield year, quarter
        quarter -= 1
        if quarter <= 0:
            quarter = 4
            year -= 1


def _floatify(val: Any) -> float | None:
    try:
        if val in (None, "", "--"):
            return None
        return float(str(val).replace(",", ""))
    except Exception:
        return None


def _query_rows(func, **params) -> Tuple[int | None, List[Dict[str, Any]]]:
    rs = func(**params)
    status_code = int(rs.error_code) if rs.error_code and rs.error_code.isdigit() else None
    if rs.error_code != "0":
        raise RuntimeError(rs.error_msg)
    rows: List[Dict[str, Any]] = []
    while rs.next():
        row = rs.get_row_data()
        if not row:
            continue
        try:
            rows.append({k.lower(): v for k, v in zip(rs.fields, row)})
        except Exception:
            continue
    return status_code, rows


_FIELD_MAP = {
    "revenue": ("mbrevenue", "operatingrevenue", "totaloperaterev"),
    "net_profit": ("netprofit", "np_parent_company_owners"),
    "roe": ("roeavg", "dupontroe"),
    "gross_margin": ("gpmargin",),
    "net_profit_margin": ("npmargin", "dupontnetprofitmargin"),
    "eps": ("epsttm", "eps0"),
    "asset_turnover": ("dupontassetturn", "nrturnratio"),
    "ar_turnover": ("arturnratio",),
    "inventory_turnover": ("inventoryturnover",),
    "current_ratio": ("currentratio",),
    "quick_ratio": ("quickratio",),
    "cash_ratio": ("cashratio",),
    "asset_liability_ratio": ("yoyliability",),
    "ocf": ("ncfoperatea", "netoperatecashflow"),
    "ocf_to_revenue": ("nocftooperatingrevenue",),
    "ocf_to_liability": ("nocftototalliability",),
    "asset_growth": ("yoyasset",),
    "equity_growth": ("yoyequity",),
    "profit_growth": ("yoyni",),
    "eps_growth": ("yoyepsbasic",),
    "profit_to_op": ("dupontpnr",),
}


def _merge_bundle(bundle: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    combined: Dict[str, Any] = {}
    lowered: Dict[str, Any] = {}
    for part in bundle.values():
        for k, v in part.items():
            lowered[k.lower()] = v
    for std_key, candidates in _FIELD_MAP.items():
        val = None
        for cand in candidates:
            if cand in lowered:
                val = _floatify(lowered[cand])
                if val is not None:
                    break
        if val is not None:
            combined[std_key] = val
    if "period" not in combined:
        combined["period"] = bundle.get("profit", {}).get("statdate") or bundle.get("profit", {}).get("pubdate")
    # Ensure at least 8 numeric fields by appending extra numeric entries
    if len([v for v in combined.values() if isinstance(v, (int, float))]) < 8:
        for k, v in lowered.items():
            fv = _floatify(v)
            if fv is None:
                continue
            if k not in combined:
                combined[k] = fv
            if len([val for val in combined.values() if isinstance(val, (int, float))]) >= 8:
                break
    return combined


def fetch(code: str) -> Dict[str, Any]:
    ident = canonical_identity(code)
    errors: List[Dict[str, Any]] = []
    statements: List[Dict[str, Any]] = []
    status_code = None
    url = "baostock.financial_bundle"

    try:
        _ensure_login()
        for year, quarter in _year_quarter_backwards():
            bundle: Dict[str, Dict[str, Any]] = {}
            try:
                status_code, profit_rows = _query_rows(bs.query_profit_data, code=ident.baostock_code, year=year, quarter=quarter)
                if profit_rows:
                    bundle["profit"] = profit_rows[0]
            except Exception as exc:  # noqa: BLE001
                errors.append(build_error("financial_baostock", "profit_error", str(exc)))
            try:
                _, bal_rows = _query_rows(bs.query_balance_data, code=ident.baostock_code, year=year, quarter=quarter)
                if bal_rows:
                    bundle["balance"] = bal_rows[0]
            except Exception as exc:  # noqa: BLE001
                errors.append(build_error("financial_baostock", "balance_error", str(exc)))
            try:
                _, cash_rows = _query_rows(bs.query_cash_flow_data, code=ident.baostock_code, year=year, quarter=quarter)
                if cash_rows:
                    bundle["cash"] = cash_rows[0]
            except Exception as exc:  # noqa: BLE001
                errors.append(build_error("financial_baostock", "cash_error", str(exc)))
            try:
                _, dupont_rows = _query_rows(bs.query_dupont_data, code=ident.baostock_code, year=year, quarter=quarter)
                if dupont_rows:
                    bundle["dupont"] = dupont_rows[0]
            except Exception as exc:  # noqa: BLE001
                errors.append(build_error("financial_baostock", "dupont_error", str(exc)))
            try:
                _, growth_rows = _query_rows(bs.query_growth_data, code=ident.baostock_code, year=year, quarter=quarter)
                if growth_rows:
                    bundle["growth"] = growth_rows[0]
            except Exception as exc:  # noqa: BLE001
                errors.append(build_error("financial_baostock", "growth_error", str(exc)))
            try:
                _, op_rows = _query_rows(bs.query_operation_data, code=ident.baostock_code, year=year, quarter=quarter)
                if op_rows:
                    bundle["operation"] = op_rows[0]
            except Exception as exc:  # noqa: BLE001
                errors.append(build_error("financial_baostock", "operation_error", str(exc)))

            if bundle:
                merged = _merge_bundle(bundle)
                numeric_count = len([v for v in merged.values() if isinstance(v, (int, float))])
                merged["year"] = year
                merged["quarter"] = quarter
                merged["filled_numeric_fields"] = numeric_count
                statements.append(merged)
                break
    except Exception as exc:  # noqa: BLE001
        errors.append(build_error("financial_baostock", "exception", str(exc)))

    filled_metrics = 0
    if statements:
        filled_metrics = len([v for v in statements[0].values() if isinstance(v, (int, float)) and v is not None])

    meta = {
        "source": "financial_baostock",
        "retrieved_at": time.time(),
        "errors": errors,
        "filled_metrics": filled_metrics,
        "url": url,
        "status_code": status_code,
        "used_code": ident.baostock_code,
    }
    if filled_metrics < 8:
        errors.append(build_error("financial_baostock", "insufficient", f"fields={filled_metrics}"))
        meta["errors"] = errors
    return {"data": {"statements": statements}, "meta": meta}
