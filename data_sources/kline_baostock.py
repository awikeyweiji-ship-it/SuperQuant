from __future__ import annotations

import atexit
import time
from typing import Any, Dict, List

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


def fetch(code: str, limit: int = 520) -> Dict[str, Any]:
    ident = canonical_identity(code)
    errors: List[Dict[str, Any]] = []
    series: List[Dict[str, Any]] = []
    url = "baostock.query_history_k_data_plus"
    status_code = None
    try:
        _ensure_login()
        fields = "date,open,high,low,close,preclose,volume,amount"
        rs = bs.query_history_k_data_plus(
            ident.baostock_code,
            fields,
            frequency="d",
            adjustflag="2",
        )
        status_code = int(rs.error_code) if rs.error_code and rs.error_code.isdigit() else None
        if rs.error_code != "0":
            errors.append(build_error("kline_baostock", "api_error", rs.error_msg))
        else:
            while rs.next():
                row = rs.get_row_data()
                try:
                    series.append(
                        {
                            "date": row[0],
                            "open": float(row[1]),
                            "high": float(row[2]),
                            "low": float(row[3]),
                            "close": float(row[4]),
                            "preclose": float(row[5]) if row[5] not in (None, "") else None,
                            "volume": float(row[6]),
                            "amount": float(row[7]) if row[7] not in (None, "") else None,
                        }
                    )
                except Exception:
                    continue
        if len(series) > limit:
            series = series[-limit:]
    except Exception as exc:  # noqa: BLE001
        errors.append(build_error("kline_baostock", "exception", str(exc)))
    filled = len(series)
    meta = {
        "source": "kline_baostock",
        "retrieved_at": time.time(),
        "errors": errors,
        "filled_metrics": filled,
        "url": url,
        "status_code": status_code,
        "used_code": ident.baostock_code,
    }
    if filled < 120:
        errors.append(build_error("kline_baostock", "insufficient", f"rows={filled}"))
        meta["errors"] = errors
    return {"data": {"series": series}, "meta": meta}
