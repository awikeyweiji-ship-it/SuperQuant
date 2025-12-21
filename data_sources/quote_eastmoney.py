"""Eastmoney quote provider for real-time snapshot fields."""
from __future__ import annotations

import re
import time
from typing import Any, Dict, List, Optional

import requests


def _standardize(code: str) -> str:
    code = str(code).strip()
    code = re.sub(r"\.(SH|SZ|BJ|sh|sz|bj)$", "", code)
    if code.isdigit() and len(code) < 6:
        code = code.zfill(6)
    market = "SZ"
    if code.startswith("6"):
        market = "SH"
    elif code.startswith(("8", "4")):
        market = "BJ"
    return f"{code}.{market}"


def _to_secid(code_std: str) -> str:
    plain, market = code_std.split(".")
    return ("1" if market == "SH" else "0") + f".{plain}"


def _to_float(val: Any, scale: float = 1.0) -> Optional[float]:
    if val in (None, "", "--"):
        return None
    try:
        return float(val) / scale
    except Exception:
        return None


def _count(data: Dict[str, Any]) -> int:
    return sum(1 for v in data.values() if v not in (None, "", "--"))


def fetch(symbol: str, **_: Any) -> Dict[str, Any]:
    code_std = _standardize(symbol)
    secid = _to_secid(code_std)
    meta = {
        "source": "quote_eastmoney",
        "retrieved_at": time.time(),
        "errors": [],
        "fallback_used": False,
        "cache_hit": False,
        "filled_metrics": 0,
    }

    url = "https://push2.eastmoney.com/api/qt/stock/get"
    params = {
        "secid": secid,
        "fields": "f43,f44,f45,f46,f47,f48,f57,f58,f59,f60,f170,f71,f84,f162,f167,f116,f117",
    }

    try:
        resp = requests.get(url, params=params, timeout=8, proxies={"http": None, "https": None})
        data = (resp.json() or {}).get("data") or {}
        if not data:
            meta["errors"].append({"source": meta["source"], "error_type": "empty", "message": "no data"})
            return {"data": {}, "meta": meta}

        vol_raw = _to_float(data.get("f47"))
        amount_raw = _to_float(data.get("f48"))
        payload = {
            "code": code_std,
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
        meta["filled_metrics"] = _count(payload)
        return {"data": payload, "meta": meta}
    except Exception as exc:  # noqa: BLE001
        meta["errors"].append({"source": meta["source"], "error_type": "exception", "message": str(exc)})
        return {"data": {}, "meta": meta}
