from __future__ import annotations

import re
import time
from typing import Any, Dict, List

import requests
from bs4 import BeautifulSoup

from data_sources.provider_registry import ProviderResult
from data_sources.quote_sina_live import infer_prefix

NEWS_URL = "http://vip.stock.finance.sina.com.cn/corp/view/vCB_AllNewsStock.php"


def fetch(raw_code: str, limit: int = 10) -> ProviderResult:
    code = str(raw_code).strip()
    prefix = infer_prefix(code)
    params = {"symbol": f"{prefix}{code}", "Page": 1}
    errors: List[Dict[str, Any]] = []
    items: List[Dict[str, Any]] = []
    status_code: int | None = None
    body_snippet: str | None = None
    url = f"{NEWS_URL}?symbol={params['symbol']}&Page=1"
    try:
        resp = requests.get(
            NEWS_URL,
            params=params,
            timeout=10,
            headers={"User-Agent": "Mozilla/5.0", "Referer": "http://finance.sina.com.cn"},
        )
        status_code = resp.status_code
        body_snippet = (resp.text or "")[:200]
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "html.parser")
            for row in soup.select("div.datelist ul li"):
                a = row.find("a")
                if not a or not a.text:
                    continue
                title = a.text.strip()
                href = a.get("href")
                time_text = row.text.strip()
                # extract time with regex like (2025-01-01)
                match = re.search(r"(\d{4}-\d{2}-\d{2} .*?)", time_text)
                ts = match.group(1) if match else None
                items.append({"title": title, "url": href, "time": ts, "source": "sina"})
                if len(items) >= limit:
                    break
            if not items:
                errors.append({"source": "news_sina_stock", "error_type": "empty", "message": "no news rows"})
        else:
            errors.append({"source": "news_sina_stock", "error_type": "http_error", "message": f"status {resp.status_code}"})
    except Exception as exc:  # noqa: BLE001
        errors.append({"source": "news_sina_stock", "error_type": "exception", "message": str(exc)})
    meta = {
        "source": "news_sina_stock",
        "retrieved_at": time.time(),
        "errors": errors,
        "filled_metrics": len(items),
        "url": url,
        "status_code": status_code,
        "body_snippet": body_snippet,
    }
    return ProviderResult(data={"hot_events": items}, filled_metrics=len(items), errors=errors, meta=meta)
