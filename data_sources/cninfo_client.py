"""CNINFO data accessors for announcements and reports."""
from __future__ import annotations

import time
from typing import Any, Dict, List

import requests

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Referer": "https://www.cninfo.com.cn/",
}


def _build_trace(url: str, status: int | None, error: str | None, body: str = "") -> Dict[str, Any]:
    return {
        "url": url,
        "status_code": status,
        "body_snippet": body[:200],
        "error": error,
    }


def fetch_announcements(raw_code: str, page_size: int = 50) -> Dict[str, Any]:
    """Fetch announcements list for a stock."""
    url = "https://www.cninfo.com.cn/new/hisAnnouncement"
    params = {
        "stock": raw_code,
        "tabName": "fulltext",
        "pageNum": 1,
        "pageSize": page_size,
        "column": "szse",
        "plate": "",
        "searchkey": "",
        "category": "",
    }
    items: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []
    status = None
    snippet = ""
    try:
        resp = requests.get(url, headers=HEADERS, params=params, timeout=8)
        status = resp.status_code
        snippet = (resp.text or "")[:200]
        if resp.ok:
            js = resp.json()
            records = js.get("announcements") if isinstance(js, dict) else None
            if isinstance(records, list):
                for rec in records:
                    items.append(
                        {
                            "title": rec.get("announcementTitle") or rec.get("title"),
                            "pub_time": rec.get("announcementTime") or rec.get("adjunctUrl"),
                            "url": rec.get("adjunctUrl") and f"https://www.cninfo.com.cn/{rec.get('adjunctUrl')}" or "",
                            "category": rec.get("announcementType") or rec.get("columnName") or "announcement",
                        }
                    )
        else:
            errors.append({"source": "cninfo", "error_type": "http", "message": f"status {status}"})
    except Exception as exc:  # noqa: BLE001
        errors.append({"source": "cninfo", "error_type": "exception", "message": str(exc)})
    meta = {
        "source": "cninfo_announcements",
        "retrieved_at": time.time(),
        "errors": errors,
        "filled_metrics": len(items),
        "url": url,
        "status_code": status,
        "body_snippet": snippet,
    }
    if not items:
        errors.append({"source": "cninfo", "error_type": "empty", "message": "no announcements"})
    meta["errors"] = errors
    return {"data": {"announcements": items}, "meta": meta}


def fetch_reports(raw_code: str) -> Dict[str, Any]:
    """Fetch report list from CNINFO disclosure page."""
    url = "https://www.cninfo.com.cn/new/disclosure/stock"
    params = {"stockCode": raw_code, "pageNum": 1, "pageSize": 30}
    items: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []
    status = None
    snippet = ""
    try:
        resp = requests.get(url, headers=HEADERS, params=params, timeout=8)
        status = resp.status_code
        snippet = (resp.text or "")[:200]
        if resp.ok:
            js = resp.json()
            records = js.get("classifiedAnnouncements") if isinstance(js, dict) else None
            if isinstance(records, dict):
                for _, arr in records.items():
                    if not isinstance(arr, list):
                        continue
                    for rec in arr:
                        items.append(
                            {
                                "period": rec.get("adjunctTitle"),
                                "report_type": rec.get("announcementType") or rec.get("announcementTypeName"),
                                "pub_time": rec.get("announcementTime"),
                                "url": rec.get("adjunctUrl") and f"https://www.cninfo.com.cn/{rec.get('adjunctUrl')}" or "",
                            }
                        )
        else:
            errors.append({"source": "cninfo", "error_type": "http", "message": f"status {status}"})
    except Exception as exc:  # noqa: BLE001
        errors.append({"source": "cninfo", "error_type": "exception", "message": str(exc)})
    if not items:
        errors.append({"source": "cninfo", "error_type": "empty", "message": "no reports"})
    meta = {
        "source": "cninfo_reports",
        "retrieved_at": time.time(),
        "errors": errors,
        "filled_metrics": len(items),
        "url": url,
        "status_code": status,
        "body_snippet": snippet,
    }
    return {"data": {"reports": items}, "meta": meta}
