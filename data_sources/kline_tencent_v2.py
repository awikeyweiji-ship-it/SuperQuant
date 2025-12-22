from __future__ import annotations

import time
from typing import Any, Dict, List

import requests

from data_sources.provider_registry import ProviderResult
from data_sources.quote_sina_live import infer_prefix

URL_TEMPLATE = "http://web.ifzq.gtimg.cn/appstock/app/fqkline/get"


def fetch(raw_code: str, freq: str = "day", limit: int = 320) -> ProviderResult:
    code = str(raw_code).strip()
    prefix = infer_prefix(code)
    symbol = f"{prefix}{code}"
    params = {"param": f"{symbol},{freq},,,{limit},qfq"}
    url = f"{URL_TEMPLATE}?param={params['param']}"
    errors: List[Dict[str, Any]] = []
    body_snippet: str | None = None
    status_code: int | None = None
    data: Dict[str, Any] = {"series": []}
    try:
        resp = requests.get(
            URL_TEMPLATE,
            params=params,
            timeout=10,
            headers={"User-Agent": "Mozilla/5.0", "Referer": "http://qt.gtimg.cn"},
        )
        status_code = resp.status_code
        body_snippet = (resp.text or "")[:200]
        if resp.status_code == 200:
            js = resp.json()
            rows = _extract_rows(js, symbol, freq)
            if rows:
                data = {"series": rows}
            else:
                errors.append({"source": "kline_tencent", "error_type": "empty", "message": "no rows"})
        else:
            errors.append({"source": "kline_tencent", "error_type": "http_error", "message": f"status {resp.status_code}"})
    except Exception as exc:  # noqa: BLE001
        errors.append({"source": "kline_tencent", "error_type": "exception", "message": str(exc)})
    filled = len(data.get("series", []))
    meta = {
        "source": "kline_tencent",
        "retrieved_at": time.time(),
        "errors": errors,
        "filled_metrics": filled,
        "url": url,
        "status_code": status_code,
        "body_snippet": body_snippet,
    }
    if not filled:
        meta["filled_metrics"] = 0
    return ProviderResult(data=data, filled_metrics=meta["filled_metrics"], errors=errors, meta=meta)


def _extract_rows(js: Dict[str, Any], symbol: str, freq: str) -> List[Dict[str, Any]]:
    data = js.get("data") if isinstance(js, dict) else None
    if not data:
        return []
    sec = data.get(symbol) if isinstance(data, dict) else None
    if not sec:
        return []
    kline = sec.get(freq) if isinstance(sec, dict) else None
    if not isinstance(kline, list):
        return []
    rows: List[Dict[str, Any]] = []
    for row in kline:
        if not isinstance(row, list) or len(row) < 6:
            continue
        date, open_px, close, high, low, vol = row[:6]
        try:
            rows.append(
                {
                    "date": str(date),
                    "open": float(open_px),
                    "close": float(close),
                    "high": float(high),
                    "low": float(low),
                    "volume": float(vol),
                }
            )
        except Exception:
            continue
    rows.sort(key=lambda r: r["date"])
    return rows
