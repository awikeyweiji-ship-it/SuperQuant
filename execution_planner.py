# -*- coding: utf-8 -*-
"""
execution_planner.py
====================
天网雷达·即时建仓执行规划器 (Commercial Pro Step-2)

目标：
- 基于「MarketScanner + SignalFuser」输出的候选池（带 score / fused_score / 现价）
- 结合当前价格位置（MA/ATR/区间）与宏观 DEFCON 风险预算
- 生成 10-50 只「现在可建仓」的组合建议（含：买入方式、止损、止盈、建议资金/手数、理由）
- ✅ 离线可用：当 K 线不可用时，退化为更保守的规则

注意：本模块输出仅供研究与模拟，不构成任何投资建议。
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, Any, Optional, Tuple, List
import math
import pandas as pd
import numpy as np


@dataclass
class BuildConfig:
    # 目标数量
    target_count: int = 20           # 10~50
    # 账户资金
    total_cash: float = 100000.0
    # 风格：影响单票上限、最小头寸、整体部署比例
    risk_profile: str = "标准"        # 保守/标准/激进
    # 单行业暴露上限（部署资金的比例）
    sector_cap: float = 0.30
    # 是否尝试拉取K线做价格位置判断（慢一些但更准）
    use_kline: bool = True
    # K线窗口
    kline_limit: int = 120
    # 优先级：是否更偏好「价格不追高」
    avoid_chasing: bool = True


def _safe_float(x, default: float = 0.0) -> float:
    try:
        if x is None or (isinstance(x, float) and math.isnan(x)):
            return default
        return float(x)
    except Exception:
        return default


def _atr(df: pd.DataFrame, n: int = 14) -> Optional[float]:
    """ATR(14) 近似"""
    if df is None or df.empty:
        return None
    needed = {"high", "low", "close"}
    if not needed.issubset(df.columns):
        return None
    d = df.tail(max(n + 2, 30)).copy()
    prev_close = d["close"].shift(1)
    tr = pd.concat([
        (d["high"] - d["low"]).abs(),
        (d["high"] - prev_close).abs(),
        (d["low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    atr = tr.rolling(n).mean().iloc[-1]
    if pd.isna(atr):
        return None
    return float(atr)


def _ma(df: pd.DataFrame, n: int) -> Optional[float]:
    if df is None or df.empty or "close" not in df.columns:
        return None
    v = df["close"].rolling(n).mean().iloc[-1]
    if pd.isna(v):
        return None
    return float(v)


def _hi_lo(df: pd.DataFrame, n: int = 20) -> Tuple[Optional[float], Optional[float]]:
    if df is None or df.empty:
        return None, None
    if not {"high", "low"}.issubset(df.columns):
        return None, None
    d = df.tail(max(n, 30))
    hi = d["high"].rolling(n).max().iloc[-1]
    lo = d["low"].rolling(n).min().iloc[-1]
    return (None if pd.isna(hi) else float(hi)), (None if pd.isna(lo) else float(lo))


def _defcon_deploy_ratio(defcon: str) -> float:
    d = (defcon or "").upper()
    if "RETREAT" in d:
        return 0.30
    if "DEFENSE" in d:
        return 0.60
    return 0.90  # ATTACK 或未知 -> 进攻


def _profile_caps(profile: str) -> Tuple[float, float]:
    """返回 (单票上限cap_ratio, 单票最小min_ratio)"""
    p = (profile or "标准").strip()
    if p == "保守":
        return 0.06, 0.015
    if p == "激进":
        return 0.12, 0.020
    return 0.08, 0.018


def _entry_judgement(price: float, pct: float, ma20: Optional[float], ma60: Optional[float], atr14: Optional[float],
                     hi20: Optional[float], lo20: Optional[float], avoid_chasing: bool = True) -> Tuple[str, str]:
    """
    返回 (action_tag, reason)
    action_tag: BUY_NOW / PROBE_SMALL / WAIT_PULLBACK / SKIP
    """
    # 基础极端情况：涨停/暴拉 -> 不追
    if pct >= 9.0:
        return "WAIT_PULLBACK", "当日涨幅过大（疑似涨停/情绪顶），避免追高，等回落或换手确认。"

    if ma20 is None or ma60 is None:
        # 离线退化：只做保守判断
        if pct <= 5.0:
            return "PROBE_SMALL", "K线不可用，采用保守模式：允许小仓位试探（不追涨）。"
        return "SKIP", "K线不可用且涨幅偏大，跳过。"

    dist20 = (price / ma20 - 1.0) if ma20 > 0 else 0.0
    dist60 = (price / ma60 - 1.0) if ma60 > 0 else 0.0

    # 趋势过滤：跌破60日线 -> 先不做
    if price < ma60:
        return "SKIP", "价格低于MA60，中期趋势未确认，跳过。"

    # 追高惩罚
    if avoid_chasing and dist20 > 0.08:
        return "WAIT_PULLBACK", f"距离MA20过远（+{dist20*100:.1f}%），属于追高区，等回踩MA20或横盘消化。"

    # 理想建仓区：略高于MA20，且趋势向上
    if 0.00 <= dist20 <= 0.05:
        return "BUY_NOW", f"价格位于MA20上方的理想建仓区（+{dist20*100:.1f}%），趋势向上，可分批建仓。"

    # 略回踩：靠近MA20下方，小仓试探
    if -0.03 <= dist20 < 0.00:
        return "PROBE_SMALL", f"价格回踩MA20附近（{dist20*100:.1f}%），可小仓试探，等待反包/企稳确认。"

    # 其余：偏弱或过度回撤
    return "SKIP", "价格位置不佳（不在建仓区/趋势不清），跳过。"


class ExecutionPlanner:
    """
    输入：df_res（至少含 code,name,sector,close,score,fused_score,pct 可选）
    输出：组合建议 DataFrame + 汇总信息 dict
    """
    def __init__(self, engine):
        self.engine = engine

    def build_portfolio(
        self,
        df_candidates: pd.DataFrame,
        macro_report: Optional[Dict[str, Any]] = None,
        config: Optional[BuildConfig] = None
    ) -> Tuple[pd.DataFrame, Dict[str, Any]]:
        config = config or BuildConfig()
        if df_candidates is None or df_candidates.empty:
            return pd.DataFrame(), {"error": "empty_candidates"}

        df = df_candidates.copy()

        # 必要列
        for c in ["code", "name", "sector", "close", "score", "fused_score"]:
            if c not in df.columns:
                raise ValueError(f"df_candidates missing column: {c}")
        if "pct" not in df.columns:
            df["pct"] = 0.0

        # 宏观部署比例
        defcon = (macro_report or {}).get("defcon_level", "ATTACK")
        deploy_ratio = _defcon_deploy_ratio(defcon)

        # 风格上限/下限
        cap_ratio, min_ratio = _profile_caps(config.risk_profile)

        deploy_cash = float(config.total_cash) * deploy_ratio
        if deploy_cash <= 0:
            return pd.DataFrame(), {"error": "deploy_cash<=0"}

        # 先只取前 200 做价格判断（避免跑太慢）
        df = df.sort_values("fused_score", ascending=False).head(max(200, config.target_count * 4))

        # 逐个计算价格位置
        rows: List[Dict[str, Any]] = []
        for _, r in df.iterrows():
            code = str(r["code"])
            price = _safe_float(r["close"], 0.0)
            pct = _safe_float(r.get("pct", 0.0), 0.0)
            sector = str(r.get("sector", "其他"))

            ma20 = ma60 = atr14 = hi20 = lo20 = None
            if config.use_kline:
                k = None
                try:
                    k = self.engine.get_kline(code, freq="daily", limit=config.kline_limit)
                except Exception:
                    k = None
                if k is not None and not k.empty:
                    ma20 = _ma(k, 20)
                    ma60 = _ma(k, 60)
                    atr14 = _atr(k, 14)
                    hi20, lo20 = _hi_lo(k, 20)

            tag, reason = _entry_judgement(price, pct, ma20, ma60, atr14, hi20, lo20, avoid_chasing=config.avoid_chasing)

            # 止损止盈（ATR优先）
            if atr14 and atr14 > 0:
                stop = max(0.01, price - 2.0 * atr14)
                tp1 = price + 2.0 * atr14
                tp2 = price + 4.0 * atr14
            else:
                stop = max(0.01, price * (1 - 0.06))
                tp1 = price * (1 + 0.08)
                tp2 = price * (1 + 0.15)

            rows.append({
                "code": code,
                "name": str(r.get("name", "")),
                "sector": sector,
                "price": round(price, 3),
                "pct": round(pct, 3),
                "score": _safe_float(r.get("score", 0.0)),
                "fused_score": _safe_float(r.get("fused_score", 0.0)),
                "action": tag,
                "entry_reason": reason,
                "stop_loss": round(stop, 3),
                "take_profit_1": round(tp1, 3),
                "take_profit_2": round(tp2, 3),
                "ma20": None if ma20 is None else round(ma20, 3),
                "ma60": None if ma60 is None else round(ma60, 3),
            })

        cand = pd.DataFrame(rows)
        if cand.empty:
            return pd.DataFrame(), {"error": "no_rows"}

        # 只保留 BUY_NOW / PROBE_SMALL（优先）
        pri = cand[cand["action"].isin(["BUY_NOW", "PROBE_SMALL"])].copy()
        if pri.empty:
            # 退化：允许 WAIT_PULLBACK 里排名靠前的做“观察仓”
            pri = cand[cand["action"].isin(["WAIT_PULLBACK"])].copy()

        pri = pri.sort_values(["action", "fused_score"], ascending=[True, False])

        # 资金分配：按 fused_score 加权
        fs = pri["fused_score"].clip(lower=0.0001)
        pri["_w"] = fs / fs.sum()

        # 行业暴露控制 + 数量控制
        picked: List[Dict[str, Any]] = []
        sector_cash: Dict[str, float] = {}
        max_sector_cash = deploy_cash * float(config.sector_cap)

        for _, r in pri.iterrows():
            if len(picked) >= int(config.target_count):
                break

            sec = r["sector"]
            # 预计金额（未应用 cap/min 前）
            amt = deploy_cash * float(r["_w"])
            # cap/min
            amt = min(amt, float(config.total_cash) * cap_ratio)
            amt = max(amt, float(config.total_cash) * min_ratio)

            # 行业上限
            if sector_cash.get(sec, 0.0) + amt > max_sector_cash and len(picked) > 0:
                continue

            # A股手数（100股一手）
            price = float(r["price"]) if r["price"] else 0.0
            if price <= 0:
                continue
            shares = int(amt // price)
            lots = int(shares // 100) * 100
            if lots < 100:
                # 太小的票不建议进入“即时建仓”名单（也防止极高价股）
                continue
            real_amt = round(lots * price, 2)

            sector_cash[sec] = sector_cash.get(sec, 0.0) + real_amt
            picked.append({
                **{k: r[k] for k in ["code", "name", "sector", "price", "pct", "score", "fused_score", "action",
                                     "entry_reason", "stop_loss", "take_profit_1", "take_profit_2", "ma20", "ma60"]},
                "suggest_cash": real_amt,
                "suggest_shares": lots,
                "build_method": "分3笔建仓：40%/30%/30%（回踩/企稳/放量）" if r["action"] == "BUY_NOW" else "先小仓试探：20%，确认后加到100%"
            })

        out = pd.DataFrame(picked)
        out = out.sort_values(["action", "fused_score"], ascending=[True, False]).reset_index(drop=True)

        summary = {
            "defcon": defcon,
            "deploy_ratio": deploy_ratio,
            "deploy_cash": round(deploy_cash, 2),
            "picked": int(len(out)),
            "sector_exposure": {k: round(v, 2) for k, v in sorted(sector_cash.items(), key=lambda x: -x[1])},
            "notes": "BUY_NOW=现在可建仓；PROBE_SMALL=先试探；WAIT_PULLBACK=等回踩；SKIP=跳过"
        }
        return out, summary
