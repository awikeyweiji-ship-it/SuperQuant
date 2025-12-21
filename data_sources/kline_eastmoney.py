"""Daily/weekly/monthly K线抓取（Eastmoney push2his）。

仅使用公开 push2his 接口，输出经过清洗且按日期升序的 OHLCV 序列，
保证单股面板的基础行情不为空。
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Tuple

import requests

from data_sources.identity import canonical_identity

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Referer": "https://quote.eastmoney.com/",
}


def _to_float(val: Any) -> float | None:
    if val in (None, "", "--"):
        return None
    try:
        return float(val)
    except Exception:
        try:
            return float(str(val).replace(",", ""))
        except Exception:
            return None


def _clean_rows(raw_rows: List[str]) -> List[Dict[str, Any]]:
    cleaned: List[Dict[str, Any]] = []
    for line in raw_rows:
        parts = str(line).split(",")
        if len(parts) < 6:
            continue
        date = parts[0]
        open_px = _to_float(parts[1])
        close = _to_float(parts[2])
        high = _to_float(parts[3])
        low = _to_float(parts[4])
        volume = _to_float(parts[5])
        if None in (open_px, close, high, low, volume):
            continue
        cleaned.append(
            {
                "date": date,
                "open": open_px,
                "close": close,
                "high": high,
                "low": low,
                "volume": volume,
            }
        )
    # 按日期升序并去重
    seen: Dict[str, Dict[str, Any]] = {}
    for row in cleaned:
        seen[row["date"]] = row
    ordered = [seen[k] for k in sorted(seen)]
    return ordered


def fetch(symbol: str, klt: str = "101", limit: int = 400, timeout: float = 8.0) -> Dict[str, Any]:
    ident = canonical_identity(symbol)
    meta: Dict[str, Any] = {
        "source": "kline_eastmoney",
        "retrieved_at": time.time(),
        "used_key": ident.secid,
        "errors": [],
        "filled_metrics": 0,
    }

    url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
    params = {
        "secid": ident.secid,
        "klt": klt,
        "fqt": 1,
        "lmt": limit,
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
    }

    try:
        resp = requests.get(url, params=params, headers=HEADERS, timeout=timeout)
        meta["status_code"] = resp.status_code
        resp.raise_for_status()
        payload = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
    except Exception as exc:  # noqa: BLE001
        meta["errors"].append({"source": meta["source"], "error_type": "exception", "message": str(exc), "url": url})
        meta["errors_count"] = len(meta["errors"])
        return {"data": {}, "meta": meta}

    if not isinstance(payload, dict):
        meta["errors"].append({"source": meta["source"], "error_type": "invalid", "message": "non-dict payload", "response_snippet": str(payload)[:200]})
        meta["errors_count"] = len(meta["errors"])
        return {"data": {}, "meta": meta}

    raw_rows = (((payload.get("data") or {}).get("klines")) or []) if isinstance(payload.get("data"), dict) else []
    if not isinstance(raw_rows, list):
        meta["errors"].append({"source": meta["source"], "error_type": "invalid", "message": "klines not list", "response_snippet": str(raw_rows)[:200]})
        raw_rows = []

    cleaned_rows = _clean_rows(raw_rows)
    meta["filled_metrics"] = len(cleaned_rows)
    meta["errors_count"] = len(meta["errors"])
    if not cleaned_rows and not meta["errors"]:
        meta["errors"].append({"source": meta["source"], "error_type": "empty", "message": "no kline rows"})
        meta["errors_count"] = len(meta["errors"])

    return {"data": {"rows": cleaned_rows}, "meta": meta}

