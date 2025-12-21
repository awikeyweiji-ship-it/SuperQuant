"""Eastmoney quote provider for real-time snapshot fields."""
from __future__ import annotations

import time
from typing import Any, Dict, Optional

import requests

from data_sources.identity import canonical_identity

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Referer": "https://quote.eastmoney.com/",
}


def _to_float(val: Any, scale: float = 1.0) -> Optional[float]:
    if val in (None, "", "--"):
        return None
    try:
        return float(val) / scale
    except Exception:
        try:
            return float(str(val).replace("%", "")) / scale
        except Exception:
            return None


def _count(data: Dict[str, Any]) -> int:
    return sum(1 for v in data.values() if v not in (None, "", "--"))


def fetch(symbol: str, timeout: float = 6.0, retries: int = 1, **_: Any) -> Dict[str, Any]:
    ident = canonical_identity(symbol)
    meta = {
        "source": "quote_eastmoney",
        "retrieved_at": time.time(),
        "errors": [],
        "fallback_used": False,
        "cache_hit": False,
        "used_key": ident.secid,
        "filled_metrics": 0,
    }

    url = "https://push2.eastmoney.com/api/qt/stock/get"
    params = {
        "secid": ident.secid,
        "fields": "f43,f44,f45,f46,f47,f48,f49,f50,f51,f52,f57,f58,f59,f60,f116,f117,f168,f170,f171,f172,f173,f84",
    }

    last_exc: Optional[Exception] = None
    for attempt in range(max(1, retries + 1)):
        try:
            resp = requests.get(url, params=params, timeout=timeout, headers=HEADERS)
            meta.setdefault("status_code", resp.status_code)
            resp.raise_for_status()
            payload = resp.json() or {}
            data = payload.get("data") if isinstance(payload, dict) else None
            if not isinstance(data, dict):
                meta["errors"].append(
                    {
                        "source": meta["source"],
                        "error_type": "invalid",
                        "message": "payload data not dict",
                        "response_snippet": str(payload)[:200],
                    }
                )
                continue

            vol_raw = _to_float(data.get("f47"))
            amount_raw = _to_float(data.get("f48"))
            payload_data = {
                "code": ident.symbol,
                "name": data.get("f58", ""),
                "price": _to_float(data.get("f43"), scale=100),
                "open": _to_float(data.get("f46"), scale=100),
                "high": _to_float(data.get("f44"), scale=100),
                "low": _to_float(data.get("f45"), scale=100),
                "pre_close": _to_float(data.get("f60"), scale=100),
                "pct_chg": _to_float(data.get("f170"), scale=100),
                "volume": vol_raw * 100 if vol_raw is not None else None,
                "amount": amount_raw,
                "turnover": _to_float(data.get("f84"), scale=100),
            }
            meta["filled_metrics"] = _count(payload_data)
            meta["errors_count"] = len(meta["errors"])
            return {"data": payload_data, "meta": meta}
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            meta["errors"].append(
                {
                    "source": meta["source"],
                    "error_type": "exception",
                    "message": str(exc),
                    "url": url,
                    "used_key": ident.secid,
                }
            )
            if attempt < retries:
                time.sleep(0.5 * (attempt + 1))

    meta["errors_count"] = len(meta["errors"])
    if last_exc:
        meta.setdefault("last_exception", str(last_exc))
    return {"data": {}, "meta": meta}
