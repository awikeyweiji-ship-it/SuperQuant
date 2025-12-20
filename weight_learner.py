# -*- coding: utf-8 -*-
"""
weight_learner.py
=================
Step4: 权重学习（把“慢变量”变成可回测、可训练的因子权重）

方法（务实可用）：
- 从 factor_snapshot（SQLite）取出因子样本
- 计算 forward return（horizon 日后收益）
- 对因子做标准化，使用 Ridge Regression 训练权重
- 输出 weights.json，供 Smart Radar 的“建仓清单”使用

注意：
- 这是“统计学习”层，不承诺收益；但能把因子体系变成可量化迭代的闭环。
"""

from __future__ import annotations

import json
import math
import os
import sqlite3
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd


def _clip(x: float, lo: float, hi: float) -> float:
    return float(max(lo, min(hi, x)))


def _safe_float(x, default=0.0) -> float:
    try:
        if x is None:
            return float(default)
        return float(x)
    except Exception:
        return float(default)


def _standardize(df: pd.DataFrame) -> Tuple[pd.DataFrame, pd.Series, pd.Series]:
    mu = df.mean(axis=0)
    sd = df.std(axis=0).replace(0, 1.0)
    z = (df - mu) / sd
    return z, mu, sd


def load_factor_snapshot(db_path: str, start: str, end: str) -> pd.DataFrame:
    """
    兼容两种存储：
    1) SQLite: factor_snapshot 表（旧版/可选）
    2) Parquet: SlowFactorEngine 的 slow_factors_store.parquet（默认）
    """
    # 1) SQLite
    if db_path and os.path.exists(db_path) and db_path.lower().endswith(".sqlite"):
        con = sqlite3.connect(db_path)
        try:
            q = """
            SELECT * FROM factor_snapshot
            WHERE as_of >= ? AND as_of <= ?
            """
            df = pd.read_sql_query(q, con, params=[start, end])
            return df
        finally:
            con.close()

    # 2) Parquet (default path)
    cand_paths = []
    if db_path and os.path.exists(db_path) and db_path.lower().endswith(".parquet"):
        cand_paths.append(db_path)
    cand_paths.append(os.path.join(".w5brain_cache", "factors", "slow_factors_store.parquet"))
    cand_paths.append(os.path.join(".w5brain_cache", "factors", "slow_factors.parquet"))

    for p in cand_paths:
        if os.path.exists(p):
            try:
                df = pd.read_parquet(p)
                # normalize date columns
                if "date" in df.columns and "as_of" not in df.columns:
                    df = df.rename(columns={"date": "as_of"})
                if "as_of" in df.columns:
                    df["as_of"] = pd.to_datetime(df["as_of"]).dt.strftime("%Y-%m-%d")
                    df = df[(df["as_of"] >= start) & (df["as_of"] <= end)]
                return df
            except Exception:
                continue

    return pd.DataFrame()
def _get_forward_return(engine: Any, code: str, as_of: str, horizon: int = 5) -> Optional[float]:
    """
    使用 DataEngine.get_kline 拉取历史，计算 horizon 日后收益。
    - as_of: YYYY-MM-DD
    """
    try:
        k = engine.get_kline(code, freq="daily", limit=2500)
        if k is None or k.empty:
            return None
        k = k.copy()
        if "date" not in k.columns or "close" not in k.columns:
            return None
        k["date"] = pd.to_datetime(k["date"])
        k = k.sort_values("date")
        d0 = pd.to_datetime(as_of)
        # find first row >= d0
        idx = k["date"].searchsorted(d0)
        if idx >= len(k):
            return None
        i1 = idx + int(horizon)
        if i1 >= len(k):
            return None
        p0 = float(k.iloc[idx]["close"])
        p1 = float(k.iloc[i1]["close"])
        if p0 <= 0:
            return None
        return float(p1 / p0 - 1.0)
    except Exception:
        return None


def learn_weights(
    engine: Any,
    factor_db_path: str = ".w5brain_factors.sqlite",
    start: str = "2020-01-01",
    end: str = "2030-01-01",
    horizon: int = 5,
    l2: float = 10.0,
    max_rows: int = 30000,
    min_rows: int = 1200,
) -> Dict[str, Any]:
    df = load_factor_snapshot(factor_db_path, start, end)
    if df is None or df.empty:
        return {"ok": False, "msg": "factor_snapshot 为空：请先跑一段时间 Smart Radar 扫描，让系统积累因子样本。"}

    # Choose factor columns (present)
    factor_cols = [
        'policy_strength','policy_persistence','demand_space','domestic_substitution','market_pricing','info_priced_in',
        'fundamental_quality','fundamental_growth','ops_momentum'
    ]
    factor_cols = [c for c in factor_cols if c in df.columns]
    if len(factor_cols) < 4:
        return {"ok": False, "msg": f"可用因子列太少：{factor_cols}，请更新版本并重新扫描。"}

    df = df.dropna(subset=["code", "as_of"]).copy()
    df = df.sort_values("as_of")
    # sample to limit
    if len(df) > max_rows:
        df = df.tail(max_rows).copy()

    # compute forward returns
    ys = []
    keep_rows = []
    for i, r in df.iterrows():
        code = str(r["code"])
        as_of = str(r["as_of"])[:10]
        y = _get_forward_return(engine, code, as_of, horizon=horizon)
        if y is None or math.isnan(y):
            continue
        ys.append(y)
        keep_rows.append(i)

    if len(keep_rows) < min_rows:
        return {"ok": False, "msg": f"可回测样本不足（{len(keep_rows)} < {min_rows}）。可尝试：拉长时间范围、增加扫描频次或降低 horizon。"}

    d = df.loc[keep_rows].copy()
    y = pd.Series(ys, index=d.index)

    X = d[factor_cols].apply(pd.to_numeric, errors="coerce").fillna(0.5)
    Z, mu, sd = _standardize(X)

    # Ridge regression (closed form)
    import numpy as np
    Xn = Z.to_numpy(dtype=float)
    yn = y.to_numpy(dtype=float).reshape(-1, 1)
    # add intercept? we ignore; weights only
    I = np.eye(Xn.shape[1])
    w = np.linalg.inv(Xn.T @ Xn + float(l2) * I) @ (Xn.T @ yn)
    w = w.reshape(-1)

    # normalize
    w = np.clip(w, -2.0, 2.0)
    s = float(np.sum(np.abs(w)))
    if s > 0:
        w = w / s

    weights = {c: float(w[i]) for i, c in enumerate(factor_cols)}

    # quick diagnostics: IC (rank correlation)
    try:
        pred = Z.dot(pd.Series(weights))
        ic = float(pred.corr(y, method="spearman"))
    except Exception:
        ic = 0.0

    return {
        "ok": True,
        "horizon": int(horizon),
        "l2": float(l2),
        "n_samples": int(len(d)),
        "factor_cols": factor_cols,
        "weights": weights,
        "mu": {c: float(mu[c]) for c in factor_cols},
        "sd": {c: float(sd[c]) for c in factor_cols},
        "ic_spearman": ic,
    }


def save_weights(model: Dict[str, Any], path: str = ".w5brain_weights.json") -> Tuple[bool, str]:
    try:
        model = dict(model)
        model["saved_at"] = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(model, f, ensure_ascii=False, indent=2)
        return True, f"已保存：{path}"
    except Exception as e:
        return False, f"保存失败：{e}"


def load_weights(path: str = ".w5brain_weights.json") -> Optional[Dict[str, Any]]:
    try:
        if not os.path.exists(path):
            return None
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None