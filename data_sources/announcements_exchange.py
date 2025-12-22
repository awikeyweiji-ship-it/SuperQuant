from __future__ import annotations

import time
from typing import Any, Dict, List, Tuple

import time
import requests

from data_sources.identity import canonical_identity
from logging_utils import build_error


def _safe_get(url: str, headers: Dict[str, str], params: Dict[str, Any], timeout: int = 8, retries: int = 2) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], str | None]:
    errors: List[Dict[str, Any]] = []
    body_snippet: str | None = None
    for attempt in range(retries + 1):
        try:
            resp = requests.get(url, headers=headers, params=params, timeout=timeout)
            body_snippet = resp.text[:200]
            if "<html" in (body_snippet or "").lower():
                raise RuntimeError("blocked_html")
            resp.raise_for_status()
            try:
                data = resp.json()
            except Exception:
                raise RuntimeError("non_json")
            return (data if isinstance(data, list) else data.get("data", []) if isinstance(data, dict) else []), errors, body_snippet
        except Exception as exc:  # noqa: BLE001
            if attempt >= retries:
                errors.append(build_error("announcements_exchange", "exception", str(exc)))
            else:
                time.sleep(0.6 * (attempt + 1))
    return [], errors, body_snippet


def _parse_sse(raw: List[Dict[str, Any]], code: str) -> List[Dict[str, Any]]:
    anns: List[Dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        title = item.get("bulletin_Title") or item.get("title") or ""
        pub = item.get("publishTime") or item.get("bulletin_Time") or item.get("notice_date") or ""
        url = item.get("docUrl") or item.get("url") or ""
        if url and url.startswith("/"):
            url = f"https://www.sse.com.cn{url}"
        if url and not url.startswith("http"):
            url = f"https://www.sse.com.cn/disclosure/{url}"
        anns.append({"title": title, "publish_time": str(pub)[:19], "source_url": url, "source": "sse", "code": code})
    return anns


def _parse_szse(raw: List[Dict[str, Any]], code: str) -> List[Dict[str, Any]]:
    anns: List[Dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        title = item.get("title") or item.get("noticeTitle") or ""
        pub = item.get("publishTime") or item.get("noticeDate") or ""
        url = item.get("docUrl") or item.get("attachPath") or ""
        if url and url.startswith("/"):
            url = f"https://www.szse.cn{url}"
        if url and not url.startswith("http"):
            url = f"https://www.szse.cn/disclosure/{url}"
        anns.append({"title": title, "publish_time": str(pub)[:19], "source_url": url, "source": "szse", "code": code})
    return anns


def fetch(code: str, limit: int = 20) -> Dict[str, Any]:
    ident = canonical_identity(code)
    raw_code = ident.raw_code
    is_sh = ident.exchange == "SH"
    errors: List[Dict[str, Any]] = []
    anns: List[Dict[str, Any]] = []
    url = ""
    body_snippet: str | None = None

    if is_sh:
        url = "https://query.sse.com.cn/disclosure/listedinfo/announcement/query"
        params = {
            "pageSize": limit,
            "pageNum": 1,
            "reportType": "ALL",
            "securityType": "0101,0102",
            "companyCode": raw_code,
            "isNew": 1,
        }
        headers = {
            "Referer": "https://www.sse.com.cn/disclosure/listedinfo/announcement/",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept": "application/json,text/plain,*/*",
        }
        data, err_list, body_snippet = _safe_get(url, headers, params)
        errors.extend(err_list)
        items = []
        if isinstance(data, dict):
            items = data.get("list") or data.get("data") or []
        elif isinstance(data, list):
            items = data
        anns = _parse_sse(items, raw_code)
    else:
        url = "https://www.szse.cn/api/disc/announcement/annList"
        params = {
            "pageIndex": 1,
            "pageSize": limit,
            "channelCode": "listedNotice_disc",
            "stock": raw_code,
        }
        headers = {
            "Referer": "https://www.szse.cn/disclosure/index.html",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept": "application/json,text/plain,*/*",
        }
        data, err_list, body_snippet = _safe_get(url, headers, params)
        errors.extend(err_list)
        items = []
        if isinstance(data, dict):
            items = data.get("data") or []
        elif isinstance(data, list):
            items = data
        anns = _parse_szse(items, raw_code)

    if not anns:
        errors.append(build_error("announcements_exchange", "empty", "no announcements returned"))

    meta = {
        "source": "announcements_exchange",
        "retrieved_at": time.time(),
        "errors": errors,
        "filled_metrics": len(anns),
        "url": url,
        "used_code": ident.raw_code,
        "body_snippet": body_snippet,
    }
    return {"data": {"announcements": anns}, "meta": meta}

