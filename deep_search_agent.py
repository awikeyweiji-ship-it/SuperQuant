# -*- coding: utf-8 -*-
"""
deep_search_agent.py
====================
全网哨兵（Deep Search Agent）

目标：
- 汇聚宏观/政策/市场定调的“证据链”
- 量化政策强度与持续性（PolicyEngine）
- 输出给 Radar / SlowFactorEngine / Fuser 使用的宏观报告

设计原则：
- 可用优先：没有 Tavily Key 也不会崩，返回中性结构
- 证据链：每条证据包含来源/时间/标题/摘要/量化结果
"""

from __future__ import annotations

import datetime as _dt
import json
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

try:
    from policy_engine import PolicyEngine
except Exception:
    PolicyEngine = None  # type: ignore

try:
    import requests
except Exception:
    requests = None  # type: ignore


def _now_iso() -> str:
    return _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _safe_str(x: Any) -> str:
    return "" if x is None else str(x)


def _dedup(seq: List[str]) -> List[str]:
    seen = set()
    out = []
    for s in seq:
        s = (s or "").strip()
        if not s:
            continue
        if s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


class DeepSearchAgent:
    """
    - deepseek_key：用于更深度的AI总结（可选）
    - tavily_key：用于并行搜索（可选，但强烈建议）
    """
    def __init__(self, deepseek_key: str = "", tavily_key: str = ""):
        self.deepseek_key = deepseek_key or ""
        self.tavily_key = tavily_key or ""
        self.policy = PolicyEngine() if PolicyEngine else None

    # ---------------------------
    # Tavily Search (optional)
    # ---------------------------
    def _tavily_search(self, query: str, k: int = 6) -> List[Dict[str, Any]]:
        if not self.tavily_key or not requests:
            return []
        try:
            url = "https://api.tavily.com/search"
            payload = {
                "api_key": self.tavily_key,
                "query": query,
                "search_depth": "advanced",
                "max_results": int(k),
                "include_answer": False,
                "include_raw_content": True,
            }
            r = requests.post(url, json=payload, timeout=20)
            if r.status_code != 200:
                return []
            data = r.json() or {}
            res = data.get("results") or []
            out = []
            for it in res:
                out.append({
                    "title": it.get("title") or "",
                    "url": it.get("url") or "",
                    "content": it.get("content") or "",
                    "raw_content": it.get("raw_content") or it.get("content") or "",
                    "published_date": it.get("published_date") or "",
                })
            return out
        except Exception:
            return []

    # ---------------------------
    # Evidence Capture
    # ---------------------------
    def capture_evidence(self, queries: List[str], kind: str = "macro") -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        for q in queries:
            for it in self._tavily_search(q, k=6):
                title = _safe_str(it.get("title"))
                url = _safe_str(it.get("url"))
                content = _safe_str(it.get("raw_content") or it.get("content"))
                content = content[:3000]  # avoid huge payload
                qres = {}
                if self.policy:
                    # backward-compatible API:
                    try:
                        qres = self.policy.quantify_policy(title + "\n" + content)
                    except Exception:
                        try:
                            qres = self.policy.score_evidence_item(title, content)
                        except Exception:
                            qres = {}
                items.append({
                    "kind": kind,
                    "query": q,
                    "title": title,
                    "url": url,
                    "content": content,
                    "captured_at": _now_iso(),
                    "policy_quant": qres,
                })
        return items

    # ---------------------------
    # Macro Situation
    # ---------------------------
    def analyze_macro_situation(self) -> Dict[str, Any]:
        """
        输出结构：
        - core_logic: 可直接展示的宏观定调摘要
        - primary_sectors: 本轮主线行业（用于慢变量加成）
        - confidence: 0~1
        - defcon_level: DEFENSE / OFFENSE / RETREAT
        - evidence: 证据链
        """
        # Queries: deliberately broad; Tavily will do parallel
        queries = [
            "中国 宏观 政策 定调 中央经济工作会议 产业政策 2025",
            "A股 市场 定调 货币政策 财政政策 信用 扩张 收缩",
            "产业趋势 新质生产力 低空经济 人工智能 算力 半导体 国产替代",
            "外部环境 美联储 利率 美元指数 油价 地缘风险 对A股影响",
        ]

        evidence = self.capture_evidence(queries, kind="macro")

        # Aggregate simple signals
        strength = 0.5
        sustain = 0.5
        themes: List[str] = []
        if evidence:
            ps = []
            for e in evidence:
                q = e.get("policy_quant") or {}
                if "policy_strength" in q:
                    ps.append(float(q.get("policy_strength", 0.5)))
                    sustain = max(sustain, float(q.get("policy_sustain", 0.5)))
                th = q.get("themes") or []
                if isinstance(th, list):
                    themes.extend([str(x) for x in th])
            if ps:
                strength = sum(ps) / max(1, len(ps))
        themes = _dedup(themes)[:12]

        # Primary sectors heuristic (can be replaced by LLM / graph)
        sector_map = {
            "AI": ["人工智能", "算力", "大模型", "AIGC"],
            "半导体": ["半导体", "芯片", "国产替代"],
            "低空经济": ["低空", "通航", "无人机", "eVTOL"],
            "新能源": ["新能源", "光伏", "储能", "电池"],
            "军工": ["军工", "国防", "航天"],
            "机器人": ["机器人", "自动化", "人形机器人"],
        }
        hits = []
        corpus = " ".join([(_safe_str(e.get("title")) + " " + _safe_str(e.get("content"))) for e in evidence])[:20000]
        for sec, kws in sector_map.items():
            if any(k in corpus for k in kws):
                hits.append(sec)
        primary_sectors = hits[:6]

        # DEFCON: simple mapping
        policy_score = 0.6 * strength + 0.4 * sustain
        if policy_score >= 0.7:
            defcon = "OFFENSE"
            conf = min(0.85, 0.55 + (policy_score - 0.7) * 0.8)
        elif policy_score <= 0.4:
            defcon = "RETREAT"
            conf = min(0.75, 0.45 + (0.4 - policy_score) * 0.6)
        else:
            defcon = "DEFENSE"
            conf = 0.55

        core_logic = f"[{_now_iso()}] 政策强度≈{strength:.2f} 持续性≈{sustain:.2f} | DEFCON={defcon} | 主线={', '.join(primary_sectors) or '待识别'} | 主题={', '.join(themes) or '—'}"
        return {
            "core_logic": core_logic,
            "primary_sectors": primary_sectors,
            "themes": themes,
            "confidence": float(conf),
            "defcon_level": defcon,
            "policy_strength": float(strength),
            "policy_sustain": float(sustain),
            "evidence": evidence,
        }
