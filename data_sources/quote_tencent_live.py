from __future__ import annotations

import re
import time
from typing import Any, Dict, List

import requests

from data_sources.provider_registry import ProviderResult
from data_sources.quote_sina_live import infer_prefix

TENCENT_URL = "http://qt.gtimg.cn/q={symbol}"


def fetch(raw_code: str) -> ProviderResult:
    code = str(raw_code).strip()
    prefix = infer_prefix(code)
    symbol = f"{prefix}{code}"
    url = TENCENT_URL.format(symbol=symbol)
    errors: List[Dict[str, Any]] = []
    data: Dict[str, Any] = {}
    status_code: int | None = None
    body_snippet: str | None = None
    try:
        resp = requests.get(
            url,
            timeout=8,
            headers={"User-Agent": "Mozilla/5.0", "Referer": "http://qt.gtimg.cn"},
        )
        status_code = resp.status_code
        body_snippet = (resp.text or "")[:200]
        if resp.status_code == 200:
            payload = _parse(resp.text)
            if payload:
                data = payload
            else:
                errors.append({"source": "quote_tencent", "error_type": "empty", "message": "no fields"})
        else:
            errors.append({"source": "quote_tencent", "error_type": "http_error", "message": f"status {resp.status_code}"})
    except Exception as exc:  # noqa: BLE001
        errors.append({"source": "quote_tencent", "error_type": "exception", "message": str(exc)})
    filled = sum(1 for v in data.values() if v not in (None, "", "--"))
    meta = {
        "source": "quote_tencent",
        "retrieved_at": time.time(),
        "errors": errors,
        "filled_metrics": filled,
        "url": url,
        "status_code": status_code,
        "body_snippet": body_snippet,
    }
    if not data:
        meta["filled_metrics"] = 0
    return ProviderResult(data=data, filled_metrics=meta["filled_metrics"], errors=errors, meta=meta)


def _parse(text: str) -> Dict[str, Any]:
    if "~" not in text:
        return {}
    m = re.search(r"\=\"(.+)\"", text)
    payload = m.group(1) if m else ""
    parts = payload.split("~")
    if len(parts) < 30:
        return {}
    try:
        preclose = parts[4]
        price = parts[3]
        pct = None
        if preclose not in {"", "0"}:
            pct = (float(price) - float(preclose)) / float(preclose) * 100
    except Exception:
        pct = None
    return {
        "name": parts[1],
        "price": parts[3],
        "pct": pct,
        "amount": parts[37] if len(parts) > 37 else "",
        "volume": parts[6],
        "turnover": None,
        "time": parts[30] if len(parts) > 30 else "",
        "open": parts[5],
        "preclose": preclose,
        "high": parts[33] if len(parts) > 33 else "",
        "low": parts[34] if len(parts) > 34 else "",
    }
