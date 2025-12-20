# -*- coding: utf-8 -*-
"""
fundamental_engine.py
=====================
公司运营 & 财报因子抽取（可落盘、可回测的“慢变量”补强）

核心职责：
- 拉取财务指标（ROE/毛利率/增速/负债/现金流等）
- 拉取公司运营信息（公司简介/主营/公告新闻摘要等）
- 输出标准化 0~1 的因子：fundamental_quality / fundamental_growth / ops_momentum / earnings_surprise(可选)

注意：
- 依赖 AkShare（可选）。没有 AkShare 时返回中性值，不让系统崩。
- 这里的“运营/消息面”只做弱信号（ops_momentum），避免过拟合。
"""

from __future__ import annotations

import math
import time
from typing import Any, Dict, List, Optional

try:
    import akshare as ak  # type: ignore
except Exception:
    ak = None  # type: ignore


def _clip01(x: float) -> float:
    try:
        return float(max(0.0, min(1.0, x)))
    except Exception:
        return 0.5


def _safe_float(x: Any, default: float = 0.0) -> float:
    try:
        if x is None:
            return float(default)
        if isinstance(x, str):
            x = x.replace("%", "").replace(",", "").strip()
        return float(x)
    except Exception:
        return float(default)


def _tanh01(x: float, scale: float = 20.0) -> float:
    # map [-inf, inf] to [0, 1]
    try:
        return 0.5 * (math.tanh(float(x) / float(scale)) + 1.0)
    except Exception:
        return 0.5


class FundamentalEngine:
    def __init__(self, cache: Any = None):
        self.cache = cache
        self._mem_cache: Dict[str, Any] = {}

    def _cache_get(self, key: str):
        if self.cache and hasattr(self.cache, "get"):
            return self.cache.get(key)
        it = self._mem_cache.get(key)
        if not it:
            return None
        ts, val, ttl = it
        if ttl and time.time() - ts > ttl:
            self._mem_cache.pop(key, None)
            return None
        return val

    def _cache_set(self, key: str, val: Any, ttl: int = 3600):
        if self.cache and hasattr(self.cache, "set"):
            try:
                self.cache.set(key, val, ttl=ttl)
                return
            except Exception:
                pass
        self._mem_cache[key] = (time.time(), val, ttl)

    # ----------------------------
    # Financial snapshot
    # ----------------------------
    def get_financial_snapshot(self, code: str) -> Dict[str, Any]:
        """
        返回：
        {
          roe, gross_margin, net_margin, revenue_yoy, profit_yoy,
          debt_ratio, ocf_yoy, eps, pe, pb,
          fundamental_quality, fundamental_growth
        }
        """
        code = str(code).strip()
        ck = f"fin:snap:{code}"
        cached = self._cache_get(ck)
        if cached is not None:
            return cached

        out: Dict[str, Any] = {
            "roe": None,
            "gross_margin": None,
            "net_margin": None,
            "revenue_yoy": None,
            "profit_yoy": None,
            "debt_ratio": None,
            "ocf_yoy": None,
            "eps": None,
            "pe": None,
            "pb": None,
            "fundamental_quality": 0.5,
            "fundamental_growth": 0.5,
        }

        if ak is None:
            self._cache_set(ck, out, ttl=3600)
            return out

        # Try multiple AkShare APIs depending on version
        df = None
        try:
            df = ak.stock_financial_analysis_indicator(symbol=code)
        except Exception:
            try:
                df = ak.stock_financial_analysis_indicator_em(symbol=code)
            except Exception:
                df = None

        if df is not None and hasattr(df, "empty") and not df.empty:
            row = df.iloc[-1].to_dict()  # latest
            # Handle multiple possible column names
            def pick(keys: List[str]) -> Optional[float]:
                for k in keys:
                    if k in row:
                        v = _safe_float(row.get(k), None)
                        return v
                return None

            out["roe"] = pick(["净资产收益率(%)", "ROE(%)", "净资产收益率"])
            out["gross_margin"] = pick(["销售毛利率(%)", "毛利率(%)", "毛利率"])
            out["net_margin"] = pick(["销售净利率(%)", "净利率(%)", "净利率"])
            out["revenue_yoy"] = pick(["营业收入同比增长率(%)", "营收同比(%)", "营业收入增长率(%)"])
            out["profit_yoy"] = pick(["净利润同比增长率(%)", "净利同比(%)", "净利润增长率(%)"])
            out["debt_ratio"] = pick(["资产负债率(%)", "负债率(%)"])
            out["ocf_yoy"] = pick(["经营活动产生的现金流量净额同比增长率(%)", "经营现金流同比(%)"])
            out["eps"] = pick(["基本每股收益", "每股收益"])
            out["pe"] = pick(["市盈率", "PE(TTM)", "PE"])
            out["pb"] = pick(["市净率", "PB", "PB(MRQ)"])

        # Standardized factors
        roe = _safe_float(out["roe"], 0.0)
        gm = _safe_float(out["gross_margin"], 0.0)
        nm = _safe_float(out["net_margin"], 0.0)
        debt = _safe_float(out["debt_ratio"], 60.0)
        rev = _safe_float(out["revenue_yoy"], 0.0)
        prof = _safe_float(out["profit_yoy"], 0.0)

        quality = 0.45 * _tanh01(roe, 12.0) + 0.35 * _tanh01(gm, 25.0) + 0.2 * _tanh01(nm, 15.0)
        # debt higher -> penalty
        quality = quality * (1.0 - 0.25 * _tanh01(debt - 60.0, 15.0))
        growth = 0.55 * _tanh01(rev, 25.0) + 0.45 * _tanh01(prof, 30.0)

        out["fundamental_quality"] = _clip01(quality)
        out["fundamental_growth"] = _clip01(growth)

        self._cache_set(ck, out, ttl=3600)
        return out

    # ----------------------------
    # Corporate ops signals
    # ----------------------------
    def get_corporate_news(self, code: str, limit: int = 20) -> List[Dict[str, Any]]:
        """
        返回近期开盘消息（弱信号，用于 ops_momentum）
        """
        code = str(code).strip()
        ck = f"ops:news:{code}:{limit}"
        cached = self._cache_get(ck)
        if cached is not None:
            return cached

        if ak is None:
            self._cache_set(ck, [], ttl=1800)
            return []

        df = None
        # try popular APIs
        for fn in [
            "stock_news_em",
            "stock_news_cninfo",
            "stock_notice_report",
        ]:
            if hasattr(ak, fn):
                try:
                    df = getattr(ak, fn)(symbol=code)
                    break
                except Exception:
                    df = None

        items: List[Dict[str, Any]] = []
        try:
            if df is not None and hasattr(df, "empty") and not df.empty:
                # try common columns
                cols = list(df.columns)
                # heuristics
                title_col = None
                time_col = None
                source_col = None
                url_col = None
                for c in cols:
                    if "标题" in str(c) or "title" in str(c).lower():
                        title_col = c
                    if "时间" in str(c) or "date" in str(c).lower():
                        time_col = c
                    if "来源" in str(c) or "source" in str(c).lower():
                        source_col = c
                    if "链接" in str(c) or "url" in str(c).lower():
                        url_col = c
                for _, r in df.head(int(limit)).iterrows():
                    items.append({
                        "time": str(r.get(time_col, "")) if time_col else "",
                        "title": str(r.get(title_col, "")) if title_col else "",
                        "source": str(r.get(source_col, "")) if source_col else "",
                        "url": str(r.get(url_col, "")) if url_col else "",
                    })
        except Exception:
            items = []

        self._cache_set(ck, items, ttl=1800)
        return items

    def compute_ops_momentum(self, news: List[Dict[str, Any]]) -> float:
        """
        简易情绪：正面关键词计数 - 负面关键词计数
        """
        if not news:
            return 0.5
        pos = ["中标", "签约", "订单", "增长", "上调", "回购", "增持", "业绩预增", "突破", "新产品", "合作"]
        neg = ["下调", "减持", "处罚", "亏损", "业绩下滑", "诉讼", "停产", "事故", "被立案", "退市", "延期"]
        s = 0
        for it in news[:20]:
            t = (it.get("title") or "")
            if any(k in t for k in pos):
                s += 1
            if any(k in t for k in neg):
                s -= 1
        return _clip01(0.5 + 0.12 * s)
