"""Money flow provider from Eastmoney push2 endpoints."""
from __future__ import annotations

import re
import time
from typing import Any, Dict, Optional

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


def _to_float(val: Any) -> Optional[float]:
    if val in (None, "", "--"):
        return None
    try:
        return float(val)
    except Exception:
        try:
            return float(str(val).replace(",", ""))
        except Exception:
            return None


def _count(data: Dict[str, Any]) -> int:
    return sum(1 for v in data.values() if v not in (None, "", "--"))


def fetch(symbol: str, **_: Any) -> Dict[str, Any]:
    code_std = _standardize(symbol)
    secid = _to_secid(code_std)
    meta = {
        "source": "moneyflow_eastmoney",
        "retrieved_at": time.time(),
        "errors": [],
        "fallback_used": False,
        "cache_hit": False,
        "filled_metrics": 0,
        "unit": "万元",
    }

    url = "https://push2.eastmoney.com/api/qt/stock/fflow/daykline/get"
    params = {
        "lmt": 1,
        "klt": 101,
        "secid": secid,
        "fields1": "f1,f2,f3,f7",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63,f64,f65",
    }
    try:
        resp = requests.get(url, params=params, timeout=8)
        raw_data = (resp.json() or {}).get("data") or {}
        klines = raw_data.get("klines") or []
        if not klines:
            meta["errors"].append({"source": meta["source"], "error_type": "empty", "message": "no data"})
            return {"data": {}, "meta": meta}
        parts = str(klines[0]).split(",")
        payload = {
            "date": parts[0] if len(parts) > 0 else None,
            "main_net_inflow": _to_float(parts[1]) if len(parts) > 1 else None,
            "main_net_ratio": _to_float(parts[2]) if len(parts) > 2 else None,
            "super_large": _to_float(parts[3]) if len(parts) > 3 else None,
            "super_large_ratio": _to_float(parts[4]) if len(parts) > 4 else None,
            "large": _to_float(parts[5]) if len(parts) > 5 else None,
            "large_ratio": _to_float(parts[6]) if len(parts) > 6 else None,
            "mid": _to_float(parts[7]) if len(parts) > 7 else None,
            "mid_ratio": _to_float(parts[8]) if len(parts) > 8 else None,
            "small": _to_float(parts[9]) if len(parts) > 9 else None,
            "small_ratio": _to_float(parts[10]) if len(parts) > 10 else None,
        }
        meta["filled_metrics"] = _count({k: v for k, v in payload.items() if k != "date"})
        return {"data": payload, "meta": meta}
    except Exception as exc:  # noqa: BLE001
        meta["errors"].append({"source": meta["source"], "error_type": "exception", "message": str(exc)})
        return {"data": {}, "meta": meta}
