# -*- coding: utf-8 -*-
"""东财研报抓取（轻量兜底版）。"""
from __future__ import annotations

import time
from typing import Any, Dict, List

import requests

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Referer": "https://data.eastmoney.com/",
}


def _request_json(url: str, timeout: int = 10, retries: int = 1) -> Dict[str, Any]:
    """Best-effort JSON fetcher that never raises."""

    last_exc: Exception | None = None
    for attempt in range(max(1, retries + 1)):
        try:
            resp = requests.get(url, timeout=timeout, headers=HEADERS)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt < retries:
                time.sleep(0.3 * (attempt + 1))
    return {"_error": str(last_exc) if last_exc else "unknown error"}


def _standardize_code(code: str) -> str:
    code = str(code).strip().upper()
    if code.endswith((".SH", ".SZ", ".BJ")):
        return code
    code = code.replace("SH", "").replace("SZ", "").replace("BJ", "")
    if code.isdigit() and len(code) < 6:
        code = code.zfill(6)
    market = "SZ"
    if code.startswith("6"):
        market = "SH"
    elif code.startswith(("8", "4")):
        market = "BJ"
    return f"{code}.{market}"


def fetch_research_reports_em(code: str, limit: int = 20, timeout: int = 10) -> Dict[str, Any]:
    """调用东财研报列表并返回错误信息。"""

    std = _standardize_code(code)
    plain = std.split(".")[0]
    url = (
        "https://reportapi.eastmoney.com/report/list?"
        f"code={plain}&pageSize={limit}&pageNo=1&industryCode="
    )
    payload = _request_json(url, timeout=timeout)
    items = payload.get("data", []) if isinstance(payload, dict) else []
    errors: List[Dict[str, str]] = []
    out: List[Dict[str, Any]] = []
    if isinstance(payload, dict) and payload.get("_error"):
        errors.append({"source": "report_eastmoney", "error_type": "exception", "message": str(payload.get("_error"))})
    if not isinstance(items, list):
        errors.append({"source": "report_eastmoney", "error_type": "invalid", "message": "unexpected payload"})
        items = []
    for it in items:
        out.append(
            {
                "title": it.get("title") or "",
                "org": it.get("orgSName") or it.get("orgName") or "",
                "date": (it.get("publishDate") or it.get("publishTime") or "")[:10],
                "rating": it.get("emRatingName") or it.get("ratingName") or it.get("keyword") or "",
                "url": f"https://data.eastmoney.com/report/{it.get('infoCode','')}.html",
            }
        )
    if not out and not errors:
        errors.append({"source": "report_eastmoney", "error_type": "empty", "message": "no reports"})
    return {"items": out, "errors": errors}


def fetch_research_reports_alt(code: str, limit: int = 15, timeout: int = 10) -> Dict[str, Any]:
    """同花顺/备选接口兜底，返回结果及错误。"""

    std = _standardize_code(code)
    plain = std.split(".")[0]
    url = f"https://emdata.eastmoney.com/stock/research/{plain}.json"
    payload = _request_json(url, timeout=timeout)
    data = payload.get("data", []) if isinstance(payload, dict) else []
    errors: List[Dict[str, str]] = []
    out: List[Dict[str, Any]] = []
    if isinstance(payload, dict) and payload.get("_error"):
        errors.append({"source": "report_eastmoney_alt", "error_type": "exception", "message": str(payload.get("_error"))})
    if not isinstance(data, list):
        errors.append({"source": "report_eastmoney_alt", "error_type": "invalid", "message": "unexpected payload"})
        data = []
    for row in data[:limit]:
        out.append(
            {
                "title": row.get("title", ""),
                "org": row.get("org", ""),
                "date": str(row.get("publish_date", ""))[:10],
                "rating": row.get("rating", ""),
                "url": row.get("url", ""),
            }
        )
    if not out and not errors:
        errors.append({"source": "report_eastmoney_alt", "error_type": "empty", "message": "no reports"})
    return {"items": out, "errors": errors}


def sample_reports(code: str, limit: int = 10) -> List[Dict[str, Any]]:
    ts = time.strftime("%Y-%m-%d")
    return [
        {
            "title": "【样本】行业景气度跟踪",
            "org": "示例券商",
            "date": ts,
            "rating": "买入",
            "url": "https://example.com/report",
        }
        for _ in range(limit)
    ]

