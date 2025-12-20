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

from logging_utils import get_data_logger, make_result, build_error, FetchResult
from data_sources.financial_eastmoney import fetch_financial_indicator_em

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


def _standardize_code(code: str) -> str:
    code = str(code).strip()
    code = code.replace(".SH", "").replace(".SZ", "").replace(".BJ", "").replace("sh", "").replace("sz", "").replace("bj", "")
    if code.isdigit() and len(code) < 6:
        code = code.zfill(6)
    market = "SZ"
    if code.startswith("6"):
        market = "SH"
    elif code.startswith(("8", "4")):
        market = "BJ"
    return f"{code}.{market}"


class FundamentalEngine:
    def __init__(self, cache: Any = None):
        self.cache = cache
        self._mem_cache: Dict[str, Any] = {}
        self.logger = get_data_logger("superquant.fundamental")

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
    def get_financial_snapshot_structured(self, code: str) -> FetchResult:
        """
        返回：
        {
          roe, gross_margin, net_margin, revenue_yoy, profit_yoy,
          debt_ratio, ocf_yoy, eps, pe, pb,
          fundamental_quality, fundamental_growth
        }
        """
        code_std = _standardize_code(code)
        ck = f"fin:snap:{code_std}"
        cached = self._cache_get(ck)
        if cached is not None:
            return FetchResult(data=cached, ok=True, source="cache", cache_hit=True)

        errors: List[Dict[str, str]] = []
        out: Dict[str, Any] = {}

        fin = self._fetch_financial_from_ak(code_std, errors)
        source = "akshare" if fin else ""

        if not fin:
            fin = self._fetch_financial_from_eastmoney(code_std, errors)
            if fin:
                source = "eastmoney"

        if not fin:
            fin = self._financial_offline_stub(code_std)
            if fin:
                source = "offline_stub"
                errors.append(build_error("offline_stub", "used", "实时源失败，使用内置示例财务数据，可能过期"))

        if not fin:
            errors.append(build_error("financial", "unavailable", "财务数据源均失败"))
            return FetchResult(data={}, ok=False, source="unavailable", fallback_used=True, errors=errors)

        out.update(fin)

        roe = _safe_float(out.get("roe"), 0.0)
        gm = _safe_float(out.get("gross_margin"), 0.0)
        nm = _safe_float(out.get("net_margin"), 0.0)
        debt = _safe_float(out.get("debt_ratio"), 60.0)
        rev = _safe_float(out.get("revenue_yoy"), 0.0)
        prof = _safe_float(out.get("profit_yoy"), 0.0)

        quality = 0.45 * _tanh01(roe, 12.0) + 0.35 * _tanh01(gm, 25.0) + 0.2 * _tanh01(nm, 15.0)
        quality = quality * (1.0 - 0.25 * _tanh01(debt - 60.0, 15.0))
        growth = 0.55 * _tanh01(rev, 25.0) + 0.45 * _tanh01(prof, 30.0)

        out["fundamental_quality"] = _clip01(quality)
        out["fundamental_growth"] = _clip01(growth)

        filled = [k for k in ["revenue", "net_profit", "gross_margin", "net_margin", "roe", "roa", "debt_ratio", "op_cashflow"] if out.get(k) is not None]
        ok_flag = len(filled) >= 5 and bool(out.get("report_date"))
        self._cache_set(ck, out, ttl=3600)
        self.logger.info("financial snapshot cached for %s via %s", code_std, source or "unknown")
        return FetchResult(data=out, ok=ok_flag, source=source or "unknown", fallback_used=not source or source == "offline_stub", errors=errors)

    def get_financial_snapshot(self, code: str) -> Dict[str, Any]:
        return self.get_financial_snapshot_structured(code).data

    def _map_financial_row(self, row: Dict[str, Any]) -> Dict[str, Any]:
        mapping = {
            "report_date": ["报告期", "报告日期", "reportdate", "fdate"],
            "revenue": ["营业收入", "营业总收入(元)", "totaloperatereve", "营业总收入"],
            "net_profit": ["净利润", "netprofit", "归母净利润"],
            "gross_margin": ["销售毛利率(%)", "毛利率(%)", "毛利率", "grossprofit_margin"],
            "net_margin": ["销售净利率(%)", "净利率(%)", "净利率", "netprofit_margin"],
            "roe": ["净资产收益率(%)", "ROE(%)", "净资产收益率", "weightedroe", "roe"],
            "roa": ["总资产报酬率(%)", "资产报酬率(%)", "资产报酬率", "roa2_weighted", "roa"],
            "debt_ratio": ["资产负债率(%)", "资产负债率", "debtratio"],
            "op_cashflow": ["经营活动产生的现金流量净额", "经营现金流量净额", "经营活动现金流量净额", "经营现金流", "ocfps"],
            "profit_yoy": ["净利润增长率(%)", "净利润同比增长率(%)", "净利润增长率", "netprofit_yoy"],
            "revenue_yoy": ["营业收入增长率(%)", "营业收入同比增长率(%)", "营业收入增长率", "ystz"],
            "eps": ["每股收益(元)", "eps", "basiceps", "基本每股收益"],
        }

        out: Dict[str, Any] = {k: None for k in [
            "report_date",
            "revenue",
            "net_profit",
            "gross_margin",
            "net_margin",
            "roe",
            "roa",
            "debt_ratio",
            "op_cashflow",
            "profit_yoy",
            "revenue_yoy",
            "eps",
        ]}

        def pick(keys: List[str]) -> Any:
            for k in keys:
                if k in row and row[k] not in (None, "", "--"):
                    return row[k]
            return None

        for target, keys in mapping.items():
            out[target] = _safe_float(pick(keys), None) if target != "report_date" else pick(keys)

        if not out.get("net_margin") and out.get("net_profit") and out.get("revenue"):
            try:
                out["net_margin"] = float(out["net_profit"]) / float(out["revenue"]) * 100.0
            except Exception:
                pass
        return out

    def _fetch_financial_from_ak(self, code_std: str, errors: List[Dict[str, str]]) -> Optional[Dict[str, Any]]:
        if ak is None:
            errors.append(build_error("akshare", "missing", "AkShare 未安装"))
            return None
        df = None
        try:
            df = ak.stock_financial_analysis_indicator(symbol=code_std)
        except Exception as e:
            errors.append(build_error("akshare", "exception", str(e)))

        if df is None or getattr(df, "empty", True):
            try:
                df = ak.stock_financial_analysis_indicator_em(symbol=code_std)
            except Exception as e:
                errors.append(build_error("akshare_em", "exception", str(e)))

        if df is not None and not getattr(df, "empty", True):
            try:
                row = df.iloc[-1].to_dict()
                return self._map_financial_row(row)
            except Exception as e:
                errors.append(build_error("akshare", "parse", str(e)))
        else:
            errors.append(build_error("akshare", "empty", "财务指标返回空"))
        return None

    def _fetch_financial_from_eastmoney(self, code_std: str, errors: List[Dict[str, str]]) -> Optional[Dict[str, Any]]:
        try:
            df = fetch_financial_indicator_em(code_std)
            if df is not None and not df.empty:
                row = df.iloc[0].to_dict()
                return self._map_financial_row(row)
            errors.append(build_error("eastmoney", "empty", "东财财务指标为空"))
        except Exception as e:
            errors.append(build_error("eastmoney", "exception", str(e)))
        return None

    def _financial_offline_stub(self, code_std: str) -> Optional[Dict[str, Any]]:
        samples = {
            "600519.SH": {
                "report_date": "2024-09-30",
                "revenue": 1067.5 * 1e8,
                "net_profit": 527.0 * 1e8,
                "gross_margin": 91.0,
                "net_margin": 49.0,
                "roe": 25.0,
                "roa": 18.0,
                "debt_ratio": 36.0,
                "op_cashflow": 550.0 * 1e8,
                "profit_yoy": 15.0,
                "revenue_yoy": 17.0,
                "eps": 40.0,
            },
            "000001.SZ": {
                "report_date": "2024-09-30",
                "revenue": 1500.0 * 1e8,
                "net_profit": 120.0 * 1e8,
                "gross_margin": 28.0,
                "net_margin": 12.0,
                "roe": 11.5,
                "roa": 0.9,
                "debt_ratio": 86.0,
                "op_cashflow": 300.0 * 1e8,
                "profit_yoy": 6.0,
                "revenue_yoy": 5.0,
                "eps": 1.8,
            },
        }
        return samples.get(code_std)

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
