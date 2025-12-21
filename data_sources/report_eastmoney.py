# -*- coding: utf-8 -*-
"""东财研报抓取（轻量兜底版）。"""
from __future__ import annotations

import time
from typing import Any, Dict, List

import requests


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


def fetch_research_reports_em(code: str, limit: int = 20, timeout: int = 10) -> List[Dict[str, Any]]:
    """调用东财研报列表。"""
    std = _standardize_code(code)
    plain = std.split(".")[0]
    url = (
        "https://reportapi.eastmoney.com/report/list?"
        f"code={plain}&pageSize={limit}&pageNo=1&industryCode="
    )
    resp = requests.get(url, timeout=timeout)
    resp.raise_for_status()
    payload = resp.json()
    items = payload.get("data", []) if isinstance(payload, dict) else []
    out: List[Dict[str, Any]] = []
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
    return out


def fetch_research_reports_alt(code: str, limit: int = 15, timeout: int = 10) -> List[Dict[str, Any]]:
    """同花顺/备选接口兜底。"""
    std = _standardize_code(code)
    plain = std.split(".")[0]
    url = f"https://emdata.eastmoney.com/stock/research/{plain}.json"
    resp = requests.get(url, timeout=timeout)
    if resp.status_code != 200:
        return []
    payload = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
    data = payload.get("data", []) if isinstance(payload, dict) else []
    out: List[Dict[str, Any]] = []
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
    return out


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

