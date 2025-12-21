from __future__ import annotations
import time
from typing import Dict, Any, List
import requests
from data_sources.identity import canonical_identity
from logging_utils import build_error


def fetch(code: str, limit: int = 5) -> Dict[str, Any]:
    ident = canonical_identity(code)
    # Sina finance news feed
    url = "https://feed.sina.com.cn/api/roll/get"
    params = {
        "pageid": 153,
        "lid": 2510,
        "page": 1,
        "num": limit,
    }
    items: List[Dict[str, Any]] = []
    errors = []
    try:
        resp = requests.get(url, params=params, timeout=8)
        if resp.status_code != 200:
            errors.append(build_error("news_sina", "http_error", f"status {resp.status_code}"))
        else:
            js = resp.json()
            result = js.get("result") if isinstance(js, dict) else None
            data = result.get("data") if isinstance(result, dict) else None
            if isinstance(data, list):
                for row in data:
                    title = row.get("title")
                    if not title:
                        continue
                    # filter by code presence to increase relevance
                    if ident.raw_code not in title and ident.raw_code not in (row.get("keywords") or ""):
                        continue
                    items.append({
                        "title": title,
                        "time": row.get("ctime") or row.get("intime"),
                        "url": row.get("url"),
                        "source": row.get("media_name") or "sina",
                    })
            if not items:
                errors.append(build_error("news_sina", "empty", "no matched news"))
    except Exception as exc:  # noqa: BLE001
        errors.append(build_error("news_sina", "exception", str(exc)))
    meta = {
        "source": "news_sina",
        "retrieved_at": time.time(),
        "errors": errors,
        "filled_metrics": len(items),
        "url": url,
        "used_key": ident.raw_code,
    }
    return {"data": {"hot_events": items}, "meta": meta}
