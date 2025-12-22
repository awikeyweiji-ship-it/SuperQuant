"""TuShare Pro kline provider (daily OHLCV)."""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

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


def fetch(ts_code: str, token: str, limit: int = 240, start_date: Optional[str] = None, end_date: Optional[str] = None) -> ProviderResult:
    errors: List[Dict[str, Any]] = []
    meta: Dict[str, Any] = {"source": "tushare", "retrieved_at": time.time(), "ts_code": ts_code}
    data: Dict[str, Any] = {}
    filled = 0
    try:
        pro = _get_pro(token)
        kwargs: Dict[str, Any] = {"ts_code": ts_code, "limit": max(limit, 1)}
        if start_date:
            kwargs["start_date"] = start_date
        if end_date:
            kwargs["end_date"] = end_date
        df_daily = pro.daily(**kwargs)
        if df_daily is not None and len(df_daily) > 0:
            df_sorted = df_daily.sort_values(by="trade_date", ascending=True)
            df_sorted = df_sorted[["trade_date", "open", "high", "low", "close", "vol", "amount"]]
            df_sorted = df_sorted.rename(columns={"trade_date": "date"})
            records = []
            for _, row in df_sorted.iterrows():
                rec = {
                    "date": str(row.get("date")),
                    "open": _safe_float(row.get("open")),
                    "high": _safe_float(row.get("high")),
                    "low": _safe_float(row.get("low")),
                    "close": _safe_float(row.get("close")),
                    "volume": _safe_float(row.get("vol")),
                    "amount": _safe_float(row.get("amount")),
                }
                records.append(rec)
            data["daily"] = records
            filled = len(records)
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
