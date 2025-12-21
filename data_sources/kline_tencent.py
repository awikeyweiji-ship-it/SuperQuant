from __future__ import annotations
import time
from typing import Dict, Any, List
import requests
from data_sources.identity import canonical_identity
from logging_utils import build_error


FIELDS = ["date", "open", "close", "high", "low", "volume"]


def _parse_rows(raw_rows: List[List[str]]) -> List[Dict[str, Any]]:
    cleaned = []
    for row in raw_rows:
        if not isinstance(row, list) or len(row) < 6:
            continue
        date = row[0]
        try:
            open_px = float(row[1]); close_px = float(row[2]); high_px = float(row[3]); low_px = float(row[4]); vol = float(row[5])
        except Exception:
            continue
        cleaned.append({
            "date": date,
            "open": open_px,
            "close": close_px,
            "high": high_px,
            "low": low_px,
            "volume": vol,
        })
    cleaned.sort(key=lambda x: x.get("date"))
    return cleaned


def fetch(code: str, limit: int = 320) -> Dict[str, Any]:
    ident = canonical_identity(code)
    param = f"{ident.prefixed},day,,{limit},qfq"
    url = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
    params = {"param": param}
    errors = []
    rows: List[Dict[str, Any]] = []
    try:
        resp = requests.get(url, params=params, timeout=8)
        if resp.status_code != 200:
            errors.append(build_error("kline_tencent", "http_error", f"status {resp.status_code}"))
        else:
            js = resp.json()
            data = js.get("data", {}) if isinstance(js, dict) else {}
            sec = data.get(ident.prefixed)
            day = None
            if isinstance(sec, dict):
                day = sec.get("qfqday") or sec.get("day")
            if isinstance(day, list) and day:
                raw = [d if isinstance(d, list) else str(d).split(" ") for d in day]
                rows = _parse_rows(raw)
                if limit:
                    rows = rows[-limit:]
            else:
                errors.append(build_error("kline_tencent", "empty", "no kline rows"))
    except Exception as exc:  # noqa: BLE001
        errors.append(build_error("kline_tencent", "exception", str(exc)))
    meta = {
        "source": "kline_tencent",
        "retrieved_at": time.time(),
        "errors": errors,
        "filled_metrics": len(rows),
        "used_key": ident.prefixed,
        "url": url,
    }
    return {"data": {"rows": rows}, "meta": meta}
