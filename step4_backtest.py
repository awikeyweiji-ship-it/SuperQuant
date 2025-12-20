# -*- coding: utf-8 -*-
"""
step4_backtest.py
=================
Step4: 回测框架（因子 → 建仓清单 → 组合收益）

- 使用 factor_snapshot（SQLite）作为“因子历史”
- 每个 rebalance 日：用权重打分，选 TopK 建仓
- 计算 horizon 日持有收益（可简化为等权）
- 输出曲线与关键指标

说明：
- 为了“可用优先”，这里使用简单等权与离散持仓，不做复杂撮合。
- 真实商用请逐步加入：滑点模型、成交约束、风控规则、行业/风格暴露控制。
"""

from __future__ import annotations

import os
import sqlite3
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from weight_learner import load_factor_snapshot, load_weights, _safe_float, _get_forward_return


def score_row(row: pd.Series, model: Dict[str, Any]) -> float:
    weights = model.get("weights") or {}
    mu = model.get("mu") or {}
    sd = model.get("sd") or {}
    s = 0.0
    for k, w in weights.items():
        x = _safe_float(row.get(k), 0.5)
        m = _safe_float(mu.get(k), 0.0)
        d = _safe_float(sd.get(k), 1.0)
        z = (x - m) / (d if d != 0 else 1.0)
        s += float(w) * float(z)
    # map to 0-100 like score
    return float(50.0 + 25.0 * s)


def run_factor_backtest(
    engine: Any,
    factor_db_path: str = ".w5brain_factors.sqlite",
    weights_path: str = ".w5brain_weights.json",
    start: str = "2023-01-01",
    end: str = "2025-12-31",
    horizon: int = 5,
    topk: int = 20,
    rebalance: str = "W",  # "D"/"W"/"M"
    fee: float = 0.001,
) -> Dict[str, Any]:
    df = load_factor_snapshot(factor_db_path, start, end)
    if df is None or df.empty:
        return {"ok": False, "msg": "factor_snapshot 为空，无法回测。"}
    model = load_weights(weights_path)
    if not model:
        return {"ok": False, "msg": f"未找到权重文件：{weights_path}，请先训练权重。"}

    df["as_of"] = pd.to_datetime(df["as_of"])
    df = df.sort_values("as_of")
    # rebalance dates
    dates = pd.Series(df["as_of"].unique()).sort_values()
    if rebalance.upper().startswith("W"):
        rebal_dates = dates[dates.dt.weekday == 4]  # Friday
        if rebal_dates.empty:
            rebal_dates = dates.iloc[::5]
    elif rebalance.upper().startswith("M"):
        rebal_dates = dates.groupby(dates.dt.to_period("M")).max()
    else:
        rebal_dates = dates

    records = []
    equity = 1.0

    for d0 in rebal_dates:
        d0s = d0.strftime("%Y-%m-%d")
        day = df[df["as_of"] == d0].copy()
        if day.empty:
            continue
        # score
        day["score"] = day.apply(lambda r: score_row(r, model), axis=1)
        picks = day.sort_values("score", ascending=False).head(int(topk))
        if picks.empty:
            continue

        # forward returns, equal weight
        rets = []
        for _, r in picks.iterrows():
            code = str(r["code"])
            fr = _get_forward_return(engine, code, d0s, horizon=horizon)
            if fr is None:
                continue
            rets.append(float(fr))
        if not rets:
            continue
        port_ret = sum(rets) / len(rets)
        # fee per rebalance (round trip simplified)
        port_ret_adj = port_ret - float(fee)
        equity *= (1.0 + port_ret_adj)
        records.append({
            "date": d0s,
            "n": int(len(rets)),
            "port_ret": float(port_ret),
            "port_ret_net": float(port_ret_adj),
            "equity": float(equity),
            "top_codes": ",".join([str(x) for x in picks["code"].tolist()[:10]]),
        })

    if not records:
        return {"ok": False, "msg": "回测无有效记录（可能是价格数据不足或日期对齐失败）。"}

    curve = pd.DataFrame(records)
    curve["date"] = pd.to_datetime(curve["date"])
    curve = curve.sort_values("date")

    # metrics
    total_ret = float(curve["equity"].iloc[-1] - 1.0)
    n = len(curve)
    # annualize roughly: rebalance weekly => 52, daily => 252
    freq = 52 if rebalance.upper().startswith("W") else (12 if rebalance.upper().startswith("M") else 252)
    cagr = float((curve["equity"].iloc[-1]) ** (freq / max(1, n)) - 1.0)

    # max drawdown
    peak = curve["equity"].cummax()
    dd = curve["equity"] / peak - 1.0
    mdd = float(dd.min())

    win = float((curve["port_ret_net"] > 0).mean())

    return {
        "ok": True,
        "n_periods": int(n),
        "total_return": total_ret,
        "cagr_approx": cagr,
        "max_drawdown": mdd,
        "win_rate": win,
        "curve": curve,
    }
