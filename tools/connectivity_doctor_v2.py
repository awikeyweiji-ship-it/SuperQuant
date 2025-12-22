"""Lightweight connectivity probe for key data providers.

This module intentionally avoids any proxy configuration and performs
bounded retries with short timeouts so it can run quickly on constrained
hosts. The ``probe_endpoints`` function returns a dictionary keyed by
provider name with basic reachability metadata.
"""
from __future__ import annotations

import json
import time
from typing import Dict, Any

import requests

DEFAULT_TIMEOUT = 6
DEFAULT_RETRIES = 2


def _probe(name: str, url: str, timeout: float = DEFAULT_TIMEOUT, retries: int = DEFAULT_RETRIES) -> Dict[str, Any]:
    last_error: str | None = None
    status: int | None = None
    text_snippet = ""
    for attempt in range(max(1, retries + 1)):
        try:
            resp = requests.get(url, timeout=timeout)
            status = resp.status_code
            text_snippet = (resp.text or "")[:200]
            ok = resp.ok and bool(text_snippet)
            return {
                "url": url,
                "status": status,
                "ok": ok,
                "error": None if ok else f"empty or status {status}",
                "body_snippet": text_snippet,
                "attempts": attempt + 1,
            }
        except Exception as exc:  # noqa: BLE001
            last_error = str(exc)
            time.sleep(0.3 * (attempt + 1))
    return {
        "url": url,
        "status": status,
        "ok": False,
        "error": last_error or "unknown", 
        "body_snippet": text_snippet,
        "attempts": retries + 1,
    }


def probe_endpoints() -> Dict[str, Dict[str, Any]]:
    """Probe a curated set of endpoints used by the app.

    The returned mapping is JSON-serializable and safe to log.
    """
    probes = {
        "cninfo_ann": "https://www.cninfo.com.cn/new/hisAnnouncement?stock=600519&column=szse&category=category_ndbg%2Ccategory_bndbg%2Ccategory_yjdbg%2Ccategory_sjdbg%2Ccategory_scgkfx&searchkey=&plate=&tabName=fulltext&limit=5&pageNum=1",
        "cninfo_report": "https://www.cninfo.com.cn/new/disclosure/stock?stockCode=600519&orgId=gssh0600519",
        "tencent_kline": "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=sh600519,day,,,50,qfq",
        "sina_quote": "https://hq.sinajs.cn/list=sh600519",
    }
    results: Dict[str, Dict[str, Any]] = {}
    for name, url in probes.items():
        results[name] = _probe(name, url)
    return results


if __name__ == "__main__":
    print(json.dumps(probe_endpoints(), ensure_ascii=False, indent=2))
