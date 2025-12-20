# -*- coding: utf-8 -*-
"""东财公告抓取（轻量兜底版）。"""
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


def fetch_announcements_em(code: str, limit: int = 20, timeout: int = 10) -> List[Dict[str, Any]]:
    """调用东财公告接口，返回结构化列表。"""
    sec_code = _standardize_code(code)
    url = (
        "https://datacenter-web.eastmoney.com/api/data/v1/get?"
        "reportName=RPT_PUBLIC_BULL&sortColumns=NOTICE_DATE&sortTypes=-1"
        f"&pageSize={limit}&pageNumber=1&filter=(SECUCODE=\"{sec_code}\")"
    )
    resp = requests.get(url, timeout=timeout)
    resp.raise_for_status()
    payload = resp.json()
    items = payload.get("result", {}).get("data", []) if isinstance(payload, dict) else []
    out: List[Dict[str, Any]] = []
    for it in items:
        out.append(
            {
                "title": it.get("NOTICE_TITLE") or it.get("TITLE") or "",
                "date": (it.get("NOTICE_DATE") or it.get("NOTICE_TIME") or "")[:10],
                "url": it.get("URL") or "",
                "type": it.get("NOTICE_TYPE") or it.get("COLUMN_CODE") or "公告",
            }
        )
    return out


def fetch_announcements_tencent(code: str, limit: int = 15, timeout: int = 10) -> List[Dict[str, Any]]:
    """简易腾讯财经兜底（使用快讯接口，字段有限）。"""
    std = _standardize_code(code)
    plain = std.split(".")[0]
    url = f"https://r.10jqka.com.cn/api/public/sec/getannouncement/{plain}/"  # 同花顺简易公告接口
    # 若同花顺接口不可用，则快速返回空，由上层记录错误
    resp = requests.get(url, timeout=timeout)
    if resp.status_code != 200:
        return []
    payload = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
    data = payload.get("data", []) if isinstance(payload, dict) else []
    results: List[Dict[str, Any]] = []
    for row in data[:limit]:
        results.append(
            {
                "title": row.get("title", ""),
                "date": str(row.get("publish_date", ""))[:10],
                "url": row.get("pdf_url") or row.get("url") or "",
                "type": row.get("column_name") or "公告",
            }
        )
    return results


def sample_announcements(code: str, limit: int = 10) -> List[Dict[str, Any]]:
    ts = time.strftime("%Y-%m-%d")
    return [
        {
            "title": "【样本】年度报告摘要",
            "date": ts,
            "url": "https://example.com/annual",
            "type": "公告",
        }
        for _ in range(limit)
    ]

