from __future__ import annotations

import time
from typing import Any, Dict, List

import requests

from data_sources.identity import canonical_identity
from logging_utils import build_error

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Referer": "https://www.cninfo.com.cn/",
}


def _try_fetch(stock: str, limit: int) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]], int | None, str]:
    url = "https://www.cninfo.com.cn/new/hisAnnouncement/query"
    params = {
        "stock": stock,
        "tabName": "fulltext",
        "pageNum": 1,
        "pageSize": limit,
        "column": "szse",
        "plate": "",
        "searchkey": "",
        "category": "",
    }
    errors: List[Dict[str, Any]] = []
    items: List[Dict[str, Any]] = []
    status = None
    body_snippet = ""
    try:
        resp = requests.get(url, headers=HEADERS, params=params, timeout=8)
        status = resp.status_code
        body_snippet = (resp.text or "")[:200]
        if resp.ok:
            js = resp.json()
            records = js.get("announcements") if isinstance(js, dict) else None
            if isinstance(records, list):
                for rec in records:
                    items.append(
                        {
                            "title": rec.get("announcementTitle") or rec.get("title"),
                            "time": rec.get("announcementTime"),
                            "url": rec.get("adjunctUrl") and f"https://www.cninfo.com.cn/{rec.get('adjunctUrl')}" or "",
                            "category": rec.get("announcementType") or rec.get("columnName") or "announcement",
                            "source": "cninfo",
                        }
                    )
            else:
                errors.append(build_error("announcements_cninfo", "invalid", "unexpected response"))
        else:
            errors.append(build_error("announcements_cninfo", "http", f"status {status}"))
    except Exception as exc:  # noqa: BLE001
        errors.append(build_error("announcements_cninfo", "exception", str(exc)))
    return items, errors, status, body_snippet


def fetch(code: str, limit: int = 10) -> Dict[str, Any]:
    ident = canonical_identity(code)
    candidates = [ident.prefixed, ident.raw_code]
    items: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []
    status = None
    body = ""
    for stock in candidates:
        items, errors, status, body = _try_fetch(stock, limit)
        if items:
            break
    if not items and not errors:
        errors.append(build_error("announcements_cninfo", "empty", "no announcements"))
    meta = {
        "source": "announcements_cninfo",
        "retrieved_at": time.time(),
        "errors": errors,
        "filled_metrics": len(items),
        "status_code": status,
        "body_snippet": body,
        "used_code": candidates[0] if candidates else ident.raw_code,
    }
    return {"data": {"announcements": items}, "meta": meta}
