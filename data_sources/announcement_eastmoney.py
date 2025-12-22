# -*- coding: utf-8 -*-
"""东财公告抓取（轻量兜底版）。"""
from __future__ import annotations

import time
from typing import Any, Dict, List

import requests

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Referer": "https://data.eastmoney.com/",
}


def _request_json(url: str, timeout: int = 10, retries: int = 1) -> Dict[str, Any]:
    """Best-effort JSON fetch that never raises.

    When all retries fail, returns a payload carrying the error so callers can
    surface it in provider traces.
    """

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


def fetch_announcements_em(code: str, limit: int = 20, timeout: int = 10) -> Dict[str, Any]:
    """调用东财公告接口，返回结构化列表及错误信息。"""

    sec_code = _standardize_code(code)
    url = (
        "https://datacenter-web.eastmoney.com/api/data/v1/get?"
        "reportName=RPT_PUBLIC_BULL&sortColumns=NOTICE_DATE&sortTypes=-1"
        f"&pageSize={limit}&pageNumber=1&filter=(SECUCODE=\"{sec_code}\")"
    )
    payload = _request_json(url, timeout=timeout)
    items = payload.get("result", {}).get("data", []) if isinstance(payload, dict) else []
    out: List[Dict[str, Any]] = []
    errors: List[Dict[str, str]] = []
    if isinstance(payload, dict) and payload.get("_error"):
        errors.append({"source": "announcement_eastmoney", "error_type": "exception", "message": str(payload.get("_error"))})
    if not isinstance(items, list):
        errors.append({"source": "announcement_eastmoney", "error_type": "invalid", "message": "unexpected payload"})
        items = []
    for it in items:
        out.append(
            {
                "title": it.get("NOTICE_TITLE") or it.get("TITLE") or "",
                "date": (it.get("NOTICE_DATE") or it.get("NOTICE_TIME") or "")[:10],
                "url": it.get("URL") or "",
                "type": it.get("NOTICE_TYPE") or it.get("COLUMN_CODE") or "公告",
            }
        )
    if not out and not errors:
        errors.append({"source": "announcement_eastmoney", "error_type": "empty", "message": "no announcements"})
    meta = {
        "source": "announcement_eastmoney",
        "retrieved_at": time.time(),
        "errors": errors,
        "filled_metrics": len(out),
        "url": url,
    }
    return {"data": {"announcements": out}, "meta": meta, "items": out, "errors": errors}


def fetch_announcements_tencent(code: str, limit: int = 15, timeout: int = 10) -> Dict[str, Any]:
    """简易腾讯财经兜底（使用快讯接口，字段有限）。"""
    std = _standardize_code(code)
    plain = std.split(".")[0]
    url = f"https://r.10jqka.com.cn/api/public/sec/getannouncement/{plain}/"  # 同花顺简易公告接口
    errors: List[Dict[str, Any]] = []
    anns: List[Dict[str, Any]] = []
    status_code: int | None = None
    body_snippet: str | None = None
    try:
        resp = requests.get(
            url,
            timeout=timeout,
            headers={"User-Agent": "Mozilla/5.0", "Referer": "https://r.10jqka.com.cn"},
        )
        status_code = resp.status_code
        body_snippet = (resp.text or "")[:200]
        if resp.status_code != 200:
            errors.append({"source": "ann_em_tx", "error_type": "http", "message": f"status {resp.status_code}"})
        elif "<html" in body_snippet.lower():
            errors.append({"source": "ann_em_tx", "error_type": "blocked_html", "message": "non-json body"})
        else:
            payload = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
            data = payload.get("data", []) if isinstance(payload, dict) else []
            if not isinstance(data, list):
                errors.append({"source": "ann_em_tx", "error_type": "invalid", "message": "unexpected payload"})
                data = []
            for row in data[:limit]:
                anns.append(
                    {
                        "title": row.get("title", ""),
                        "date": str(row.get("publish_date", ""))[:10],
                        "url": row.get("pdf_url") or row.get("url") or "",
                        "type": row.get("column_name") or "公告",
                        "source": "10jqka",
                    }
                )
    except Exception as exc:  # noqa: BLE001
        errors.append({"source": "ann_em_tx", "error_type": "exception", "message": str(exc)})

    if not anns and not errors:
        errors.append({"source": "ann_em_tx", "error_type": "empty", "message": "no announcements"})

    meta = {
        "source": "ann_em_tx",
        "retrieved_at": time.time(),
        "errors": errors,
        "filled_metrics": len(anns),
        "url": url,
        "status_code": status_code,
        "body_snippet": body_snippet,
    }
    return {"data": {"announcements": anns}, "meta": meta}


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

