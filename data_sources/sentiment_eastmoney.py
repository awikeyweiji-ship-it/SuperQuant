# -*- coding: utf-8 -*-
"""轻量舆情抓取（股吧为主，带兜底样本）。"""
from __future__ import annotations

import datetime
import re
import datetime
from typing import Any, Dict, List, Tuple

import requests

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Referer": "https://guba.eastmoney.com/",
}


def _strip_symbol(symbol: str) -> str:
    code = symbol.replace(".", "").lower()
    code = code.replace("sh", "").replace("sz", "")
    return code.upper()


def _build_sample_posts(symbol: str) -> List[Dict[str, Any]]:
    today = datetime.datetime.utcnow().date().isoformat()
    base_url = "https://guba.eastmoney.com"
    samples = [
        {
            "time": today,
            "summary": f"{symbol} 基本面稳健，龙头溢价仍在。",
            "url": base_url,
            "source": "sample_cache",
        },
        {
            "time": today,
            "summary": "主力博弈明显，短线情绪温度提升。",
            "url": base_url,
            "source": "sample_cache",
        },
        {
            "time": today,
            "summary": "估值回落带来性价比，机构讨论量增加。",
            "url": base_url,
            "source": "sample_cache",
        },
        {
            "time": today,
            "summary": "关注政策催化与需求弹性，等待量价共振。",
            "url": base_url,
            "source": "sample_cache",
        },
        {
            "time": today,
            "summary": "市场分歧中，上车与否取决于风险偏好。",
            "url": base_url,
            "source": "sample_cache",
        },
    ]
    return samples


def _score_from_words(words: List[str]) -> float:
    if not words:
        return 0.0
    positive = {"利好", "龙头", "涨停", "起飞", "低估", "买入", "加仓", "高景气"}
    negative = {"利空", "大跌", "退市", "暴雷", "割肉", "出货", "跳水", "回撤"}
    score = 0.0
    for w in words:
        if any(p in w for p in positive):
            score += 1.0
        if any(n in w for n in negative):
            score -= 1.0
    return max(min(score / max(len(words), 1), 1.0), -1.0)


def fetch_guba_api(symbol: str, limit: int = 20, timeout: int = 8) -> Dict[str, Any]:
    """尝试调用东财股吧接口。"""
    code = _strip_symbol(symbol)
    url = "https://gbapi.eastmoney.com/webarticle/stock"
    params = {"code": code, "pc": 1, "ps": max(limit, 10)}
    r = requests.get(url, params=params, headers=DEFAULT_HEADERS, timeout=timeout)
    r.raise_for_status()
    data = r.json()
    posts_raw = data.get("re") or data.get("data") or []
    posts: List[Dict[str, Any]] = []
    for item in posts_raw:
        title = str(item.get("title") or item.get("Title") or "").strip()
        if not title:
            continue
        ts = item.get("publish_time") or item.get("CreateTime") or ""
        url_item = item.get("url") or item.get("Url") or ""
        posts.append({"time": str(ts), "summary": title, "url": url_item, "source": "eastmoney_api"})
        if len(posts) >= limit:
            break
    words = [p.get("summary", "") for p in posts][:10]
    score = _score_from_words(words)
    return {
        "sentiment_score": round(score, 2),
        "hot_words": _top_words(words, k=10),
        "sample_posts": posts,
        "source": "eastmoney_api",
    }


def fetch_guba_html(symbol: str, limit: int = 20, timeout: int = 8) -> Dict[str, Any]:
    code = _strip_symbol(symbol)
    url = f"https://guba.eastmoney.com/list,{code}.html"
    r = requests.get(url, headers=DEFAULT_HEADERS, timeout=timeout)
    r.raise_for_status()
    html = r.text
    matches: List[Tuple[str, str]] = re.findall(r'href="(/news,\d+,\d+\.html)"[^>]*title="([^"]+)"', html)
    posts: List[Dict[str, Any]] = []
    for href, title in matches:
        if len(title.strip()) < 4:
            continue
        posts.append(
            {
                "time": "",
                "summary": title.strip(),
                "url": f"https://guba.eastmoney.com{href}",
                "source": "eastmoney_html",
            }
        )
        if len(posts) >= limit:
            break
    words = [p["summary"] for p in posts][:10]
    return {
        "sentiment_score": round(_score_from_words(words), 2),
        "hot_words": _top_words(words, k=10),
        "sample_posts": posts,
        "source": "eastmoney_html",
    }


def fetch_xueqiu_search(symbol: str, limit: int = 15, timeout: int = 8) -> Dict[str, Any]:
    """简单雪球搜索兜底，若受限则由上层处理错误。"""
    code = _strip_symbol(symbol)
    url = "https://xueqiu.com/query/v1/search/status.json"
    params = {"q": code, "page": 1, "count": limit}
    r = requests.get(url, params=params, headers=DEFAULT_HEADERS, timeout=timeout)
    r.raise_for_status()
    data = r.json()
    posts_raw = data.get("list") or []
    posts: List[Dict[str, Any]] = []
    for item in posts_raw:
        title = str(item.get("title") or item.get("text") or "").strip()
        if not title:
            continue
        ts = item.get("created_at") or item.get("created") or ""
        posts.append({"time": str(ts), "summary": title, "url": str(item.get("target")) or "", "source": "xueqiu"})
        if len(posts) >= limit:
            break
    words = [p.get("summary", "") for p in posts][:10]
    return {
        "sentiment_score": round(_score_from_words(words), 2),
        "hot_words": _top_words(words, k=10),
        "sample_posts": posts,
        "source": "xueqiu",
    }


def sample_sentiment(symbol: str) -> Dict[str, Any]:
    posts = _build_sample_posts(symbol)
    words = _top_words([p["summary"] for p in posts], k=10)
    return {
        "sentiment_score": 0.15,
        "hot_words": words,
        "sample_posts": posts,
        "source": "sample_cache",
        "note": "启用离线舆情样本，数据可能过期",
    }


def _top_words(texts: List[str], k: int = 10) -> List[str]:
    freq: Dict[str, int] = {}
    for t in texts:
        for word in re.findall(r"[\u4e00-\u9fa5A-Za-z0-9]{2,}", t):
            freq[word] = freq.get(word, 0) + 1
    return [w for w, _ in sorted(freq.items(), key=lambda kv: kv[1], reverse=True)[:k]]

