"""Hot topic news provider using Eastmoney concept heat."""
from __future__ import annotations

import time
from typing import Any, Dict, List

from data_sources.hot_eastmoney import fetch_hot_topics_em


def fetch(symbol: str, limit: int = 15, **_: Any) -> Dict[str, Any]:
    errors: List[Dict[str, str]] = []
    items: List[Dict[str, Any]] = []
    try:
        payload = fetch_hot_topics_em(limit=limit)
        rows = payload.get("items", []) if isinstance(payload, dict) else payload
        errors.extend(payload.get("errors", []) if isinstance(payload, dict) else [])
        for row in rows or []:
            url = row.get("url") or ""
            ts = row.get("time") or time.strftime("%Y-%m-%d")
            if not url or "example.com" in url:
                errors.append({"source": "news_hot_eastmoney", "error_type": "invalid", "message": "missing url"})
                continue
            items.append(
                {
                    "title": row.get("title") or row.get("theme") or "",
                    "time": ts,
                    "source": row.get("tag") or "hot_concept",
                    "url": url,
                    "summary": row.get("reason") or row.get("title") or "概念热度",
                }
            )
    except Exception as exc:  # noqa: BLE001
        errors.append({"source": "news_hot_eastmoney", "error_type": "exception", "message": str(exc)})

    if not items and not errors:
        errors.append({"source": "news_hot_eastmoney", "error_type": "empty", "message": "no hot events"})

    meta = {
        "source": "news_hot_eastmoney",
        "retrieved_at": time.time(),
        "errors": errors,
        "errors_count": len(errors),
        "filled_metrics": len(items),
        "fallback_used": False,
    }
    return {"data": {"hot_events": items}, "meta": meta}
