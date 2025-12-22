from __future__ import annotations

import time
from typing import Any, Dict, List

import requests

from data_sources.identity import canonical_identity
from logging_utils import build_error

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Referer": "https://data.eastmoney.com/",
}


def _request_json(url: str, timeout: int = 8, retries: int = 2) -> Dict[str, Any]:
    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=timeout)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt < retries:
                time.sleep(0.6 * (attempt + 1))
    return {"_error": str(last_exc) if last_exc else "unknown error"}


def fetch(code: str, limit: int = 20) -> Dict[str, Any]:
    ident = canonical_identity(code)
    secucode = ident.symbol
    url = (
        "https://datacenter-web.eastmoney.com/api/data/v1/get?"
        "reportName=RPT_PUBLIC_BULL&sortColumns=NOTICE_DATE&sortTypes=-1"
        f"&pageSize={limit}&pageNumber=1&columns=SECURITY_CODE,SECURITY_NAME_ABBR,NOTICE_DATE,NOTICE_TITLE,URL&filter=(SECUCODE=\"{secucode}\")"
    )
    payload = _request_json(url)
    items = payload.get("result", {}).get("data", []) if isinstance(payload, dict) else []
    announcements: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []

    if isinstance(payload, dict) and payload.get("_error"):
        errors.append(build_error("announcements_eastmoney", "exception", str(payload.get("_error"))))

    if not isinstance(items, list):
        errors.append(build_error("announcements_eastmoney", "invalid", "unexpected payload"))
        items = []

    for it in items:
        if not isinstance(it, dict):
            continue
        announcements.append(
            {
                "title": it.get("NOTICE_TITLE") or it.get("TITLE") or "",
                "publish_time": (it.get("NOTICE_DATE") or "")[:19],
                "source_url": it.get("URL") or "",
                "code": ident.raw_code,
                "provider": "eastmoney",
            }
        )

    if not announcements:
        errors.append(build_error("announcements_eastmoney", "empty", "no announcements returned"))

    meta = {
        "source": "announcements_eastmoney",
        "retrieved_at": time.time(),
        "errors": errors,
        "filled_metrics": len(announcements),
        "url": url,
        "used_code": secucode,
    }
    return {"data": {"announcements": announcements}, "meta": meta}
