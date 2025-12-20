# -*- coding: utf-8 -*-
"""policy_engine.py
===================
慢变量因子：政策量化引擎 (Policy Factor Engine)

把“政策强度/持续性、国产替代、需求空间”等文本信号量化成可回测因子。

特点：
- 规则为主，轻量 NLP 为辅；在无外部依赖时也可运行。
- 返回 0~1 的分数 + 可解释的触发理由。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, Any, List, Tuple


@dataclass
class PolicyScore:
    """单条政策/新闻文本的评分结果"""

    policy_strength: float  # 0~1
    policy_sustain: float   # 0~1
    demand_signal: float    # 0~1
    substitution_signal: float  # 0~1
    themes: List[str]
    triggers: List[str]


class PolicyEngine:
    """规则化政策因子评分"""

    # 权威机构/会议/文件：越靠“顶层”，政策强度越高
    AUTHORITY_WEIGHTS: List[Tuple[str, float]] = [
        ("中共中央", 1.00),
        ("国务院", 0.95),
        ("中央", 0.90),
        ("国家发改委", 0.88),
        ("发改委", 0.85),
        ("财政部", 0.82),
        ("央行", 0.82),
        ("人民银行", 0.82),
        ("证监会", 0.78),
        ("工信部", 0.78),
        ("国资委", 0.75),
        ("部委", 0.70),
        ("省政府", 0.62),
        ("地方", 0.55),
        ("试点", 0.50),
    ]

    # 资金/量化“力度”词
    INTENSITY_HINTS: List[Tuple[str, float]] = [
        ("万亿", 0.25),
        ("千亿", 0.18),
        ("专项债", 0.15),
        ("财政补贴", 0.15),
        ("补贴", 0.10),
        ("税收优惠", 0.12),
        ("降准", 0.18),
        ("降息", 0.18),
        ("再贷款", 0.12),
        ("扩大", 0.08),
        ("加快", 0.08),
        ("落地", 0.10),
    ]

    # 持续性/周期词：越长周期越高
    SUSTAIN_HINTS: List[Tuple[str, float]] = [
        ("五年规划", 1.00),
        ("十四五", 1.00),
        ("十五五", 1.00),
        ("2030", 0.95),
        ("2035", 1.00),
        ("长期", 0.75),
        ("中长期", 0.75),
        ("三年行动", 0.65),
        ("行动计划", 0.55),
        ("试点", 0.40),
        ("短期", 0.25),
    ]

    # 国产替代相关
    SUBSTITUTION_HINTS: List[Tuple[str, float]] = [
        ("国产替代", 1.00),
        ("自主可控", 0.95),
        ("信创", 0.85),
        ("国产化", 0.80),
        ("卡脖子", 0.75),
        ("关键核心技术", 0.75),
        ("供应链安全", 0.70),
    ]

    # 需求空间相关
    DEMAND_HINTS: List[Tuple[str, float]] = [
        ("需求", 0.20),
        ("订单", 0.22),
        ("出口", 0.22),
        ("渗透率", 0.18),
        ("市场规模", 0.22),
        ("增长", 0.15),
        ("放量", 0.12),
        ("扩产", 0.18),
        ("产能", 0.15),
    ]

    # 常见主题（概念）词库（用于图谱/映射）
    THEME_KEYWORDS: Dict[str, List[str]] = {
        "低空经济": ["低空", "通航", "eVTOL", "空管", "无人机"],
        "AI算力": ["算力", "GPU", "数据中心", "AI服务器", "液冷"],
        "半导体": ["半导体", "芯片", "EDA", "先进封装", "光刻"],
        "新能源": ["锂电", "光伏", "储能", "风电", "氢能"],
        "军工": ["军工", "导弹", "雷达", "军贸"],
        "机器人": ["机器人", "人形", "伺服", "减速器"],
        "医药": ["创新药", "医疗器械", "集采"],
        "地产链": ["地产", "城中村", "棚改", "保交楼"],
    }

    def score_text(self, text: str) -> PolicyScore:
        """对输入文本打分。"""
        t = (text or "").strip()
        if not t:
            return PolicyScore(0.0, 0.0, 0.0, 0.0, [], ["EMPTY"])

        triggers: List[str] = []

        # 1) 强度：权威 + 力度词 + 数字规模
        strength = 0.15
        for k, w in self.AUTHORITY_WEIGHTS:
            if k in t:
                strength = max(strength, w)
                triggers.append(f"AUTH:{k}")
        for k, add in self.INTENSITY_HINTS:
            if k in t:
                strength = min(1.0, strength + add)
                triggers.append(f"INT:{k}")

        # 数字规模（万亿/千亿/亿/万）
        if re.search(r"\d+(\.\d+)?\s*万亿", t):
            strength = min(1.0, strength + 0.20)
            triggers.append("NUM:万亿")
        elif re.search(r"\d+(\.\d+)?\s*千亿", t):
            strength = min(1.0, strength + 0.12)
            triggers.append("NUM:千亿")

        # 2) 持续性：周期词 + 年份范围
        sustain = 0.20
        for k, v in self.SUSTAIN_HINTS:
            if k in t:
                sustain = max(sustain, v)
                triggers.append(f"SUS:{k}")
        years = re.findall(r"(20\d{2})", t)
        if years:
            # 出现多个年份，视作更强持续性
            if len(set(years)) >= 2:
                sustain = max(sustain, 0.75)
                triggers.append("SUS:YEAR_RANGE")
            else:
                sustain = max(sustain, 0.55)
                triggers.append("SUS:YEAR")

        # 3) 国产替代信号
        substitution = 0.0
        for k, v in self.SUBSTITUTION_HINTS:
            if k in t:
                substitution = max(substitution, v)
                triggers.append(f"SUB:{k}")

        # 4) 需求空间信号
        demand = 0.0
        for k, v in self.DEMAND_HINTS:
            if k in t:
                demand = min(1.0, demand + v)
                triggers.append(f"DEM:{k}")
        demand = min(1.0, demand)

        # 5) 主题抽取（概念映射）
        themes: List[str] = []
        for theme, kws in self.THEME_KEYWORDS.items():
            if any(kw in t for kw in kws):
                themes.append(theme)

        return PolicyScore(
            policy_strength=float(max(0.0, min(1.0, strength))),
            policy_sustain=float(max(0.0, min(1.0, sustain))),
            demand_signal=float(max(0.0, min(1.0, demand))),
            substitution_signal=float(max(0.0, min(1.0, substitution))),
            themes=themes,
            triggers=triggers[:20],
        )

    def score_evidence_item(self, title: str, content: str = "") -> Dict[str, Any]:
        """对一条证据(新闻/公告/研报摘要)打分，返回可直接入库的 dict。"""
        text = f"{title or ''} {content or ''}".strip()
        ps = self.score_text(text)
        return {
            "policy_strength": ps.policy_strength,
            "policy_sustain": ps.policy_sustain,
            "demand_signal": ps.demand_signal,
            "substitution_signal": ps.substitution_signal,
            "themes": ps.themes,
            "triggers": ps.triggers,
        }
    def quantify_policy(self, text: str) -> Dict[str, Any]:
        """Backward-compatible policy quantification API.

        Older versions of DeepSearchAgent call `PolicyEngine.quantify_policy(text)`.
        This method wraps `score_text` and returns a superset of common keys so
        downstream code can safely consume it.
        """
        ps = self.score_text(text or "")
        policy_score = float(max(0.0, min(1.0, 0.6 * ps.policy_strength + 0.4 * ps.policy_sustain)))
        return {
            # canonical
            "policy_strength": ps.policy_strength,
            "policy_sustain": ps.policy_sustain,
            "demand_signal": ps.demand_signal,
            "substitution_signal": ps.substitution_signal,
            "themes": ps.themes,
            "triggers": ps.triggers,
            "policy_score": policy_score,
            # compatibility aliases (used as slow factors)
            "demand_space": ps.demand_signal,
            "domestic_substitution": ps.substitution_signal,
            "info_sufficiency": 0.5,   # cannot infer from a single text
            "market_pricing": 0.5,     # cannot infer from a single text
        }
