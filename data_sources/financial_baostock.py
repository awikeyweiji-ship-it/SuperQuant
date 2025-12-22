from __future__ import annotations

import atexit
import datetime as dt
import time
from typing import Any, Dict, List

try:  # noqa: SIM105
    import baostock as bs  # type: ignore
except Exception:  # noqa: BLE001
    bs = None  # type: ignore

from data_sources.identity import canonical_identity
from logging_utils import build_error

_LOGIN_DONE = False

def _ensure_login():
    global _LOGIN_DONE
    if _LOGIN_DONE:
        return
    if bs is None:
        raise RuntimeError("baostock not installed")
    lg = bs.login()
    if lg.error_code != "0":
        raise RuntimeError(f"baostock login failed: {lg.error_msg}")
    _LOGIN_DONE = True
    atexit.register(_safe_logout)


def _safe_logout():
    global _LOGIN_DONE
    if not _LOGIN_DONE:
        return
    if bs is None:
        return
    try:
        bs.logout()
    except Exception:
        pass
    _LOGIN_DONE = False


def _year_quarter_backwards(max_back: int = 6):
    today = dt.date.today()
    year = today.year
    quarter = (today.month - 1) // 3 + 1
    for _ in range(max_back):
        yield year, quarter
        quarter -= 1
        if quarter <= 0:
            quarter = 4
            year -= 1


def fetch(code: str) -> Dict[str, Any]:
    ident = canonical_identity(code)
    errors: List[Dict[str, Any]] = []
    records: List[Dict[str, Any]] = []
    url = "baostock.query_financial_indicator"
    status_code = None
    try:
        _ensure_login()
        for year, quarter in _year_quarter_backwards():
            rs = bs.query_financial_indicator(code=ident.baostock_code, year=year, quarter=quarter)
            status_code = int(rs.error_code) if rs.error_code and rs.error_code.isdigit() else None
            if rs.error_code != "0":
                errors.append(build_error("financial_baostock", "api_error", rs.error_msg))
                continue
            while rs.next():
                row = rs.get_row_data()
                if not row:
                    continue
                try:
                    records.append(
                        {
                            "year": year,
                            "quarter": quarter,
                            "eps": float(row[2]) if row[2] not in (None, "") else None,
                            "roe": float(row[4]) if row[4] not in (None, "") else None,
                            "net_profit_ratio": float(row[6]) if row[6] not in (None, "") else None,
                            "gross_profit_ratio": float(row[8]) if row[8] not in (None, "") else None,
                            "net_profit": float(row[10]) if row[10] not in (None, "") else None,
                            "total_revenue": float(row[11]) if row[11] not in (None, "") else None,
                            "total_profit": float(row[9]) if row[9] not in (None, "") else None,
                            "assets_turn": float(row[14]) if row[14] not in (None, "") else None,
                            "current_ratio": float(row[16]) if row[16] not in (None, "") else None,
                            "inv_turn": float(row[20]) if row[20] not in (None, "") else None,
                        }
                    )
                except Exception:
                    continue
            if records:
                break
    except Exception as exc:  # noqa: BLE001
        errors.append(build_error("financial_baostock", "exception", str(exc)))
    meta = {
        "source": "financial_baostock",
        "retrieved_at": time.time(),
        "errors": errors,
        "filled_metrics": len(records[0]) if records else 0,
        "url": url,
        "status_code": status_code,
        "used_code": ident.baostock_code,
    }
    if not records:
        errors.append(build_error("financial_baostock", "empty", "no financial records"))
        meta["errors"] = errors
    return {"data": {"statements": records[:3]}, "meta": meta}
