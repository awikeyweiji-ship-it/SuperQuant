# -*- coding: utf-8 -*-
"""
slow_factor_engine.py
=====================
把“慢变量”变成【可计算、可记录、可回测】的因子，并进入评分体系。

设计目标（V1）：
- Policy 强度/持续性（基于宏观战略输出 + 日度记录）
- Demand 需求空间（基于财务增长 + 行业主线加成）
- Substitution 国产替代/自主可控（基于行业标签 + 研发强度 + 关键词证据）
- Pricing 市场定价/预期反映（基于估值相对分位 + 价格位置）
- Info 信息面是否充分（基于热度/拥挤度：成交/波动/热榜）

⚠️ 说明：
1) “可回测”= 在你开始收集后，因子会按日落盘（FactorStore），回测时只读取 <= 模拟日期的数据，避免未来函数。
2) 如果某类数据缺失，会回退到中性 0.5，不会让系统崩掉。
"""
from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass
from datetime import datetime, date
from pathlib import Path
from typing import Any, Dict, List, Optional, Iterable, Tuple

import pandas as pd
import numpy as np

from universe_cache import UniverseCache

# ------------------------------ helpers ------------------------------

def _now_date_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")

def _to_date_str(d: Any) -> str:
    if d is None:
        return _now_date_str()
    if isinstance(d, str):
        # keep yyyy-mm-dd
        return d[:10]
    if isinstance(d, datetime):
        return d.strftime("%Y-%m-%d")
    if isinstance(d, date):
        return d.strftime("%Y-%m-%d")
    try:
        return pd.to_datetime(d).strftime("%Y-%m-%d")
    except Exception:
        return _now_date_str()

def _clip01(x: float) -> float:
    try:
        return float(max(0.0, min(1.0, x)))
    except Exception:
        return 0.5

def _safe_float(x: Any, default: float = 0.0) -> float:
    try:
        if x is None or (isinstance(x, float) and np.isnan(x)):
            return float(default)
        return float(x)
    except Exception:
        return float(default)

def _sigmoid(x: float) -> float:
    try:
        return 1.0 / (1.0 + math.exp(-x))
    except Exception:
        return 0.5

def _tanh01(x: float, scale: float = 20.0) -> float:
    # map growth% to [0,1], centered at 0
    try:
        return _clip01(0.5 + 0.5 * math.tanh(float(x) / float(scale)))
    except Exception:
        return 0.5

def _contains_any(text: str, kws: Iterable[str]) -> bool:
    if not text:
        return False
    t = str(text)
    return any(kw in t for kw in kws)

# ------------------------------ constants ------------------------------

POLICY_KEYWORDS = [
    "政策", "发改委", "国务院", "财政", "央行", "降准", "降息", "MLF", "逆回购",
    "专项债", "国债", "补贴", "规划", "试点", "指导意见", "会议", "经济工作会议",
    "新质生产力", "产业", "稳增长", "扩内需"
]

SUBSTITUTION_KEYWORDS = [
    "国产替代", "进口替代", "自主可控", "国产化", "信创", "自主研发", "自主",
    "卡脖子", "替代", "去IOE", "国产芯片", "国产操作系统"
]

# 粗粒度行业标签（可按需扩展）
SECTOR_SUBSTITUTION_BONUS = {
    "半导体": 0.85,
    "信创": 0.85,
    "软件": 0.75,
    "军工": 0.75,
    "高端装备": 0.70,
    "工业母机": 0.80,
    "新能源": 0.65,
    "汽车": 0.60,
    "医药": 0.55,
}

# ------------------------------ FactorStore ------------------------------

@dataclass
class FactorStoreConfig:
    filename: str = "slow_factors_store.parquet"
    max_rows: int = 400000  # 简单保护：避免无限膨胀

class FactorStore:
    """日度因子落盘：用于后续无未来函数回测。"""
    def __init__(self, cache: UniverseCache, cfg: Optional[FactorStoreConfig] = None):
        self.cache = cache
        self.cfg = cfg or FactorStoreConfig()
        self.dir = Path(self.cache.cache_dir) / "factors"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.path_parquet = self.dir / self.cfg.filename
        self.path_csv = self.dir / self.cfg.filename.replace(".parquet", ".csv")

    def _load(self) -> pd.DataFrame:
        if self.path_parquet.exists():
            try:
                return pd.read_parquet(self.path_parquet)
            except Exception:
                pass
        if self.path_csv.exists():
            try:
                return pd.read_csv(self.path_csv)
            except Exception:
                pass
        return pd.DataFrame()

    def _save(self, df: pd.DataFrame) -> None:
        # 裁剪
        if len(df) > self.cfg.max_rows:
            df = df.tail(self.cfg.max_rows).copy()
        # 尝试 parquet
        try:
            df.to_parquet(self.path_parquet, index=False)
            return
        except Exception:
            pass
        # fallback csv
        try:
            df.to_csv(self.path_csv, index=False, encoding="utf-8-sig")
        except Exception:
            # 最坏情况：不影响主流程
            return

    def append_many(self, records: List[Dict[str, Any]]) -> None:
        if not records:
            return
        try:
            new_df = pd.DataFrame(records)
            if new_df.empty:
                return
            df = self._load()
            df = pd.concat([df, new_df], ignore_index=True)
            # 去重：同日同股保留最后一条
            if "date" in df.columns and "code" in df.columns:
                df = df.sort_values(["date", "code"]).drop_duplicates(["date", "code"], keep="last")
            self._save(df)
        except Exception:
            return

    def query_asof(self, codes: List[str], as_of: Any) -> pd.DataFrame:
        """取 <= as_of 的最新一条因子快照（按 code）。"""
        if not codes:
            return pd.DataFrame()
        as_of_str = _to_date_str(as_of)
        df = self._load()
        if df.empty or "date" not in df.columns or "code" not in df.columns:
            return pd.DataFrame()
        try:
            df["date"] = df["date"].astype(str).str.slice(0, 10)
            sub = df[df["code"].isin(codes) & (df["date"] <= as_of_str)].copy()
            if sub.empty:
                return pd.DataFrame()
            sub = sub.sort_values(["code", "date"])
            last = sub.groupby("code").tail(1)
            return last
        except Exception:
            return pd.DataFrame()

    def sector_policy_persistence(self, sector: str, as_of: Any, lookback_days: int = 30) -> float:
        """对指定行业的 policy_strength 做指数衰减均值，作为持续性。"""
        sector = (sector or "").strip()
        if not sector:
            return 0.5
        as_of_str = _to_date_str(as_of)
        df = self._load()
        if df.empty:
            return 0.5
        if not {"date","sector","policy_strength"}.issubset(set(df.columns)):
            return 0.5
        try:
            df["date"] = df["date"].astype(str).str.slice(0,10)
            sub = df[(df["sector"].astype(str) == sector) & (df["date"] <= as_of_str)][["date","policy_strength"]].copy()
            if sub.empty:
                return 0.5
            sub = sub.sort_values("date").tail(lookback_days)
            vals = sub["policy_strength"].astype(float).values
            # 指数衰减：越近权重越高
            n = len(vals)
            w = np.exp(-np.linspace(n-1, 0, n) / max(1.0, n/6.0))
            w = w / (w.sum() + 1e-9)
            return float(np.dot(vals, w))
        except Exception:
            return 0.5

# ------------------------------ SlowFactorEngine ------------------------------

class SlowFactorEngine:
    def __init__(self, cache: UniverseCache):
        self.cache = cache
        self.store = FactorStore(cache)

    # --------- internal scoring blocks ---------

    def _policy_strength(self, sector: str, macro_report: Optional[Dict[str, Any]], alt_report: Optional[Dict[str, Any]]) -> Tuple[float, List[str]]:
        ev: List[str] = []
        sector = sector or ""
        score = 0.5

        if macro_report:
            primary = macro_report.get("primary_sectors") or []
            conf = _safe_float(macro_report.get("confidence", 0.5), 0.5)
            hit = False
            for s in primary:
                if not s:
                    continue
                if (s in sector) or (sector and sector in str(s)):
                    hit = True
                    ev.append(f"宏观主线命中: {s} (conf={conf:.2f})")
                    break
            score = 0.40 + (0.50 * conf if hit else 0.15 * conf)
        else:
            # fallback: 从新闻标题里抓政策词命中
            titles: List[str] = []
            if alt_report:
                for it in (alt_report.get("macro_news") or []):
                    titles.append(str(it.get("title","")))
                for it in (alt_report.get("corporate_news") or []):
                    titles.append(str(it.get("title","")))
            hits = sum(1 for t in titles if _contains_any(t, POLICY_KEYWORDS))
            if hits > 0:
                ev.append(f"政策新闻命中: {hits} 条")
            score = _sigmoid((hits - 1.5) / 1.5)  # hits=0 => ~0.27, hits=3 => ~0.73
            score = 0.35 + 0.65 * score

        return _clip01(score), ev

    def _demand_space(self, fin: Dict[str, Any], sector: str, macro_report: Optional[Dict[str, Any]]) -> Tuple[float, List[str]]:
        ev: List[str] = []
        rev = _safe_float(fin.get("revenue_yoy", 0.0), 0.0)
        prof = _safe_float(fin.get("profit_yoy", 0.0), 0.0)
        # 需求空间：用收入/利润增速的“慢变量”proxy
        base = 0.6 * _tanh01(rev, 25.0) + 0.4 * _tanh01(prof, 30.0)
        ev.append(f"营收YoY={rev:.1f}% 利润YoY={prof:.1f}%")

        # 行业主线加成
        if macro_report:
            primary = macro_report.get("primary_sectors") or []
            if any((p in (sector or "")) or ((sector or "") and (sector in str(p))) for p in primary if p):
                base = min(1.0, base + 0.10)
                ev.append("行业处于宏观主线 -> 需求空间+0.10")

        return _clip01(base), ev

    def _substitution(self, sector: str, fin: Dict[str, Any], alt_report: Optional[Dict[str, Any]]) -> Tuple[float, List[str]]:
        ev: List[str] = []
        sector = sector or ""
        # 行业标签基础分
        base = 0.45
        for k, v in SECTOR_SUBSTITUTION_BONUS.items():
            if k in sector:
                base = max(base, float(v))
                ev.append(f"行业标签命中: {k} -> base={base:.2f}")
                break

        # 研发强度（如可获得）
        rd_ratio = _safe_float(fin.get("rd_ratio", 0.0), 0.0)  # %
        if rd_ratio > 0:
            # 研发费用率 0~20% 映射 0.45~0.85
            rd_score = _clip01(0.45 + 0.02 * min(20.0, rd_ratio))
            base = 0.6 * base + 0.4 * rd_score
            ev.append(f"研发费用率={rd_ratio:.2f}% -> rd_score={rd_score:.2f}")

        # 新闻关键词证据
        titles: List[str] = []
        if alt_report:
            for it in (alt_report.get("corporate_news") or []):
                titles.append(str(it.get("title","")))
        hits = sum(1 for t in titles if _contains_any(t, SUBSTITUTION_KEYWORDS))
        if hits > 0:
            bump = min(0.12, 0.05 * hits)
            base = min(1.0, base + bump)
            ev.append(f"国产替代关键词命中: {hits} 条 -> +{bump:.2f}")

        return _clip01(base), ev

    def _market_pricing(self, spot: Dict[str, Any], kline_260: Optional[pd.DataFrame], sector_pe_median: Optional[float]) -> Tuple[float, List[str]]:
        ev: List[str] = []
        pe = _safe_float(spot.get("pe", 0.0), 0.0)
        # 估值相对（低估更好）
        val_score = 0.5
        if pe > 0 and sector_pe_median and sector_pe_median > 0:
            rel = pe / sector_pe_median
            # rel<1 低估 -> 高分
            val_score = _clip01(1.0 - 0.5 * math.tanh((rel - 1.0) / 0.6))
            ev.append(f"PE={pe:.1f} 行业中位PE={sector_pe_median:.1f} rel={rel:.2f}")
        elif pe > 0:
            # 没行业参照：用阈值
            val_score = _clip01(1.0 - 0.03 * min(30.0, max(0.0, pe - 10.0)))
            ev.append(f"PE={pe:.1f} (无行业参照)")
        else:
            ev.append("PE缺失 -> 中性")

        # 价格位置：越靠近区间底部越有赔率（过高=预期已满）
        pos_score = 0.5
        if isinstance(kline_260, pd.DataFrame) and not kline_260.empty and "close" in kline_260.columns:
            closes = kline_260["close"].astype(float).values
            lo, hi = float(np.nanmin(closes)), float(np.nanmax(closes))
            last = float(closes[-1])
            if hi > lo:
                pos = (last - lo) / (hi - lo + 1e-9)
                # pos 越低越好：pos_score=1-pos
                pos_score = _clip01(1.0 - pos)
                ev.append(f"价格位置pos={pos:.2f} (0低位-1高位)")
        else:
            ev.append("价格区间缺失 -> 中性")

        score = 0.55 * val_score + 0.45 * pos_score
        return _clip01(score), ev

    def _info_priced_in(self, row: Dict[str, Any], hotlist: Optional[List[str]] = None, ranks: Optional[Dict[str, float]] = None) -> Tuple[float, List[str]]:
        """
        返回“信息是否充分/预期是否拥挤”的程度（0=信息不充分/未拥挤，1=高度拥挤/可能已price-in）
        """
        ev: List[str] = []
        code = str(row.get("code",""))
        hotlist = hotlist or []
        # rank-based（批量计算更准）
        if ranks and code in ranks:
            priced = _clip01(ranks[code])
            if code in hotlist:
                priced = min(1.0, priced + 0.08)
                ev.append("热榜命中 -> 拥挤度+0.08")
            return priced, ev

        # 单股fallback：用阈值
        vol_ratio = _safe_float(row.get("vol_ratio", 0.0), 0.0)
        pct = abs(_safe_float(row.get("pct", 0.0), 0.0))
        priced = 0.40
        if vol_ratio >= 2.0: priced += 0.20; ev.append(f"量比高({vol_ratio:.2f})")
        if pct >= 6.0: priced += 0.15; ev.append(f"涨跌幅波动大(|{pct:.1f}%|)")
        if code in hotlist: priced += 0.10; ev.append("热榜命中")
        return _clip01(priced), ev

    # --------- public APIs ---------

    def compute_single(
        self,
        code: str,
        sector: str,
        spot: Dict[str, Any],
        fin: Dict[str, Any],
        kline_260: Optional[pd.DataFrame] = None,
        macro_report: Optional[Dict[str, Any]] = None,
        alt_report: Optional[Dict[str, Any]] = None,
        as_of: Any = None,
        sector_pe_median: Optional[float] = None,
        hotlist: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        as_of_str = _to_date_str(as_of)
        evidence: Dict[str, List[str]] = {}

        pol, ev1 = self._policy_strength(sector, macro_report, alt_report)
        evidence["policy"] = ev1

        # persistence 用 store 的行业时间序列
        pers = self.store.sector_policy_persistence(sector, as_of_str)
        if pers != 0.5:
            evidence.setdefault("policy", []).append(f"政策持续性(指数衰减)={pers:.2f}")

        dem, ev2 = self._demand_space(fin, sector, macro_report)
        evidence["demand"] = ev2

        sub, ev3 = self._substitution(sector, fin, alt_report)
        evidence["substitution"] = ev3

        pricing, ev4 = self._market_pricing(spot, kline_260, sector_pe_median)
        evidence["pricing"] = ev4

        info, ev5 = self._info_priced_in({**spot, "code": code}, hotlist=hotlist)
        evidence["info"] = ev5

        # composite（慢变量总分，高=更适合“现在建仓”）
        # info 是“拥挤度”，需要反向
        slow_score = (
            0.25 * pol +
            0.15 * pers +
            0.20 * dem +
            0.15 * sub +
            0.15 * pricing +
            0.10 * (1.0 - info)
        )
        slow_score = _clip01(slow_score)

        return {
            "version": "slow_factors_v1",
            "as_of": as_of_str,
            "policy_strength": float(pol),
            "policy_persistence": float(pers),
            "demand_space": float(dem),
            "domestic_substitution": float(sub),
            "market_pricing": float(pricing),
            "info_priced_in": float(info),
            "slow_score": float(slow_score),
            "evidence": evidence,
        }

    def enrich_market_df(
        self,
        market_df: pd.DataFrame,
        engine: Any,
        macro_report: Optional[Dict[str, Any]] = None,
        logic_report: Optional[Dict[str, Any]] = None,
        hotlist: Optional[List[str]] = None,
        as_of: Any = None,
        topk: int = 120
    ) -> pd.DataFrame:
        """
        对市场扫描结果做批量慢变量增强（只对 topk 做重计算，其余默认0.5）。
        - 市场/拥挤度部分用 rank（更稳定）
        - 价格位置用 K 线（相对慢，控制 topk）
        - 财务/研发用缓存（24h）
        """
        if market_df is None or market_df.empty:
            return market_df

        df = market_df.copy()
        df["slow_score"] = 0.5
        df["policy_strength"] = 0.5
        df["policy_persistence"] = 0.5
        df["demand_space"] = 0.5
        df["domestic_substitution"] = 0.5
        df["market_pricing"] = 0.5
        df["info_priced_in"] = 0.5
        df["slow_evidence"] = ""

        hotlist = hotlist or []
        as_of_str = _to_date_str(as_of)

        # -------- ranks for crowdedness (info) --------
        # 综合“热度/拥挤”proxy：量比、涨跌幅绝对值、资金流
        tmp = df.copy()
        if "main_net_inflow" not in tmp.columns:
            tmp["main_net_inflow"] = 0.0
        r_vol = tmp["vol_ratio"].fillna(0).rank(pct=True)
        r_abs = tmp["pct"].fillna(0).abs().rank(pct=True)
        r_flow = tmp["main_net_inflow"].fillna(0).rank(pct=True)
        crowded = (0.45 * r_vol + 0.35 * r_abs + 0.20 * r_flow).clip(0,1)
        ranks = {str(c): float(v) for c, v in zip(tmp["code"].astype(str).tolist(), crowded.tolist())}

        # -------- sector PE median (for pricing) --------
        sector_pe_median_map: Dict[str, float] = {}
        try:
            pe_df = tmp[(tmp["pe"] > 0) & tmp["sector"].notna()][["sector","pe"]].copy()
            if not pe_df.empty:
                sector_pe_median_map = pe_df.groupby("sector")["pe"].median().to_dict()
        except Exception:
            sector_pe_median_map = {}

        # -------- choose heavy calc subset --------
        work = df.sort_values("fused_score" if "fused_score" in df.columns else "score", ascending=False).head(int(topk)).copy()

        records: List[Dict[str, Any]] = []

        for i, row in work.iterrows():
            code = str(row.get("code",""))
            sector = str(row.get("sector",""))
            # spot row is row itself (close/pe/pct/vol_ratio/flow)
            spot = {
                "code": code,
                "close": row.get("close"),
                "pct": row.get("pct"),
                "pe": row.get("pe"),
                "market_cap": row.get("market_cap"),
                "vol_ratio": row.get("vol_ratio"),
                "main_net_inflow": row.get("main_net_inflow", 0.0),
            }
            # financial (cached)
            fin = engine.get_financial_features(code) or {}
            # K线（用于价格位置）
            try:
                k260 = engine.get_kline(code, freq="daily", limit=260)
            except Exception:
                k260 = None

            # policy strength uses macro_report + sector match
            pol, _ = self._policy_strength(sector, macro_report, alt_report=None)
            pers = self.store.sector_policy_persistence(sector, as_of_str)
            dem, _ = self._demand_space(fin, sector, macro_report)
            sub, _ = self._substitution(sector, fin, alt_report=None)
            pricing, _ = self._market_pricing(spot, k260, sector_pe_median_map.get(sector))
            info, ev_info = self._info_priced_in({**spot}, hotlist=hotlist, ranks=ranks)

            # fundamentals & ops (from DataEngine.get_financial_features)
            fq = _clip01(float((fin or {}).get('fundamental_quality', 0.5) or 0.5))
            fg = _clip01(float((fin or {}).get('fundamental_growth', 0.5) or 0.5))
            ops = _clip01(float((fin or {}).get('ops_momentum', 0.5) or 0.5))

            # 商用化：把“财报质量/增长/运营动量”纳入慢变量（可回测/可训练）
            slow_score = (
                0.15 * pol +
                0.10 * pers +
                0.10 * dem +
                0.10 * sub +
                0.10 * pricing +
                0.05 * (1.0 - info) +
                0.20 * fq +
                0.15 * fg +
                0.05 * ops
            )
            slow_score = _clip01(slow_score)

            df.loc[i, "policy_strength"] = pol
            df.loc[i, "policy_persistence"] = pers
            df.loc[i, "demand_space"] = dem
            df.loc[i, "domestic_substitution"] = sub
            df.loc[i, "market_pricing"] = pricing
            df.loc[i, "info_priced_in"] = info
            df.loc[i, "fundamental_quality"] = fq
            df.loc[i, "fundamental_growth"] = fg
            df.loc[i, "ops_momentum"] = ops
            # compatibility aliases
            df.loc[i, "policy_sustain"] = pers
            df.loc[i, "info_sufficiency"] = _clip01(1.0 - info)
            df.loc[i, "slow_score"] = slow_score

            # evidence（短文本，便于 UI）
            brief = []
            if pol >= 0.62: brief.append("🏛️政策强")
            if pers >= 0.62: brief.append("⏳持续性好")
            if dem >= 0.62: brief.append("📈需求强")
            if sub >= 0.62: brief.append("🇨🇳替代强")
            if pricing >= 0.62: brief.append("💎定价好")
            if fq >= 0.62: brief.append("🏦财报强")
            if fg >= 0.62: brief.append("📊成长强")
            if ops >= 0.62: brief.append("🛰️运营强")
            if info >= 0.65: brief.append("🔥拥挤")
            if code in hotlist: brief.append("📌热榜")
            df.loc[i, "slow_evidence"] = " | ".join(brief[:4])

            records.append({
                "date": as_of_str,
                "code": code,
                "sector": sector,
                "policy_strength": float(pol),
                "policy_persistence": float(pers),
                "demand_space": float(dem),
                "domestic_substitution": float(sub),
                "market_pricing": float(pricing),
                "info_priced_in": float(info),
                "slow_score": float(slow_score),
                "meta": json.dumps({"brief": brief, "macro_conf": _safe_float((macro_report or {}).get("confidence", 0.0), 0.0)}, ensure_ascii=False)
            })

        # 落盘（用于可回测）
        self.store.append_many(records)

        return df
