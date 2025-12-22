from __future__ import annotations

import time
from typing import Any, Dict, List, Sequence

import requests

from data_sources.provider_registry import ProviderResult
from data_sources.quote_sina_live import infer_prefix

URL_TEMPLATE = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"


def _parse_row(row: Sequence[Any]) -> Dict[str, Any] | None:
    try:
        if not isinstance(row, (list, tuple)):
            if isinstance(row, str):
                parts = row.replace(",", " ").split()
                row = parts
            else:
                return None
        if len(row) < 6:
            return None
        date, open_px, close, high, low, vol = row[:6]
        return {
            "date": str(date),
            "open": float(open_px),
            "close": float(close),
            "high": float(high),
            "low": float(low),
            "volume": float(vol),
        }
    except Exception:
        return None


def _extract_rows(
    js: Dict[str, Any], symbol: str, plain: str, freq: str, limit: int
) -> tuple[List[Dict[str, Any]], str | None]:
    data = js.get("data") if isinstance(js, dict) else None
    if not isinstance(data, dict):
        return [], None

    candidates = [symbol, symbol.lower(), plain, f"sh{plain}", f"sz{plain}", f"bj{plain}"]
    series: List[Dict[str, Any]] = []
    used_key = None
    for key in candidates:
        sec = data.get(key)
        if not isinstance(sec, dict):
            continue
        used_key = key
        for fld in ["qfqday", "day", "qfq", "daily", freq]:
            kline = sec.get(fld)
            if isinstance(kline, list) and kline:
                for row in kline:
                    parsed = _parse_row(row)
                    if parsed:
                        series.append(parsed)
                break
        if series:
            break

    if not series:
        return [], used_key
    # ensure deterministic ordering and dedupe
    dedup = {(r["date"], r["open"], r["close"]): r for r in series}
    rows = list(dedup.values())
    rows.sort(key=lambda r: r["date"])
    if limit:
        rows = rows[-limit:]
    return rows, used_key


def fetch(raw_code: str, freq: str = "day", limit: int = 320) -> ProviderResult:
    code = str(raw_code).strip()
    prefix = infer_prefix(code)
    plain = code.split(".")[0]
    symbol = f"{prefix}{plain}"
    params = {"param": f"{symbol},{freq},,,{limit},qfq"}
    url = f"{URL_TEMPLATE}?param={params['param']}"
    errors: List[Dict[str, Any]] = []
    body_snippet: str | None = None
    status_code: int | None = None
    used_key: str | None = None
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
        if resp.status_code != 200:
            errors.append({"source": "kline_tencent", "error_type": "http_error", "message": f"status {resp.status_code}"})
        else:
            try:
                js = resp.json()
            except Exception:
                errors.append({"source": "kline_tencent", "error_type": "blocked_html", "message": "non-json body"})
                js = {}
            rows, used_key = _extract_rows(js, symbol, plain, freq, limit)
            if rows:
                data = {"series": rows}
            else:
                errors.append({"source": "kline_tencent", "error_type": "empty", "message": "no rows"})
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
        "used_key": used_key or symbol,
    }
    if not filled:
        meta["filled_metrics"] = 0
    return ProviderResult(data=data, filled_metrics=meta["filled_metrics"], errors=errors, meta=meta)
