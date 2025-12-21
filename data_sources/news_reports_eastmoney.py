"""Research report news provider from Eastmoney."""
from __future__ import annotations

import time
from typing import Any, Dict, List

from data_sources.report_eastmoney import fetch_research_reports_em, fetch_research_reports_alt


def _collect_reports(fetcher, symbol: str, limit: int, errors: List[Dict[str, str]]) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    try:
        payload = fetcher(symbol, limit=limit)
        rows = payload.get("items", []) if isinstance(payload, dict) else payload
        errors.extend(payload.get("errors", []) if isinstance(payload, dict) else [])
        for row in rows or []:
            title = row.get("title") or ""
            ts = (row.get("date") or row.get("time") or "").strip()
            url = (row.get("url") or "").strip()
            if not ts or not url or "example.com" in url:
                errors.append({"source": "news_reports_eastmoney", "error_type": "invalid", "message": "missing time/url"})
                continue
            items.append(
                {
                    "title": title,
                    "time": ts,
                    "source": row.get("org") or "eastmoney_report",
                    "url": url,
                    "summary": row.get("rating") or title or "研报摘要",
                }
            )
    except Exception as exc:  # noqa: BLE001
        errors.append({"source": "news_reports_eastmoney", "error_type": "exception", "message": str(exc)})
    return items


def fetch(symbol: str, limit: int = 20, **_: Any) -> Dict[str, Any]:
    errors: List[Dict[str, str]] = []
    items = _collect_reports(fetch_research_reports_em, symbol, limit, errors)
    if not items:
        items = _collect_reports(fetch_research_reports_alt, symbol, limit, errors)
    if not items and not errors:
        errors.append({"source": "news_reports_eastmoney", "error_type": "empty", "message": "no reports"})
    meta = {
        "source": "news_reports_eastmoney",
        "retrieved_at": time.time(),
        "errors": errors,
        "errors_count": len(errors),
        "filled_metrics": len(items),
        "fallback_used": False,
    }
    return {"data": {"reports": items}, "meta": meta}
