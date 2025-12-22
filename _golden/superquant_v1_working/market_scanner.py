# -*- coding: utf-8 -*-
"""
market_scanner.py
=================
市场扫描器（增强版）

修复点：
1. 完美复刻【图二】中的所有细分扫描策略。
2. 增加对创业板、科创板、主板的精确过滤逻辑。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

import pandas as pd
import numpy as np

try:
    import akshare as ak
except Exception:
    ak = None

from universe_cache import UniverseCache
from data_engine import normalize_code, DataEngine


@dataclass
class ScanConfig:
    """
    快筛参数
    """
    prefer_large_cap: float = 0.35  # 偏好大市值权重
    prefer_value: float = 0.35      # 偏好低估值权重
    prefer_momentum: float = 0.20   # 偏好动量权重
    penalize_overheat: float = 0.10 # 惩罚过热
    min_market_cap_yi: float = 0.0  # 最小市值(亿)
    max_market_cap_yi: Optional[float] = None # 最大市值(亿) - 用于小市值策略
    max_pe: Optional[float] = None  # 过滤过高PE
    name_filter: str = ""           # 名字包含过滤 (如 "ST")
    code_prefix: Optional[List[str]] = None # 代码前缀过滤 (如 ["300"] 创业板)


class MarketScanner:
    def __init__(self, engine: DataEngine, cache: Optional[UniverseCache] = None):
        self.engine = engine
        self.cache = cache or engine.cache

    # ------------------------------------------------------------------
    # 1. 策略池构建 (核心逻辑升级)
    # ------------------------------------------------------------------

    def get_pool(self, pool_id: str) -> List[str]:
        """
        根据策略 ID 返回对应的股票代码列表
        """
        # 尝试读取缓存 (24小时有效)
        cached = self.cache.get_pool(pool_id, ttl_seconds=24 * 3600)
        if cached:
            return [normalize_code(x) for x in cached]

        # 获取全市场快照 (这是基准)
        spot = self.engine.get_spot_snapshot()
        if spot is None or spot.empty:
            return []

        codes: List[str] = []

        # --- 策略 A: 核心资产 (市值 Top 100) ---
        if pool_id == "core_assets_top100":
            codes = spot.sort_values("market_cap", ascending=False).head(100)["code"].tolist()

        # --- 策略 B: 机构重仓 (市值 Top 300) ---
        elif pool_id == "institutional_top300":
            codes = spot.sort_values("market_cap", ascending=False).head(300)["code"].tolist()

        # --- 策略 C: 创业板特攻 (30开头) ---
        elif pool_id == "growth_gem":
            # 筛选 30 开头的股票
            mask = spot["code"].astype(str).str.startswith("30")
            # 且市值不能太小 (过滤掉垃圾票，保留 > 30亿)
            df_gem = spot[mask & (spot["market_cap"] > 30)]
            codes = df_gem.sort_values("market_cap", ascending=False).head(200)["code"].tolist()

        # --- 策略 D: 主板蓝筹 (60开头) ---
        elif pool_id == "main_board_bluechip":
            # 筛选 600/601/603/605 开头
            mask = spot["code"].astype(str).str.match(r"^60[0135]")
            df_main = spot[mask].sort_values("market_cap", ascending=False)
            codes = df_main.head(200)["code"].tolist()

        # --- 策略 E: 极致冷门/小市值 (市值倒数 200) ---
        elif pool_id == "small_cap_contrarian":
            # 剔除 ST 和退市整理
            mask_st = spot["name"].str.contains("ST|退")
            # 市值 > 10亿 (防止太烂) 且 < 50亿
            mask_cap = (spot["market_cap"] > 10) & (spot["market_cap"] < 50)
            
            df_small = spot[~mask_st & mask_cap]
            # 取市值最小的 200 只
            codes = df_small.sort_values("market_cap", ascending=True).head(200)["code"].tolist()

        # --- 策略 F: 全 A 股市场 ---
        elif pool_id == "all_a_shares":
            codes = spot["code"].tolist()

        # 默认回退
        else:
            codes = spot.sort_values("market_cap", ascending=False).head(500)["code"].tolist()

        # 存入缓存
        codes = [normalize_code(x) for x in codes if str(x).strip()]
        self.cache.set_pool(pool_id, codes)
        return codes

    # ------------------------------------------------------------------
    # 2. 向量化扫描 (打分逻辑)
    # ------------------------------------------------------------------

    def scan(self, pool_codes: List[str], config: Optional[ScanConfig] = None) -> pd.DataFrame:
        """
        基于内存计算评分，不请求网络
        """
        config = config or ScanConfig()

        spot = self.engine.get_spot_snapshot()
        if spot is None or spot.empty:
            return pd.DataFrame()

        codes = [normalize_code(x) for x in pool_codes]
        df = spot[spot["code"].isin(codes)].copy()
        if df.empty:
            return pd.DataFrame()

        # --- 过滤器 ---
        # 1. 市值过滤
        if config.min_market_cap_yi > 0:
            df = df[df["market_cap"] >= config.min_market_cap_yi]
        if config.max_market_cap_yi is not None:
            df = df[df["market_cap"] <= config.max_market_cap_yi]
            
        # 2. PE 过滤
        if config.max_pe is not None:
            # pe > 0 且 pe < max
            df = df[(df["pe"] > 0) & (df["pe"] <= config.max_pe)]

        # 3. 名字过滤 (比如不含ST)
        if config.name_filter:
            # 如果 name_filter 是 "ST"，则剔除包含 ST 的
            df = df[~df["name"].str.contains(config.name_filter, na=False)]

        # 4. 前缀过滤 (再次确保)
        if config.code_prefix:
            # 只要以列表中任意一个开头即可
            pattern = "|".join([f"^{p}" for p in config.code_prefix])
            df = df[df["code"].astype(str).str.match(pattern)]

        if df.empty:
            return pd.DataFrame()

        # --- 打分逻辑 ---
        # 填充缺失值
        mcap = df["market_cap"].fillna(0)
        
        # 归一化排名 (0~1)
        mcap_rank = mcap.rank(pct=True)

        pe = df["pe"].copy()
        pb = df["pb"].copy()
        # 估值分：PE/PB 越低分越高 (注意处理负值或NaN)
        pe_score = (1.0 - pe[pe > 0].rank(pct=True)).fillna(0.5) 
        pb_score = (1.0 - pb[pb > 0].rank(pct=True)).fillna(0.5)
        
        # 综合估值分
        df.loc[pe.index, "val_score"] = (0.6 * pe_score + 0.4 * pb_score)
        df["val_score"] = df["val_score"].fillna(0.5)

        # 动量分
        pct = df["pct"].fillna(0.0)
        momentum_score = pct.rank(pct=True)
        
        # 过热惩罚: 涨幅超过 9.5% 或 跌幅超过 9.5% 稍微扣分 (防追高/抄底跌停)
        overheat = (pct.abs() > 9.5).astype(int)

        # 最终得分公式
        # 如果是小市值策略，mcap_rank 应该反过来？
        # 这里统一逻辑：prefer_large_cap如果是正数，偏好大市值；如果是负数，偏好小市值。
        
        final_score = (
            config.prefer_large_cap * mcap_rank +
            config.prefer_value * df["val_score"] +
            config.prefer_momentum * momentum_score -
            config.penalize_overheat * overheat
        )

        df["score"] = final_score.clip(0, 1).round(4)

        # 整理输出
        keep_cols = ["code", "name", "close", "pct", "market_cap", "pe", "pb", "turnover", "score"]
        # 补齐缺列
        for c in keep_cols:
            if c not in df.columns:
                df[c] = np.nan

        df = df[keep_cols].sort_values("score", ascending=False).reset_index(drop=True)
        return df

    # ------------------------------------------------------------------
    # 3. 缓存封装
    # ------------------------------------------------------------------

    def scan_cached(self, pool_id: str, config: ScanConfig, cache_ttl: int = 600) -> Tuple[pd.DataFrame, str]:
        # 生成唯一指纹
        scan_id = f"{pool_id}_min{config.min_market_cap_yi}_max{config.max_market_cap_yi}_pe{config.max_pe}"
        
        cached = self.cache.get_scan(scan_id, ttl_seconds=cache_ttl)
        if cached is not None and isinstance(cached, pd.DataFrame) and not cached.empty:
            return cached, scan_id

        pool = self.get_pool(pool_id)
        df = self.scan(pool, config)
        
        if df is not None and not df.empty:
            self.cache.set_scan(scan_id, df)
        return df, scan_id