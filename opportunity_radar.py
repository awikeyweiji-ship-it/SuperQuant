# -*- coding: utf-8 -*-
"""
opportunity_radar.py
====================
机会雷达 · 多维度因子编排器 (Commercial Pro V13.0 - 全息情报版)

设计目标：
- 覆盖“政策/技术/需求/情绪/资金/估值/宏观”七维因子，确保入围标的具备可验证的投资依据。
- 与现有 DataEngine / MarketScanner 解耦，随取随用；缺少某类数据时自动降级为中性分数，不让 UI/调度崩。
- 输出可直接落到表格：score、买入建议、依据摘要，方便“机会雷达”面板直接呈现。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from data_engine import DataEngine, normalize_code


@dataclass
class RadarWeights:
    policy: float = 0.2
    sentiment: float = 0.15
    capital_flow: float = 0.2
    valuation: float = 0.15
    demand: float = 0.1
    momentum: float = 0.1
    macro: float = 0.1

    def total(self) -> float:
        return sum(
            [
                self.policy,
                self.sentiment,
                self.capital_flow,
                self.valuation,
                self.demand,
                self.momentum,
                self.macro,
            ]
        )


class OpportunityRadar:
    """
    将多源情报编排为量化可比的 Radar 表。
    """

    def __init__(self, engine: Optional[DataEngine] = None, weights: Optional[RadarWeights] = None):
        self.engine = engine or DataEngine()
        self.weights = weights or RadarWeights()
        self.alt_engine = getattr(self.engine, "alt_engine", None)
        self.fund_engine = getattr(self.engine, "fund_engine", None)
        self.capital_engine = getattr(self.engine, "capital_engine", None)

    # ------------------------------------------------------------------
    # 公用工具
    # ------------------------------------------------------------------
    @staticmethod
    def _clip01(x: Any) -> float:
        try:
            return float(max(0.0, min(1.0, x)))
        except Exception:
            return 0.5

    @staticmethod
    def _tanh01(x: float, scale: float = 20.0) -> float:
        try:
            return 0.5 * (np.tanh(x / scale) + 1.0)
        except Exception:
            return 0.5

    def _macro_score(self) -> Dict[str, float]:
        """根据宏观指标粗略给出风险偏好评分，并记录覆盖情况。"""
        macro_data = {"macro_score": 0.5, "comment": "", "macro_coverage": False}
        if not self.alt_engine:
            macro_data["comment"] = "无另类情报引擎，按中性处理"
            return macro_data

        try:
            snapshot = self.alt_engine.fetch_macro_indexes()
            macro_data["macro_coverage"] = True
        except Exception:
            macro_data["comment"] = "宏观接口异常，按中性处理"
            return macro_data

        cpi = float(snapshot.get("cpi_yoy", 0.5) or 0.5)
        m2 = float(snapshot.get("m2_yoy", 8.0) or 8.0)
        bond = float(snapshot.get("cn_10y_bond", 2.5) or 2.5)

        # 简化评分：通胀温和、流动性友好、利率低 -> 高分
        cpi_score = 1.0 - self._clip01(abs(cpi - 2.0) / 6)
        m2_score = self._clip01(m2 / 12)
        rate_score = 1.0 - self._clip01(bond / 5)

        macro_val = (0.4 * cpi_score + 0.35 * m2_score + 0.25 * rate_score)
        macro_data["macro_score"] = round(self._clip01(macro_val), 3)
        macro_data["comment"] = f"CPI {cpi:.2f}, M2 {m2:.1f}, 10Y {bond:.2f}"
        return macro_data

    def _policy_and_sentiment(self, code: str, sector: str = "") -> Dict[str, float]:
        """抓取政策强度 + 舆情情绪，并返回覆盖标记。"""
        policy_score = 0.5
        sentiment_score = 0.5
        policy_hits: List[str] = []
        sentiment_words: List[str] = []
        policy_coverage = False
        sentiment_coverage = False

        if self.alt_engine:
            try:
                news = self.alt_engine.fetch_smart_news(symbol=code, sector=sector)
                macro_hits = news.get("macro", []) if isinstance(news, dict) else []
                corp_hits = news.get("corporate", []) if isinstance(news, dict) else []
                # 简化：宏观/政策命中越多，得分越高，上限 0.95
                total_hits = len(macro_hits) + len(corp_hits)
                policy_score = self._clip01(0.35 + 0.1 * total_hits)
                policy_hits = [str(item.get("title", "")) for item in macro_hits[:3]]
                policy_coverage = True
            except Exception:
                policy_score = 0.5

            try:
                senti = self.alt_engine.fetch_guba_sentiment(symbol=code)
                sentiment_score = self._clip01(0.5 + float(senti.get("score", 0)) * 0.5)
                sentiment_words = list(senti.get("hot_words", []) or [])
                sentiment_coverage = True
            except Exception:
                sentiment_score = 0.5

        return {
            "policy_score": round(policy_score, 3),
            "policy_hits": "; ".join(policy_hits),
            "sentiment_score": round(sentiment_score, 3),
            "sentiment_words": ", ".join(sentiment_words),
            "policy_coverage": policy_coverage,
            "sentiment_coverage": sentiment_coverage,
        }

    def _fundamental_scores(self, code: str) -> Dict[str, float]:
        valuation = 0.5
        demand = 0.5
        growth = 0.5
        fund_coverage = False
        valuation_basis = ""
        demand_basis = ""
        growth_basis = ""

        if self.fund_engine:
            try:
                snap = self.fund_engine.get_financial_snapshot(code)
                pe = snap.get("pe") or snap.get("pb")
                revenue_yoy = snap.get("revenue_yoy", 0.0) or 0.0
                profit_yoy = snap.get("profit_yoy", 0.0) or 0.0

                if pe:
                    valuation = self._clip01(1.0 - self._tanh01(float(pe), scale=80))
                    valuation_basis = f"PE/PB={pe}"
                demand = self._clip01(self._tanh01(float(revenue_yoy), scale=40))
                demand_basis = f"营收YoY={revenue_yoy}%"
                growth = self._clip01(self._tanh01(float(profit_yoy), scale=40))
                growth_basis = f"归母YoY={profit_yoy}%"
                fund_coverage = True
            except Exception:
                pass

        return {
            "valuation_score": round(valuation, 3),
            "demand_score": round(demand, 3),
            "growth_score": round(growth, 3),
            "fund_coverage": fund_coverage,
            "valuation_basis": valuation_basis,
            "demand_basis": demand_basis,
            "growth_basis": growth_basis,
        }

    def _capital_and_momentum(
        self, code: str, market_row: Optional[pd.Series]
    ) -> Dict[str, float]:
        capital_score = 0.5
        momentum_score = 0.5
        flow_detail = None
        flow_coverage = False

        if market_row is not None:
            pct = float(market_row.get("pct", 0.0) or 0.0)
            vol_ratio = float(market_row.get("vol_ratio", 0.0) or 0.0)
            main_flow = float(market_row.get("main_net_inflow", 0.0) or 0.0)

            # 近端强势 + 放量 + 主力净流入 -> 高分
            momentum_score = self._clip01(0.5 + 0.5 * self._tanh01(pct, scale=12))
            capital_score = self._clip01(0.45 + 0.1 * self._tanh01(vol_ratio, scale=3) + 0.1 * self._tanh01(main_flow, scale=5))
            flow_coverage = True

        if self.capital_engine:
            try:
                flow = self.capital_engine.get_capital_features(code)
                detail = flow.get("main_net_inflow_detail") if isinstance(flow, dict) else None
                if detail is not None:
                    flow_detail = detail
                    capital_score = max(capital_score, self._clip01(0.5 + self._tanh01(detail, scale=5)))
                    flow_coverage = True
            except Exception:
                pass

        return {
            "capital_score": round(capital_score, 3),
            "momentum_score": round(momentum_score, 3),
            "capital_flow_detail": flow_detail,
            "flow_coverage": flow_coverage,
        }

    def build_radar_table(
        self,
        codes: List[str],
        market_df: Optional[pd.DataFrame] = None,
        sector_map: Optional[Dict[str, str]] = None,
    ) -> pd.DataFrame:
        codes = [normalize_code(c) for c in codes if str(c).strip()]
        if not codes:
            return pd.DataFrame()

        if market_df is None:
            market_df = self.engine.get_spot_snapshot()
        if market_df is None or getattr(market_df, "empty", True):
            market_df = pd.DataFrame()
        else:
            market_df["code"] = market_df.get("code", pd.Series(dtype=str)).astype(str).apply(normalize_code)
            market_df = market_df.set_index("code")

        macro_pack = self._macro_score()
        rows: List[Dict[str, Any]] = []
        sector_map = sector_map or getattr(self.engine, "sector_map", {}) or {}

        for code in codes:
            row = {"code": code}
            market_row = market_df.loc[code] if not market_df.empty and code in market_df.index else None
            row["name"] = market_row.get("name") if market_row is not None else ""
            row["sector"] = sector_map.get(code, "")

            # 七维因子
            policy_pack = self._policy_and_sentiment(code, sector=row["sector"])
            fund_pack = self._fundamental_scores(code)
            flow_pack = self._capital_and_momentum(code, market_row)

            row.update(policy_pack)
            row.update(fund_pack)
            row.update(flow_pack)
            row.update({"macro_score": macro_pack.get("macro_score", 0.5), "macro_comment": macro_pack.get("comment", "")})

            # 数据覆盖度与依据摘要
            row["data_gaps"] = self._gap_summary(policy_pack, fund_pack, flow_pack, macro_pack)
            news_links, news_reasons = self._news_evidence(code, row["sector"])
            evidence_list, evidence_text = self._build_evidence(row)
            combined_reasons = news_reasons + evidence_list
            if len(combined_reasons) < 5:
                combined_reasons.extend([
                    f"趋势分 {row.get('momentum_score', 0)}",
                    f"资金分 {row.get('capital_score', 0)}",
                    f"基本面 {row.get('valuation_basis', '') or '估值中性'}",
                    f"增长 {row.get('growth_basis', '') or '增速中性'}",
                    f"情绪 {row.get('sentiment_words', '') or '无明显热词'}",
                ])
                combined_reasons = combined_reasons[:5]
            if len(news_links) < 3:
                news_links.extend(
                    [
                        {"url": f"data://{code}/capital_flow", "source": "metric", "time": ""},
                        {"url": f"data://{code}/trend", "source": "metric", "time": ""},
                        {"url": f"data://{code}/fundamental", "source": "metric", "time": ""},
                    ][: 3 - len(news_links)]
                )
            row["evidence_points"] = combined_reasons
            row["evidence"] = " | ".join(combined_reasons)
            row["evidence_links"] = news_links

            # 综合评分
            weights = self.weights
            total_w = weights.total()
            radar_score = (
                weights.policy * row["policy_score"]
                + weights.sentiment * row["sentiment_score"]
                + weights.capital_flow * row["capital_score"]
                + weights.valuation * row["valuation_score"]
                + weights.demand * row["demand_score"]
                + weights.momentum * row["momentum_score"]
                + weights.macro * row["macro_score"]
            ) / (total_w or 1)
            row["radar_score"] = round(self._clip01(radar_score), 3)
            row["score_total"] = row["radar_score"]
            row["recommendation"] = self._make_reco(row)
            row["action"] = self._action_label(row["radar_score"], row["recommendation"])
            row["resonance_reason"] = self._resonance_reason(row, news_links)
            rows.append(row)

        df = pd.DataFrame(rows)
        return df.sort_values("radar_score", ascending=False).reset_index(drop=True)

    def _make_reco(self, row: Dict[str, Any]) -> str:
        score = row.get("radar_score", 0.5)
        policy = row.get("policy_score", 0.5)
        capital = row.get("capital_score", 0.5)
        sentiment = row.get("sentiment_score", 0.5)

        if score >= 0.7 and policy >= 0.55 and capital >= 0.55:
            return "进攻：政策+资金共振，可分批吸筹"
        if score >= 0.58:
            return "观察：逻辑成立，轻仓跟踪"
        if sentiment >= 0.8:
            return "警戒：情绪过热，防止接力风险"
        return "回避：未形成共振，等待催化"

    def _action_label(self, total: float, reco: str) -> str:
        if total >= 0.7:
            return "买"
        if total >= 0.55:
            return "观望"
        if "警戒" in reco:
            return "观望"
        return "回避"

    def _gap_summary(
        self,
        policy_pack: Dict[str, Any],
        fund_pack: Dict[str, Any],
        flow_pack: Dict[str, Any],
        macro_pack: Dict[str, Any],
    ) -> str:
        gaps: List[str] = []
        if not policy_pack.get("policy_coverage"):
            gaps.append("政策新闻缺失")
        if not policy_pack.get("sentiment_coverage"):
            gaps.append("舆情缺失")
        if not fund_pack.get("fund_coverage"):
            gaps.append("财报缺失")
        if not flow_pack.get("flow_coverage"):
            gaps.append("资金流缺失")
        if not macro_pack.get("macro_coverage"):
            gaps.append("宏观兜底")
        return "; ".join(gaps)

    def _build_evidence(self, row: Dict[str, Any]) -> str:
        evidences: List[str] = []
        if row.get("policy_hits"):
            evidences.append(f"政策: {row['policy_hits']}")
        if row.get("capital_flow_detail") is not None:
            evidences.append(f"主力净流入: {row['capital_flow_detail']}")
        if row.get("demand_basis"):
            evidences.append(f"需求: {row['demand_basis']}")
        if row.get("growth_basis"):
            evidences.append(f"利润: {row['growth_basis']}")
        if row.get("valuation_basis"):
            evidences.append(f"估值: {row['valuation_basis']}")
        if row.get("sentiment_words"):
            evidences.append(f"舆情热词: {row['sentiment_words']}")
        if row.get("macro_comment"):
            evidences.append(f"宏观: {row['macro_comment']}")
        return evidences, " | ".join(evidences)

    def _news_evidence(self, code: str, sector: str = "") -> Tuple[List[Dict[str, Any]], List[str]]:
        links: List[Dict[str, Any]] = []
        reasons: List[str] = []
        if self.alt_engine:
            try:
                nb = self.alt_engine.get_news_bundle_structured(code, sector)
                bundle = nb.data if isinstance(nb.data, dict) else {}
                for k in ["announcements", "reports", "hot_events", "opinions", "forums"]:
                    items = bundle.get(k) or []
                    for it in items[:3]:
                        if it.get("url"):
                            links.append({"url": it.get("url"), "source": it.get("source", k), "time": it.get("time", "")})
                        reasons.append(f"{k}: {it.get('title','')[:40]}")
                if len(reasons) < 3:
                    reasons.append("情报覆盖不足，建议继续跟踪")
            except Exception:
                reasons.append("情报流获取异常，按中性处理")
        return links[:10], reasons[:8]

    def _resonance_reason(self, row: Dict[str, Any], links: List[Dict[str, Any]]) -> str:
        if (
            row.get("policy_score", 0) > 0.6
            and row.get("capital_score", 0) > 0.55
            and row.get("momentum_score", 0) > 0.55
            and links
        ):
            return "政策/资金/趋势三线共振，叠加公告/研报催化"
        if row.get("sentiment_score", 0) > 0.7 and row.get("capital_score", 0) > 0.55:
            return "情绪升温 + 资金介入"
        return "-"


if __name__ == "__main__":
    # 简单自检
    radar = OpportunityRadar()
    demo = radar.build_radar_table(["000001", "600519"])
    print(demo.head())
