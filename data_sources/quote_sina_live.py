from __future__ import annotations

import time
from typing import Dict, Any, List
import requests

from data_sources.provider_registry import ProviderResult

SINA_URL_TEMPLATE = "http://hq.sinajs.cn/list={symbol}"


def parse_sina_response(text: str) -> Dict[str, Any]:
    parts = text.split("\n")[0].split("=")
    if len(parts) < 2:
        return {}
    payload = parts[1].strip().strip('"')
    fields = payload.split(",")
    if len(fields) < 32:
        return {}
    name = fields[0].strip()
    open_px = fields[1]
    preclose = fields[2]
    price = fields[3]
    high = fields[4]
    low = fields[5]
    volume = fields[8]
    amount = fields[9]
    date_str = fields[30] if len(fields) > 30 else ""
    time_str = fields[31] if len(fields) > 31 else ""
    pct = None
    try:
        pct = (float(price) - float(preclose)) / float(preclose) * 100 if preclose not in {"0", ""} else None
    except Exception:
        pct = None
    return {
        "name": name,
        "price": price,
        "pct": pct,
        "amount": amount,
        "volume": volume,
        "turnover": None,
        "time": f"{date_str} {time_str}".strip(),
        "open": open_px,
        "preclose": preclose,
        "high": high,
        "low": low,
    }


def fetch(raw_code: str) -> ProviderResult:
    symbol = normalize_symbol(raw_code)
    url = SINA_URL_TEMPLATE.format(symbol=symbol)
    errors: List[Dict[str, Any]] = []
    data: Dict[str, Any] = {}
    status_code: int | None = None
    body_snippet: str | None = None
    try:
        resp = requests.get(
            url,
            timeout=8,
            headers={"User-Agent": "Mozilla/5.0", "Referer": "http://finance.sina.com.cn"},
        )
        status_code = resp.status_code
        resp.encoding = "gbk"
        body_snippet = (resp.text or "")[:200]
        if resp.status_code == 200:
            data = parse_sina_response(resp.text)
            if not data:
                errors.append({"source": "quote_sina", "error_type": "empty", "message": "payload empty"})
        else:
            errors.append({"source": "quote_sina", "error_type": "http_error", "message": f"status {resp.status_code}"})
    except Exception as exc:  # noqa: BLE001
        errors.append({"source": "quote_sina", "error_type": "exception", "message": str(exc)})
    filled = sum(1 for v in data.values() if v not in (None, "", "--"))
    meta = {
        "source": "quote_sina",
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


def normalize_symbol(raw_code: str) -> str:
    code = str(raw_code).strip().upper()
    if code.startswith("SH") or code.startswith("SZ"):
        return code.lower()
    prefix = infer_prefix(code)
    return f"{prefix}{code}"


def infer_prefix(code: str) -> str:
    if code.startswith(("60", "68", "50", "11")):
        return "sh"
    if code.startswith(("00", "30", "20")):
        return "sz"
    if code.startswith(("8", "4")):
        return "bj"
    return "sz"
