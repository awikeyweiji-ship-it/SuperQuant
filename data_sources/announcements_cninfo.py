from __future__ import annotations
import time
from typing import Dict, Any, List
import requests
from data_sources.identity import canonical_identity
from logging_utils import build_error


def fetch(code: str, limit: int = 5) -> Dict[str, Any]:
    ident = canonical_identity(code)
    url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
    params = {
        "reportName": "RPT_PUBLIC_BULLETIN",
        "filter": f"(SECURITY_CODE=\"{ident.raw_code}\")",
        "pageNumber": 1,
        "pageSize": limit,
        "sortTypes": "-1",
    }
    errors = []
    items: List[Dict[str, Any]] = []
    try:
        resp = requests.get(url, params=params, timeout=8)
        if resp.status_code != 200:
            errors.append(build_error("announcements", "http_error", f"status {resp.status_code}"))
        else:
            js = resp.json()
            records = (js.get("result") or {}).get("data") if isinstance(js, dict) else None
            if isinstance(records, list):
                for rec in records:
                    items.append({
                        "title": rec.get("BULLETIN_TITLE") or rec.get("TITLE") or rec.get("SECURITY_SHORT_NAME"),
                        "time": rec.get("BULLETIN_DATE") or rec.get("NOTICE_DATE"),
                        "url": rec.get("INFOCODE") and f"https://data.eastmoney.com/notices/detail/{ident.raw_code}/{rec.get('INFOCODE')}.html" or "",
                        "category": rec.get("COLUMNNAME") or "announcement",
                        "source": "eastmoney_bulletin",
                    })
            if not items:
                errors.append(build_error("announcements", "empty", "no announcements"))
    except Exception as exc:  # noqa: BLE001
        errors.append(build_error("announcements", "exception", str(exc)))
    meta = {
        "source": "announcements_cninfo",
        "retrieved_at": time.time(),
        "errors": errors,
        "filled_metrics": len(items),
        "url": url,
        "used_key": ident.raw_code,
    }
    return {"data": {"announcements": items}, "meta": meta}
