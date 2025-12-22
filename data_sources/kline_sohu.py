"""Fallback daily kline via Sohu public endpoint (no login)."""
from __future__ import annotations

import time
from typing import Any, Dict, List

import requests


def fetch(code: str, limit: int = 320) -> Dict[str, Any]:
    prefix = "cn_" + code
    url = "https://q.stock.sohu.com/hisHq"
    params = {
        "code": prefix,
        "stat": 1,
        "order": "D",
        "period": "day",
        "callback": "",
    }
    series: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []
    status = None
    snippet = ""
    try:
        resp = requests.get(url, params=params, timeout=10)
        status = resp.status_code
        snippet = (resp.text or "")[:200]
        if resp.ok:
            js = resp.json()
            if isinstance(js, list) and js and isinstance(js[0], dict):
                data_rows = js[0].get("hq") or []
                for row in data_rows:
                    if not isinstance(row, list) or len(row) < 7:
                        continue
                    try:
                        series.append(
                            {
                                "date": row[0],
                                "open": float(row[1]),
                                "close": float(row[2]),
                                "high": float(row[6]),
                                "low": float(row[5]),
                                "volume": float(row[7]) if len(row) > 7 else None,
                            }
                        )
                    except Exception:
                        continue
        else:
            errors.append({"source": "kline_sohu", "error_type": "http", "message": f"status {status}"})
    except Exception as exc:  # noqa: BLE001
        errors.append({"source": "kline_sohu", "error_type": "exception", "message": str(exc)})
    series = series[-limit:]
    filled = len(series)
    meta = {
        "source": "kline_sohu",
        "retrieved_at": time.time(),
        "errors": errors,
        "filled_metrics": filled,
        "url": url,
        "status_code": status,
        "body_snippet": snippet,
    }
    if filled == 0:
        errors.append({"source": "kline_sohu", "error_type": "empty", "message": "no data"})
    meta["errors"] = errors
    return {"data": {"series": series}, "meta": meta}
