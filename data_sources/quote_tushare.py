"""TuShare Pro quote provider (daily snapshot from daily/daily_basic)."""
from __future__ import annotations

import time
from typing import Any, Dict, List

from data_sources.provider_registry import ProviderResult


class _MissingToken(Exception):
    pass


def _get_pro(token: str):
    try:
        import tushare as ts  # type: ignore
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"tushare import failed: {exc}") from exc
    if not token:
        raise _MissingToken("TuShare token missing")
    return ts.pro_api(token)


def fetch(ts_code: str, token: str) -> ProviderResult:
    errors: List[Dict[str, Any]] = []
    meta: Dict[str, Any] = {"source": "tushare", "retrieved_at": time.time(), "ts_code": ts_code}
    data: Dict[str, Any] = {}
    filled = 0
    try:
        pro = _get_pro(token)
        df_daily = pro.daily(ts_code=ts_code, limit=5)
        df_basic = pro.daily_basic(ts_code=ts_code, limit=5)
        latest_daily = df_daily.iloc[0] if df_daily is not None and len(df_daily) > 0 else None
        latest_basic = df_basic.iloc[0] if df_basic is not None and len(df_basic) > 0 else None
        if latest_daily is not None:
            data.update(
                {
                    "close": _safe_float(latest_daily.get("close")),
                    "pct_chg": _safe_float(latest_daily.get("pct_chg")),
                    "vol": _safe_float(latest_daily.get("vol")),
                    "amount": _safe_float(latest_daily.get("amount")),
                    "trade_date": str(latest_daily.get("trade_date")),
                }
            )
            filled += 1
        if latest_basic is not None:
            data.update(
                {
                    "turnover_rate": _safe_float(latest_basic.get("turnover_rate")),
                    "pe_ttm": _safe_float(latest_basic.get("pe_ttm")),
                    "pb": _safe_float(latest_basic.get("pb")),
                }
            )
            filled += 1
    except _MissingToken as exc:  # noqa: BLE001
        errors.append({"source": "tushare", "error_type": "token", "message": str(exc)})
    except Exception as exc:  # noqa: BLE001
        errors.append({"source": "tushare", "error_type": "exception", "message": str(exc)})
    meta["filled_metrics"] = filled if data else 0
    meta["errors"] = errors
    return ProviderResult(data=data, filled_metrics=meta["filled_metrics"], errors=errors, meta=meta)


def _safe_float(val: Any):
    try:
        if val is None:
            return None
        return float(val)
    except Exception:
        return None
