"""Eastmoney announcements provider with schema normalization."""
from __future__ import annotations

import time
from typing import Any, Dict, List

from data_sources.announcement_eastmoney import fetch_announcements_em


REQUIRED_FIELDS = ["title", "time", "source", "url", "summary"]


def _filter_items(items: List[Dict[str, Any]], meta_errors: List[Dict[str, str]]) -> List[Dict[str, Any]]:
    cleaned: List[Dict[str, Any]] = []
    for row in items:
        title = row.get("title") or row.get("NOTICE_TITLE") or ""
        ts = (row.get("date") or row.get("time") or "").strip()
        url = (row.get("url") or "").strip()
        if not ts or not url or "example.com" in url:
            meta_errors.append({"source": "news_announcements_eastmoney", "error_type": "invalid", "message": "missing time/url"})
            continue
        cleaned.append(
            {
                "title": title,
                "time": ts,
                "source": row.get("type") or "eastmoney_announcement",
                "url": url,
                "summary": row.get("type") or title,
            }
        )
    return cleaned


def fetch(symbol: str, limit: int = 20, **_: Any) -> Dict[str, Any]:
    meta_errors: List[Dict[str, str]] = []
    items: List[Dict[str, Any]] = []
    try:
        raw_items = fetch_announcements_em(symbol, limit=limit)
        items = _filter_items(raw_items, meta_errors)
    except Exception as exc:  # noqa: BLE001
        meta_errors.append({"source": "news_announcements_eastmoney", "error_type": "exception", "message": str(exc)})

    meta = {
        "source": "news_announcements_eastmoney",
        "retrieved_at": time.time(),
        "errors": meta_errors,
        "filled_metrics": len(items),
        "fallback_used": False,
    }
    return {"data": {"announcements": items}, "meta": meta}
