# -*- coding: utf-8 -*-
"""
market_scanner.py
=================
五维超脑·市场雷达 (Commercial Pro V12.0 - 全域覆盖版)

【核心职能】
1. **全域扫描**: 覆盖全A股、创业板、主板、核心资产等 7 大战区。
2. **定向爆破**: 接收 AI 战略指令，对命中“金手指”行业的个股给予生存金加分。
3. **多因子量化**: 结合市值、估值、动量、活跃度进行初筛。
"""

from __future__ import annotations
from dataclasses import dataclass, field, fields
from typing import List, Optional, Tuple, Dict
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
    扫描配置参数
    """
    # 量化权重
    prefer_large_cap: float = 0.35
    prefer_value: float = 0.35
    prefer_momentum: float = 0.20
    prefer_active: float = 0.10
    penalize_overheat: float = 0.10
    
    # AI 定向爆破
    target_concepts: List[str] = field(default_factory=list) 
    concept_survival_bonus: float = 0.15 # 命中概念加分
    
    # 硬过滤
    min_market_cap_yi: float = 0.0  
    max_market_cap_yi: Optional[float] = None 
    max_pe: Optional[float] = None  
    name_filter: str = ""           

    def __init__(self, **kwargs):
        # 自动容错初始化
        valid_fields = set([f.name for f in fields(self)])
        for k, v in kwargs.items():
            if k in valid_fields: setattr(self, k, v)

class MarketScanner:
    def __init__(self, engine: DataEngine, cache: Optional[UniverseCache] = None):
        self.engine = engine
        self.cache = cache or engine.cache

    # ------------------------------------------------------------------
    # 1. 策略池构建 (全域覆盖)
    # ------------------------------------------------------------------
    def get_pool(self, pool_id: str) -> List[str]:
        # 尝试缓存
        cached = self.cache.get_pool(pool_id, ttl_seconds=24 * 3600)
        if cached: return [normalize_code(x) for x in cached]

        spot = self.engine.get_spot_snapshot()
        if spot is None or spot.empty: return []

        codes: List[str] = []
        
        # --- 策略分发 ---
        if pool_id == "all_a_shares":
            # 全 A 股 (仅剔除 ST/退市)
            mask_st = spot["name"].str.contains("ST|退", na=False)
            codes = spot[~mask_st]["code"].tolist()

        elif pool_id == "core_assets_top100":
            # 核心资产：市值前 100
            codes = spot.sort_values("market_cap", ascending=False).head(100)["code"].tolist()
            
        elif pool_id == "institutional_top300":
            # 机构重仓：市值前 300
            codes = spot.sort_values("market_cap", ascending=False).head(300)["code"].tolist()
            
        elif pool_id == "growth_gem":
            # 创业板特攻：30 开头
            mask = spot["code"].astype(str).str.startswith("30")
            codes = spot[mask].sort_values("market_cap", ascending=False).head(500)["code"].tolist()
            
        elif pool_id == "sh_main_board":
            # 沪市蓝筹：60 开头
            mask = spot["code"].astype(str).str.match(r"^60[0135]")
            codes = spot[mask].sort_values("market_cap", ascending=False).head(500)["code"].tolist()

        elif pool_id == "sz_main_board":
            # 深市主板/中小板：00 开头 (含002)
            mask = spot["code"].astype(str).str.startswith("00")
            codes = spot[mask].sort_values("market_cap", ascending=False).head(500)["code"].tolist()
            
        elif pool_id == "small_cap_contrarian":
            # 极致博弈：市值 10亿~50亿，非 ST
            mask_st = spot["name"].str.contains("ST|退", na=False)
            mask_cap = (spot["market_cap"] > 10) & (spot["market_cap"] < 50) 
            codes = spot[~mask_st & mask_cap].sort_values("market_cap", ascending=True).head(500)["code"].tolist()
            
        else:
            # 默认兜底
            codes = spot.sort_values("market_cap", ascending=False).head(500)["code"].tolist()

        codes = [normalize_code(x) for x in codes if str(x).strip()]
        self.cache.set_pool(pool_id, codes)
        return codes

    # ------------------------------------------------------------------
    # 2. 扫描核心逻辑
    # ------------------------------------------------------------------
    def scan(self, pool_codes: List[str], config: Optional[ScanConfig] = None) -> pd.DataFrame:
        config = config or ScanConfig()
        spot = self.engine.get_spot_snapshot()
        if spot is None or spot.empty: return pd.DataFrame()

        # 过滤池
        codes = [normalize_code(x) for x in pool_codes]
        df = spot[spot["code"].isin(codes)].copy()
        if df.empty: return pd.DataFrame()

        # 硬过滤
        if config.min_market_cap_yi > 0: df = df[df["market_cap"] >= config.min_market_cap_yi]
        if config.max_market_cap_yi: df = df[df["market_cap"] <= config.max_market_cap_yi]
        if config.max_pe: df = df[(df["pe"] > 0) & (df["pe"] <= config.max_pe)]
        if config.name_filter: df = df[~df["name"].str.contains(config.name_filter, na=False)]
        
        if df.empty: return pd.DataFrame()

        # 补全行业
        sector_map = getattr(self.engine, "sector_map", {})
        if not sector_map:
            self.engine._ensure_sector_map()
            sector_map = getattr(self.engine, "sector_map", {})
        df["sector"] = df["code"].map(sector_map).fillna("其他")

        # 量化打分
        mcap_rank = df["market_cap"].fillna(0).rank(pct=True)
        size_score = mcap_rank if config.prefer_large_cap >= 0 else (1.0 - mcap_rank)
        
        pe_score = pd.Series(0.0, index=df.index)
        pe_valid = df["pe"] > 0
        pe_score[pe_valid] = 1.0 - df.loc[pe_valid, "pe"].rank(pct=True)

        mom_score = df["pct"].fillna(0.0).rank(pct=True)
        
        vol = df["vol_ratio"].fillna(0).rank(pct=True)
        flow = df.get("main_net_inflow", pd.Series(0, index=df.index)).fillna(0).rank(pct=True)
        active_score = (0.6 * vol + 0.4 * flow)

        # 生存金 (Concept Bonus)
        survival_score = pd.Series(0.0, index=df.index)
        if config.target_concepts:
            def check_hit(row):
                s = str(row.get('sector', ''))
                n = str(row.get('name', ''))
                for t in config.target_concepts:
                    if t in s or t in n: return 1.0
                return 0.0
            survival_score = df.apply(check_hit, axis=1) * config.concept_survival_bonus

        # 综合加权
        raw_score = (
            abs(config.prefer_large_cap) * size_score +
            config.prefer_value * pe_score +
            config.prefer_momentum * mom_score +
            config.prefer_active * active_score +
            survival_score
        )
        df["score"] = raw_score.round(4)
        
        out_cols = ["code", "name", "sector", "close", "pct", "market_cap", "pe", "vol_ratio", "score"]
        if "main_net_inflow" in df.columns: out_cols.append("main_net_inflow")
        for c in out_cols:
            if c not in df.columns: df[c] = np.nan
            
        return df[out_cols].sort_values("score", ascending=False).reset_index(drop=True)

    def scan_cached(self, pool_id: str, config: ScanConfig, cache_ttl: int = 300) -> Tuple[pd.DataFrame, str]:
        concepts_str = "-".join(sorted(config.target_concepts))
        scan_id = f"{pool_id}_v12_c{concepts_str}"
        cached = self.cache.get_scan(scan_id, ttl_seconds=cache_ttl)
        if cached is not None and not cached.empty:
            return cached, scan_id
        pool = self.get_pool(pool_id)
        df = self.scan(pool, config)
        if df is not None and not df.empty:
            self.cache.set_scan(scan_id, df)
        return df, scan_id