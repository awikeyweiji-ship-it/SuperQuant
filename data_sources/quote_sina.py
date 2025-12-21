from __future__ import annotations
import time
import requests
from typing import Dict, Any
from data_sources.identity import canonical_identity
from logging_utils import build_error

def fetch(code: str) -> Dict[str, Any]:
    ident = canonical_identity(code)
    prefixed = ident.prefixed
    url = f"http://hq.sinajs.cn/list={prefixed}"
    errors = []
    data: Dict[str, Any] = {}
    try:
        resp = requests.get(url, timeout=6)
        if resp.status_code != 200 or '=""' in resp.text:
            errors.append(build_error("quote_sina", "http_error", f"status {resp.status_code}"))
        else:
            text = resp.text
            if '="' in text:
                body = text.split('="',1)[1].split('";',1)[0]
                parts = body.split(',')
                if len(parts) >= 6:
                    data = {
                        "code": ident.symbol,
                        "name": parts[0],
                        "open": _to_float(parts[1]),
                        "preclose": _to_float(parts[2]),
                        "price": _to_float(parts[3]),
                        "high": _to_float(parts[4]),
                        "low": _to_float(parts[5]),
                        "volume": _to_float(parts[8]) if len(parts)>8 else None,
                        "amount": _to_float(parts[9]) if len(parts)>9 else None,
                        "pct_chg": _pct(_to_float(parts[3]), _to_float(parts[2])),
                    }
                else:
                    errors.append(build_error("quote_sina", "parse_error", "not enough fields"))
            else:
                errors.append(build_error("quote_sina", "empty", "no quote payload"))
    except Exception as exc:  # noqa: BLE001
        errors.append(build_error("quote_sina", "exception", str(exc)))
    meta = {
        "source": "quote_sina",
        "retrieved_at": time.time(),
        "errors": errors,
        "filled_metrics": sum(1 for v in data.values() if v not in (None, "", "--")),
        "used_key": prefixed,
        "url": url,
    }
    return {"data": data, "meta": meta}

def _to_float(val: Any):
    try:
        if val in (None, "", "--", "—"):
            return None
        return float(val)
    except Exception:
        return None

def _pct(price, preclose):
    if price is None or preclose in (None, 0):
        return None
    try:
        return (float(price) - float(preclose)) / float(preclose) * 100
    except Exception:
        return None
