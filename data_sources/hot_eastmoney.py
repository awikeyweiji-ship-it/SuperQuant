# -*- coding: utf-8 -*-
"""热门要事/概念热榜兜底。"""
from __future__ import annotations

import time
from typing import Any, Dict, List

import requests


def fetch_hot_topics_em(limit: int = 10, timeout: int = 10) -> List[Dict[str, Any]]:
    """东财热门概念榜，返回主题及热度。"""
    url = (
        f"https://push2.eastmoney.com/api/qt/clist/get?pn=1&pz={limit}&po=1&np=1"
        "&fltt=2&invt=2&fid=f62&fs=m:90+t:2&fields=f12,f14,f62,f113,f128,f136"
    )
    resp = requests.get(url, timeout=timeout)
    resp.raise_for_status()
    payload = resp.json()
    items = payload.get("data", {}).get("diff", []) if isinstance(payload, dict) else []
    out: List[Dict[str, Any]] = []
    for it in items:
        out.append(
            {
                "theme": it.get("f14", ""),
                "heat": it.get("f62"),
                "top_stock": it.get("f128") or it.get("f12"),
                "tag": "东财概念热度",
                "title": it.get("f14", ""),
                "time": time.strftime("%Y-%m-%d"),
                "url": f"https://quote.eastmoney.com/center/boardlist.html#concept_board/{it.get('f12','')}",
                "reason": "概念热度榜",
            }
        )
    return out


def fetch_hot_topics_ak(limit: int = 10) -> List[Dict[str, Any]]:
    try:
        import akshare as ak  # type: ignore
    except Exception:
        return []
    try:
        df = ak.stock_hot_rank_em()
    except Exception:
        return []
    if df is None or df.empty:
        return []
    out: List[Dict[str, Any]] = []
    for _, row in df.head(limit).iterrows():
        out.append(
            {
                "theme": row.get("名称", ""),
                "heat": row.get("个股人气", ""),
                "top_stock": row.get("代码", ""),
                "tag": "AkShare热榜",
                "title": row.get("名称", ""),
                "time": time.strftime("%Y-%m-%d"),
                "url": "https://www.eastmoney.com/",
                "reason": "人气榜",
            }
        )
    return out


def sample_hot_topics(limit: int = 5) -> List[Dict[str, Any]]:
    ts = time.strftime("%m-%d %H:%M")
    return [
        {
            "theme": "【样本】低空经济",
            "heat": 9999,
            "top_stock": "示例股",
            "tag": f"离线样本 {ts}",
            "title": "【样本】低空经济",
            "time": time.strftime("%Y-%m-%d"),
            "url": "https://example.com/hot",
            "reason": "离线热点样本",
        }
        for _ in range(limit)
    ]

