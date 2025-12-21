# -*- coding: utf-8 -*-
"""
data_engine.py
==============
全息数据引擎 (Commercial Pro V12.1 - 接口修复版)

【修复日志】
1. **修复 AttributeError**: 补回 `get_market_hot_spots` 接口，解决“启动宏观深搜”报错。
2. **多周期K线**: 保持 freq 参数，支持 D(日)/W(周)/M(月) K线数据获取。
3. **数据加固**: 针对 NaN 值进行更严格的清洗。
"""

from __future__ import annotations
import datetime as _dt
import re
import time
import json
import logging
import sys
import requests
from typing import Dict, Any, Optional, List

# 确保优先使用系统 site-packages，避免本地 Windows 版依赖污染
site_paths = [p for p in sys.path if "site-packages" in p]
other_paths = [p for p in sys.path if p not in site_paths and p != ""]
sys.path = site_paths + other_paths + [""]

import pandas as pd
import numpy as np

from logging_utils import get_data_logger, make_result, build_error, FetchResult
from data_sources.financial_eastmoney import fetch_financial_indicator_em
from data_sources.identity_eastmoney import fetch_identity_em
from data_sources.announcement_eastmoney import (
    fetch_announcements_em,
    fetch_announcements_tencent,
    sample_announcements,
)
from data_sources.report_eastmoney import (
    fetch_research_reports_em,
    fetch_research_reports_alt,
    sample_reports,
)
from data_sources.hot_eastmoney import fetch_hot_topics_em, fetch_hot_topics_ak, sample_hot_topics

try:
    import akshare as ak
except ImportError:
    ak = None

from universe_cache import UniverseCache

try:
    from alternative_data import AlternativeDataEngine
except ImportError:
    AlternativeDataEngine = None

try:
    from fundamental_engine import FundamentalEngine
except ImportError:
    FundamentalEngine = None

try:
    from capital_engine import CapitalEngine
except ImportError:
    CapitalEngine = None


def _now_str() -> str:
    return _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def normalize_code(code: str) -> str:
    code = str(code).strip()
    code = re.sub(r"\.(SH|SZ|BJ|sh|sz|bj)$", "", code)
    if code.isdigit() and len(code) < 6:
        code = code.zfill(6)
    return code


def standardize_code(code: str) -> str:
    """统一股票代码为 6 位数字 + 交易所后缀格式 (如 600519.SH)。"""
    code = normalize_code(code)
    market = "SZ"
    if code.startswith("6"):
        market = "SH"
    elif code.startswith(("8", "4")):
        market = "BJ"
    return f"{code}.{market}"


def to_tencent_symbol(code: str) -> str:
    code_std = standardize_code(code)
    plain, market = code_std.split(".")
    prefix = "sz"
    if market == "SH":
        prefix = "sh"
    elif market == "BJ":
        prefix = "bj"
    return f"{prefix}{plain}"


def to_eastmoney_secid(code: str) -> str:
    code_std = standardize_code(code)
    plain, market = code_std.split(".")
    market_flag = "0"
    if market == "SH":
        market_flag = "1"
    return f"{market_flag}.{plain}"

def _safe_float(x: Any, default: float = 0.0) -> float:
    if x is None: return default
    try:
        s = str(x).strip().replace(",", "").replace("%", "")
        if s in ("", "--", "nan", "None", "NaN"): return default
        factor = 1.0
        if "亿" in s: 
            factor = 1e8; s = s.replace("亿", "")
        elif "万" in s: 
            factor = 1e4; s = s.replace("万", "")
        return float(s) * factor
    except: return default


def _to_float_or_none(x: Any) -> Optional[float]:
    try:
        val = _safe_float(x, default=np.nan)
        if pd.isna(val):
            return None
        return float(val)
    except Exception:
        return None


def _retry(func, max_retries: int = 3, base_delay: float = 0.6):
    last_err = None
    for i in range(max_retries):
        try:
            return func()
        except Exception as e:
            last_err = e
            time.sleep(base_delay * (2 ** i))
    if last_err:
        raise last_err

class DataEngine:
    _instance = None
    _printed_logo = False

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(DataEngine, cls).__new__(cls)
        return cls._instance

    def __init__(self, cache: Optional[UniverseCache] = None):
        if hasattr(self, "_initialized"): return
        self._initialized = True
        self.logger = get_data_logger("superquant.data_engine")
        self.cache = cache or UniverseCache()
        self.alt_engine = AlternativeDataEngine(cache=self.cache) if AlternativeDataEngine else None
        # Step5: 财报/运营 + 资本运作 情报引擎
        self.fund_engine = FundamentalEngine(cache=self.cache) if FundamentalEngine else None
        self.capital_engine = CapitalEngine() if CapitalEngine else None

        self.sector_map = {}
        # 行情快照状态（用于 UI/调度自检）
        self.spot_source = ""
        self.spot_is_stale = False
        self.spot_age_sec = None
        if not DataEngine._printed_logo:
            DataEngine._printed_logo = True
            print(f"🚀 [DataEngine V12.1] 引擎就绪 (热点接口已修复)...")

    def _cache_age(self, key: str) -> Optional[float]:
        meta_path = self.cache._meta_path(key)  # type: ignore[attr-defined]
        try:
            if meta_path.exists():
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                ts = float(meta.get("ts", 0))
                return time.time() - ts
        except Exception:
            return None
        return None

    def _market_prefix(self, code: str) -> str:
        code = normalize_code(code)
        if code.startswith('6'): return 'sh'
        if code.startswith(('0','3')): return 'sz'
        if code.startswith(('8','4')): return 'bj'
        return 'sz'

    def _fetch_quote_tencent(self, code: str) -> Dict[str, Any]:
        """腾讯行情兜底，返回原始字段。"""
        code = normalize_code(code)
        try:
            px = self._market_prefix(code)
            q = f's_{px}{code}'
            url = f'https://qt.gtimg.cn/q={q}'
            r = requests.get(url, timeout=8, proxies={"http": None, "https": None})
            txt = (r.text or '').strip()
            if '~' not in txt:
                return {}
            m = re.search(r'"(.*)"', txt)
            payload = m.group(1) if m else txt
            parts = payload.split('~')
            if len(parts) < 30:
                return {}
            name = parts[1].strip()
            price = parts[3].strip()
            pct = parts[5].strip()
            open_px = parts[4].strip()
            preclose = parts[33].strip() if len(parts) > 33 else ""
            high = parts[41].strip() if len(parts) > 41 else ""
            low = parts[42].strip() if len(parts) > 42 else ""
            vol = parts[6].strip()
            amount = parts[37].strip() if len(parts) > 37 else ""
            return {
                'code': code,
                'name': name,
                'price': price,
                'pct_chg': pct,
                'open': open_px,
                'preclose': preclose,
                'high': high,
                'low': low,
                'vol': vol,
                'amount': amount,
                'source': 'tencent'
            }
        except Exception as e:
            self.logger.warning("腾讯行情兜底异常: %s", e)
            return {}

    def _fetch_quote_akshare(self, code_std: str) -> Dict[str, Any]:
        if ak is None:
            return {}
        plain = normalize_code(code_std)
        if hasattr(ak, "stock_zh_a_spot_em"):
            df = self._retry_call(lambda: ak.stock_zh_a_spot_em())
            if df is not None and not df.empty:
                df = df.rename(columns={"代码": "code"})
                row = df[df["code"].astype(str).str.strip() == plain]
                if not row.empty:
                    r = row.iloc[0].to_dict()
                    r["source"] = "akshare"
                    return r
        return {}

    def _fetch_quote_eastmoney(self, code_std: str) -> Dict[str, Any]:
        secid = to_eastmoney_secid(code_std)
        url = "https://push2.eastmoney.com/api/qt/stock/get"
        params = {
            "secid": secid,
            # 增加估值/市值字段，便于财务兜底
            "fields": "f43,f44,f45,f46,f47,f48,f57,f58,f59,f60,f170,f71,f84,f162,f167,f116,f117",
        }
        try:
            r = requests.get(url, params=params, timeout=10, proxies={"http": None, "https": None})
            data = (r.json() or {}).get("data") or {}
            if not data:
                return {}
            return {
                "code": normalize_code(code_std),
                "name": data.get("f58", ""),
                "price": data.get("f43"),
                "open": data.get("f46"),
                "high": data.get("f44"),
                "low": data.get("f45"),
                "preclose": data.get("f60"),
                "pct_chg": data.get("f170"),
                "vol": data.get("f47"),
                "amount": data.get("f48"),
                "turnover": data.get("f84"),
                "pe_ttm": data.get("f162"),
                "pb": data.get("f167"),
                "total_mv": data.get("f116"),
                "float_mv": data.get("f117"),
                "source": "eastmoney_push2",
            }
        except Exception as e:
            self.logger.warning("东财行情兜底异常: %s", e)
            return {}

    def _standardize_quote(self, payload: Dict[str, Any], code_std: str, source: str) -> Dict[str, Any]:
        if not isinstance(payload, dict):
            return {}
        pick = lambda *keys: next((payload.get(k) for k in keys if payload.get(k) not in (None, "", "--")), None)
        price = _to_float_or_none(pick("price", "close", "最新价", "现价"))
        pct = _to_float_or_none(pick("pct", "pct_chg", "涨跌幅"))
        total_mv = _to_float_or_none(pick("total_mv", "总市值", "market_cap"))
        out = {
            "code": code_std,
            "name": pick("name", "名称", "股票名称") or payload.get("code", ""),
            "price": price,
            "pct_chg": pct,
            "vol": _to_float_or_none(pick("vol", "volume", "成交量")),
            "amount": _to_float_or_none(pick("amount", "成交额")),
            "turnover": _to_float_or_none(pick("turnover", "换手率")),
            "high": _to_float_or_none(pick("high", "最高")),
            "low": _to_float_or_none(pick("low", "最低")),
            "open": _to_float_or_none(pick("open", "开盘")),
            "preclose": _to_float_or_none(pick("preclose", "昨收", "昨收价", "前收盘")),
            "pe_ttm": _to_float_or_none(pick("pe_ttm", "petm", "pe")),
            "pb": _to_float_or_none(pick("pb", "市净率")),
            "total_mv": total_mv,
            "float_mv": _to_float_or_none(pick("float_mv", "flow_mv", "流通市值")),
            "source": source,
        }
        if out.get("total_mv"):
            try:
                out["market_cap"] = round(float(out["total_mv"]) / 1e8, 2)
            except Exception:
                out["market_cap"] = None
        else:
            out["market_cap"] = None
        # 若价格为空则视为无效
        if out.get("price") is None:
            return {}
        return out

    def _quote_sample(self, code_std: str) -> Optional[Dict[str, Any]]:
        samples = {
            "600519.SH": {
                "code": "600519.SH",
                "name": "贵州茅台",
                "price": 1600.0,
                "pct_chg": 0.0,
                "vol": 1.0,
                "amount": 1.0,
                "turnover": 0.0,
                "high": 1605.0,
                "low": 1595.0,
                "open": 1600.0,
                "preclose": 1600.0,
                "pe_ttm": 30.0,
                "pb": 10.5,
                "total_mv": 2.0e12,
                "float_mv": 2.0e12,
            },
            "000001.SZ": {
                "code": "000001.SZ",
                "name": "平安银行",
                "price": 10.0,
                "pct_chg": 0.0,
                "vol": 1.0,
                "amount": 1.0,
                "turnover": 0.0,
                "high": 10.1,
                "low": 9.9,
                "open": 10.0,
                "preclose": 10.0,
                "pe_ttm": 5.5,
                "pb": 0.6,
                "total_mv": 2.0e11,
                "float_mv": 2.0e11,
            },
            "601872.SH": {
                "code": "601872.SH",
                "name": "招商港口",
                "price": 16.5,
                "pct_chg": 0.2,
                "vol": 1.0,
                "amount": 1.0,
                "turnover": 0.0,
                "high": 16.8,
                "low": 16.2,
                "open": 16.4,
                "preclose": 16.2,
                "pe_ttm": 12.0,
                "pb": 1.5,
                "total_mv": 1.5e11,
                "float_mv": 1.2e11,
            },
        }
        return samples.get(code_std)

    def _retry_call(self, func, *args, max_retries=2, **kwargs):
        for i in range(max_retries):
            try: return func(*args, **kwargs)
            except: time.sleep(0.5)
        return None

    def _ensure_sector_map(self):
        if self.sector_map: return
        ck = "sector_map_v1"
        cached = self.cache.get(ck, ttl=24*3600*7)
        if cached: self.sector_map = cached
        else: self.sector_map = {} 

    # -------------------------------------
    # 1. 市场热点感知 (修复关键点)
    # -------------------------------------
    def get_market_hot_spots(self) -> List[str]:
        """
        获取全网市场热点 (用于 DeepSearch 素材)
        来源：东财人气榜、资金流向榜
        """
        hot_list = []
        if not ak: return ["Akshare 未安装，无法获取热点"]

        try:
            # 1. 个股人气榜 (Top 5)
            df_pop = self._retry_call(lambda: ak.stock_hot_rank_em())
            if df_pop is not None and not df_pop.empty:
                top_stocks = df_pop.head(5)['symbol'].tolist()
                hot_list.append(f"🔥 人气飙升股: {', '.join(top_stocks)}")

            # 2. 行业资金流 (Top 3)
            df_sec = self._retry_call(lambda: ak.stock_sector_fund_flow_rank(indicator="今日", sector_type="行业资金流"))
            if df_sec is not None and not df_sec.empty:
                if '名称' in df_sec.columns:
                    top_sectors = df_sec.head(3)['名称'].tolist()
                    hot_list.append(f"💰 资金主攻方向: {', '.join(top_sectors)}")

            # 3. 概念涨幅榜 (Top 3)
            df_con = self._retry_call(lambda: ak.stock_board_concept_name_em())
            if df_con is not None and not df_con.empty:
                if '板块名称' in df_con.columns:
                    top_concepts = df_con.head(3)['板块名称'].tolist()
                    hot_list.append(f"🚀 领涨概念: {', '.join(top_concepts)}")

        except Exception as e:
            logging.warning(f"Fetch hot spots failed: {e}")
            
        return hot_list

    # -------------------------------------
    # 2. 基础行情
    # -------------------------------------
    def _fetch_spot_snapshot_eastmoney(self) -> pd.DataFrame:
        """备用通道：直接调用东财 push2 接口获取全市场快照。
        目标：当 AkShare 失效/限流时，系统依旧能拿到“现价/涨跌幅/市值”等核心字段。
        """
        url = "https://push2.eastmoney.com/api/qt/clist/get"
        params = {
            "pn": 1,
            "pz": 8000,
            "po": 1,
            "np": 1,
            "ut": "bd1d9ddb04089700cf9c27f6f7426281",
            "fltt": 2,
            "invt": 2,
            "fid": "f3",
            "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23",
            "fields": "f12,f14,f2,f3,f20,f9,f5,f8,f10,f23,f62",
        }
        headers = {
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json,text/plain,*/*",
            "Referer": "https://quote.eastmoney.com/",
        }
        r = requests.get(url, params=params, headers=headers, timeout=12, proxies={"http": None, "https": None})
        if r.status_code != 200:
            return pd.DataFrame()
        try:
            data = r.json() or {}
        except Exception:
            return pd.DataFrame()
        diff = (data.get("data") or {}).get("diff") or []
        if not diff:
            return pd.DataFrame()
        rows = []
        for it in diff:
            # f12 code, f14 name, f2 close, f3 pct, f20 market cap, f9 pe, f5 volume, f8 turnover, f10 vol_ratio, f23 pb, f62 main inflow
            rows.append({
                "code": str(it.get("f12", "")).strip(),
                "name": str(it.get("f14", "")).strip(),
                "close": float(it.get("f2") or 0.0),
                "pct": float(it.get("f3") or 0.0),
                "market_cap": float(it.get("f20") or 0.0),
                "pe": float(it.get("f9") or 0.0),
                "volume": float(it.get("f5") or 0.0),
                "turnover": float(it.get("f8") or 0.0),
                "vol_ratio": float(it.get("f10") or 0.0),
                "pb": float(it.get("f23") or 0.0),
                "main_net_inflow": float(it.get("f62") or 0.0),
            })
        df = pd.DataFrame(rows)
        df = df[df["code"].str.len() > 0]
        return df

    def get_spot_snapshot(self, ttl_seconds: int = 60) -> pd.DataFrame:
        """
        全市场快照（核心依赖，商用级降级策略）
        1) TTL 内优先缓存
        2) AkShare 多函数尝试
        3) 东财 push2 直连兜底
        4) 若仍失败，返回“历史缓存”（stale），保证 UI 不空白
        """
        self.spot_is_stale = False
        self.spot_source = ""
        self.spot_age_sec = None

        # 1) TTL 缓存（优先）
        cached = self.cache.get_spot_snapshot(ttl_seconds=ttl_seconds)
        if cached is not None and not cached.empty:
            self.spot_source = "cache"
            return cached

        # 工具缺失
        if ak is None and requests is None:
            return pd.DataFrame()

        def _normalize(df: pd.DataFrame) -> pd.DataFrame:
            if df is None or df.empty:
                return pd.DataFrame()
            rename_map = {
                "代码": "code", "名称": "name", "最新价": "close",
                "涨跌幅": "pct", "总市值": "market_cap", "市盈率-动态": "pe",
                "成交量": "volume", "换手率": "turnover", "量比": "vol_ratio",
                "市净率": "pb", "主力净流入": "main_net_inflow"
            }
            df = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns})
            # 兜底列
            for c in ["code", "name", "close", "pct", "market_cap", "pe", "volume", "turnover", "vol_ratio", "pb", "main_net_inflow"]:
                if c not in df.columns:
                    df[c] = 0.0 if c != "name" and c != "code" else ""
            df["code"] = df["code"].astype(str).str.strip()
            df = df[df["code"].str.len() > 0]
            # 数值列清洗
            num_cols = ["close", "pct", "market_cap", "pe", "volume", "turnover", "vol_ratio", "pb", "main_net_inflow"]
            for c in num_cols:
                df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
            return df

        # 2) AkShare 多函数尝试
        if ak is not None:
            providers = []
            if hasattr(ak, "stock_zh_a_spot_em"):
                providers.append(("akshare_em", lambda: ak.stock_zh_a_spot_em()))
            if hasattr(ak, "stock_zh_a_spot"):
                providers.append(("akshare", lambda: ak.stock_zh_a_spot()))
            for name, fn in providers:
                df_raw = self._retry_call(fn, max_retries=2)
                df_norm = _normalize(df_raw)
                if df_norm is not None and not df_norm.empty:
                    self.cache.set_spot_snapshot(df_norm)
                    self.spot_source = name
                    self.logger.info("spot snapshot loaded from %s", name)
                    return df_norm
                else:
                    self.logger.warning("spot snapshot empty via %s", name)

        # 3) 东财 push2 兜底
        try:
            df_em = self._retry_call(self._fetch_spot_snapshot_eastmoney, max_retries=2)
            df_em = _normalize(df_em)
            if df_em is not None and not df_em.empty:
                self.cache.set_spot_snapshot(df_em)
                self.spot_source = "eastmoney_push2"
                self.logger.info("spot snapshot loaded from eastmoney push2 fallback")
                return df_em
        except Exception:
            self.logger.exception("eastmoney push2 snapshot failed")

        # 4) 历史缓存兜底（无 TTL）
        stale = self.cache.get_df("spot_snapshot", ttl=None)
        if stale is not None and not stale.empty:
            self.spot_is_stale = True
            self.spot_source = "stale_cache"
            self.logger.warning("using stale cache for spot snapshot")
            return stale

        self.logger.error("spot snapshot unavailable after all providers")
        return pd.DataFrame()

    def get_spot_row_structured(self, code: str) -> FetchResult:
        code_std = standardize_code(code)
        cache_key = self.cache.key("quote_v1", {"code": code_std})
        errors: List[Dict[str, str]] = []
        cache_age = self._cache_age(cache_key)

        cached = self.cache.get(cache_key, ttl=30)
        if isinstance(cached, dict) and cached:
            return make_result(cached, source=cached.get("source", "cache"), cache_hit=True, cache_age=cache_age)

        providers = [
            ("eastmoney", lambda: self._fetch_quote_eastmoney(code_std)),
            ("tencent", lambda: self._fetch_quote_tencent(code_std)),
        ]

        if ak is not None:
            providers.append(("akshare", lambda: self._fetch_quote_akshare(code_std)))
        else:
            errors.append(build_error("akshare", "skip", "AkShare 未安装/不可用，跳过行情源"))

        for idx, (name, fn) in enumerate(providers):
            try:
                raw = _retry(fn, max_retries=3)
                std = self._standardize_quote(raw, code_std, name)
                if std:
                    self.cache.set(cache_key, std)
                    fallback_used = idx > 0
                    return make_result(std, source=name, fallback_used=fallback_used, errors=errors, cache_hit=False, cache_age=None)
                if name == "akshare" and ak is None:
                    errors.append(build_error(name, "skip", "AkShare 未安装，未尝试"))
                else:
                    errors.append(build_error(name, "empty", f"{name} 行情返回空"))
            except Exception as e:
                errors.append(build_error(name, "exception", str(e)))

        stale = self.cache.get(cache_key, ttl=None)
        if isinstance(stale, dict) and stale:
            errors.append(build_error("quote", "stale_cache", "使用历史缓存，数据可能过期"))
            return make_result(stale, source=stale.get("source", "cache_stale"), fallback_used=True, errors=errors, cache_hit=True, cache_age=cache_age)

        sample = self._quote_sample(code_std)
        if sample:
            errors.append(build_error("quote", "offline_sample", "实时行情不可用，使用离线样本（数据可能过期）"))
            sample["source"] = "offline_sample"
            return make_result(sample, source="offline_sample", fallback_used=True, errors=errors, cache_hit=False)

        errors.append(build_error("quote", "unavailable", "未能获取到单只股票快照"))
        return make_result({}, source="quote", fallback_used=True, errors=errors)

    def get_spot_row(self, code: str) -> Dict[str, Any]:
        return self.get_spot_row_structured(code).data

    # -------------------------------------
    # 3. 身份与行业
    # -------------------------------------
    def get_stock_identity_structured(self, code: str) -> FetchResult:
        code_std = standardize_code(code)
        ck = self.cache.key("identity_v12", {"s": code_std})
        cache_age = self._cache_age(ck)
        cached = self.cache.get(ck, ttl=7 * 24 * 3600)
        if isinstance(cached, dict) and cached:
            return make_result(cached, source="cache", cache_hit=True, cache_age=cache_age)

        errors: List[Dict[str, str]] = []
        data = {"code": code_std, "name": "未知", "sector": "", "concepts": []}

        try:
            spot = self.get_spot_row_structured(code_std)
            if spot.ok and isinstance(spot.data, dict):
                data["name"] = spot.data.get("name", data["name"])
            else:
                errors.extend(spot.errors)
        except Exception as e:
            errors.append(build_error("spot", "exception", str(e)))

        def _ak_identity() -> Dict[str, Any]:
            if ak is None:
                return {}
            try:
                df_info = self._retry_call(lambda: ak.stock_individual_info_em(symbol=code_std))
                if df_info is not None and not df_info.empty:
                    info_dict = dict(zip(df_info.iloc[:, 0], df_info.iloc[:, 1]))
                    sector = str(info_dict.get("行业", "")).strip()
                    concept_str = str(info_dict.get("概念", "")).strip()
                    concepts = [c for c in re.split(r"[，,\s]+", concept_str) if c]
                    if sector or concepts:
                        return {"sector": sector, "concepts": concepts, "source": "akshare_info"}
                errors.append(build_error("akshare", "empty", "行业/概念接口返回空"))
            except Exception as e:
                errors.append(build_error("akshare", "exception", str(e)))
            return {}

        def _offline_identity() -> Dict[str, Any]:
            samples = {
                "600519.SH": {"sector": "白酒", "concepts": ["消费", "贵州国资"], "source": "offline_sample"},
                "000001.SZ": {"sector": "银行", "concepts": ["金融", "深股通"], "source": "offline_sample"},
                "601872.SH": {"sector": "港口航运", "concepts": ["央企国资", "交通运输"], "source": "offline_sample"},
            }
            return samples.get(code_std, {})

        providers = [
            ("eastmoney", lambda: fetch_identity_em(code_std)),
        ]
        if ak is not None:
            providers.append(("akshare", _ak_identity))
        else:
            errors.append(build_error("akshare", "skip", "AkShare 未安装/不可用，跳过行业/概念源"))
        providers.append(("offline_sample", _offline_identity))

        for idx, (name, fn) in enumerate(providers):
            try:
                res = fn()
            except Exception as e:  # noqa: BLE001
                errors.append(build_error(name, "exception", str(e)))
                continue

            if isinstance(res, dict) and (res.get("sector") or res.get("concepts")):
                data["sector"] = res.get("sector") or data.get("sector", "")
                data["concepts"] = res.get("concepts") or data.get("concepts", [])
                data["name"] = res.get("name") or data.get("name", "未知")
                source = res.get("source", name)
                if source == "offline_sample":
                    errors.append(build_error("identity", "offline_sample", "实时身份接口不可用，使用离线样本（可能过期）"))
                self.cache.set(ck, data)
                return make_result(
                    data=data,
                    source=source,
                    fallback_used=idx > 0,
                    errors=errors,
                )

            errors.append(build_error(name, "empty", f"{name} 行业/概念为空"))

        errors.append(build_error("identity", "empty", "行业/概念均为空，身份信息不可用"))
        return make_result({}, source="identity", fallback_used=True, errors=errors)

    def get_stock_identity(self, code: str) -> Dict[str, Any]:
        return self.get_stock_identity_structured(code).data

    # -------------------------------------
    # 4. K线数据 (多周期)
    # -------------------------------------
    def _fetch_kline_akshare(
        self,
        code_plain: str,
        freq: str,
        limit: Optional[int],
        start_date: Optional[str],
        end_date: Optional[str],
    ) -> pd.DataFrame:
        period_map = {"daily": "daily", "weekly": "weekly", "monthly": "monthly"}
        p = period_map.get(freq, "daily")

        kwargs = {"symbol": code_plain, "period": p, "adjust": "qfq"}
        if start_date:
            kwargs["start_date"] = str(start_date)
        if end_date:
            kwargs["end_date"] = str(end_date)

        df = ak.stock_zh_a_hist(**kwargs)
        if df is None or df.empty:
            return pd.DataFrame()

        df = df.rename(columns={"日期": "date", "开盘": "open", "收盘": "close", "最高": "high", "最低": "low", "成交量": "volume"})
        df["date"] = pd.to_datetime(df["date"])
        for col in ["open", "close", "high", "low", "volume"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")

        if limit is not None:
            try:
                df = df.tail(int(limit))
            except Exception:
                pass
        return df

    def _fetch_kline_eastmoney(
        self,
        code_std: str,
        freq: str,
        limit: Optional[int],
    ) -> pd.DataFrame:
        klt_map = {"daily": "101", "weekly": "102", "monthly": "103"}
        klt = klt_map.get(freq, "101")
        secid = to_eastmoney_secid(code_std)
        url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
        params = {
            "secid": secid,
            "klt": klt,
            "fqt": "1",
            "lmt": int(limit) if limit else 1000,
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58",
        }
        delay = 1.0
        last_err: Optional[Exception] = None
        for i in range(3):
            try:
                resp = requests.get(url, params=params, timeout=10, proxies={"http": None, "https": None})
                resp.raise_for_status()
                payload = resp.json()
                klines = payload.get("data", {}).get("klines", []) if isinstance(payload, dict) else []
                if not klines:
                    return pd.DataFrame()
                records = []
                for line in klines:
                    parts = str(line).split(",")
                    if len(parts) < 6:
                        continue
                    records.append({
                        "date": pd.to_datetime(parts[0]),
                        "open": _safe_float(parts[1]),
                        "close": _safe_float(parts[2]),
                        "high": _safe_float(parts[3]),
                        "low": _safe_float(parts[4]),
                        "volume": _safe_float(parts[5]),
                    })
                df = pd.DataFrame(records)
                if limit is not None and not df.empty:
                    df = df.tail(int(limit))
                return df
            except Exception as e:
                last_err = e
                time.sleep(delay)
                delay *= 2
        if last_err:
            raise last_err
        return pd.DataFrame()

    def _offline_stub_kline(self, limit: Optional[int], freq: str) -> pd.DataFrame:
        steps = int(limit) if limit else 60
        if steps < 30:
            steps = 30
        dates = pd.date_range(end=_dt.datetime.today(), periods=steps, freq="B")
        base = np.linspace(80, 95, steps)
        noise = np.random.normal(0, 0.5, steps)
        close = base + noise
        open_px = close - np.random.uniform(0.3, 0.8, steps)
        high = np.maximum(open_px, close) + np.random.uniform(0.1, 0.6, steps)
        low = np.minimum(open_px, close) - np.random.uniform(0.1, 0.6, steps)
        volume = np.random.randint(1e6, 5e6, steps)
        df = pd.DataFrame({
            "date": dates,
            "open": open_px,
            "close": close,
            "high": high,
            "low": low,
            "volume": volume,
        })
        return df.tail(int(limit)) if limit else df

    def get_kline(
        self,
        code: str,
        freq: str = "daily",
        limit: Optional[int] = 250,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> pd.DataFrame:
        res = self.get_kline_structured(code, freq=freq, limit=limit, start_date=start_date, end_date=end_date)
        if hasattr(res.data, "empty"):
            return res.data
        return pd.DataFrame()

    def get_kline_structured(
        self,
        code: str,
        freq: str = "daily",
        limit: Optional[int] = 250,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> FetchResult:
        code_std = standardize_code(code)
        code_plain = normalize_code(code)
        cache_key = f"kline:{code_std}:{freq}"
        errors: List[Dict[str, str]] = []

        cached = self.cache.get_df(cache_key, ttl=3600)
        if cached is not None and not cached.empty:
            return make_result(cached, source="cache", cache_hit=True, cache_age=self._cache_age(cache_key))

        if ak is None:
            errors.append(build_error("akshare", "missing", "AkShare 未安装"))
        else:
            try:
                df = self._retry_call(lambda: self._fetch_kline_akshare(code_plain, freq, limit, start_date, end_date), max_retries=2)
                if df is not None and not df.empty:
                    self.cache.set_df(cache_key, df)
                    return make_result(df, source="akshare", errors=errors)
                errors.append(build_error("akshare", "empty", "K线数据为空"))
            except Exception as e:
                errors.append(build_error("akshare", "exception", str(e)))

        fallback_used = True

        try:
            df_em = self._fetch_kline_eastmoney(code_std, freq, limit)
            if df_em is not None and not df_em.empty:
                self.cache.set_df(cache_key, df_em)
                return make_result(df_em, source="eastmoney", fallback_used=True, errors=errors)
            errors.append(build_error("eastmoney", "empty", "东财K线为空"))
        except Exception as e:
            errors.append(build_error("eastmoney", "exception", str(e)))

        stale = self.cache.get_df(cache_key, ttl=None)
        if stale is not None and not stale.empty:
            errors.append(build_error("cache", "stale", "实时源失败，使用历史缓存，数据可能过期"))
            return make_result(stale, source="stale_cache", fallback_used=True, errors=errors, cache_hit=True, cache_age=self._cache_age(cache_key))

        try:
            stub = self._offline_stub_kline(limit or 60, freq)
            if stub is not None and not stub.empty:
                errors.append(build_error("offline_stub", "used", "实时源不可用，使用内置示例K线，数据可能过期"))
                return make_result(stub, source="offline_stub", fallback_used=True, errors=errors)
        except Exception as e:
            errors.append(build_error("offline_stub", "exception", str(e)))

        errors.append(build_error("kline", "unavailable", "所有数据源均失败"))
        return make_result(pd.DataFrame(), source="unavailable", fallback_used=fallback_used, errors=errors)

    def get_kline_with_meta(
        self,
        code: str,
        freq: str = "daily",
        limit: Optional[int] = 250,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> pd.DataFrame:
        """兼容旧接口，返回 DataFrame。"""
        return self.get_kline_structured(code, freq, limit, start_date, end_date).data
    # -------------------------------------
    # 5. 深度财务
    # -------------------------------------
    def get_financial_features_structured(self, code: str) -> FetchResult:
        """财报/运营类特征（结构化输出），保证错误可见且多源兜底。"""

        code_std = standardize_code(code)
        ck = f"fin:{code_std}"
        cached = self.cache.get(ck, ttl=3600 * 12)
        if cached is not None:
            return FetchResult(data=cached, ok=True, source="cache", cache_hit=True, cache_age=self._cache_age(ck), meta={"filled_metrics": len([v for v in cached.values() if v not in (None, "", "--")])})

        errors: List[Dict[str, str]] = []
        source = ""
        fallback_used = False

        fin = self._fetch_financial_from_ak(code_std, errors)
        if fin:
            source = "akshare"
        else:
            fallback_used = True
            fin = self._fetch_financial_from_eastmoney(code_std, errors)
            if fin:
                source = "eastmoney"

        if not fin:
            fallback_used = True
            quote_fin = self._financial_from_quote(code_std, errors)
            if quote_fin:
                source = quote_fin.pop("source", "quote")
                fin = quote_fin

        if not fin:
            stale = self.cache.get(ck, ttl=None)
            if stale:
                errors.append(build_error("cache", "stale", "实时源失败，使用历史缓存，数据可能过期"))
                return FetchResult(
                    data=stale,
                    ok=True,
                    source="stale_cache",
                    fallback_used=True,
                    errors=errors,
                    cache_hit=True,
                    cache_age=self._cache_age(ck),
                    meta={"filled_metrics": len([v for v in stale.values() if v not in (None, "", "--")])},
                )

        if not fin:
            fallback_used = True
            fin = self._financial_offline_stub(code_std)
            if fin:
                errors.append(build_error("offline_stub", "used", "实时源不可用，使用内置示例财务数据，可能过期"))
                source = "offline_stub"
            else:
                errors.append(build_error("financial", "unavailable", "所有财务数据源均失败"))

        if not fin:
            return FetchResult(data={}, ok=False, source="unavailable", fallback_used=True, errors=errors)

        fin = self._enrich_financial_scores(fin)
        metric_keys = [
            "revenue",
            "net_profit",
            "gross_margin",
            "net_margin",
            "roe",
            "roa",
            "debt_ratio",
            "op_cashflow",
        ]
        valuation_keys = ["pe_ttm", "pb", "total_mv", "float_mv", "market_cap"]
        filled_keys = [k for k in metric_keys + valuation_keys if fin.get(k) not in (None, "", "--")]

        ok_flag = len(filled_keys) >= 3 and source not in ("offline_stub", "sample_cache", "unavailable")
        if ok_flag:
            self.cache.set(ck, fin)
        return FetchResult(
            data=fin,
            ok=ok_flag,
            source=source or "unknown",
            fallback_used=fallback_used,
            errors=errors,
            cache_age=self._cache_age(ck),
            meta={"filled_metrics": len(filled_keys)},
        )

    def get_financial_features(self, code: str) -> Dict[str, Any]:
        return self.get_financial_features_structured(code).data

    def _map_financial_row(self, row: Dict[str, Any]) -> Dict[str, Any]:
        mapping = {
            "report_date": ["报告期", "报告日期", "reportdate", "fdate", "REPORT_DATE"],
            "revenue": ["营业收入", "营业总收入(元)", "totaloperatereve", "营业总收入", "biz_income"],
            "net_profit": ["净利润", "netprofit", "归属于母公司股东的净利润", "netprofit_parent_comp", "归母净利润"],
            "gross_margin": ["销售毛利率(%)", "毛利率(%)", "毛利率", "grossprofit_margin", "GROSS_MARGIN"],
            "net_margin": ["销售净利率(%)", "净利率(%)", "净利率", "netprofit_margin"],
            "roe": ["净资产收益率(%)", "ROE(%)", "净资产收益率", "weightedroe", "roe"],
            "roa": ["总资产报酬率(%)", "资产报酬率(%)", "资产报酬率", "roa2_weighted", "roa"],
            "debt_ratio": ["资产负债率(%)", "资产负债率", "debtratio", "资产负债率\r"],
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
            out[target] = _to_float_or_none(pick(keys)) if target != "report_date" else pick(keys)

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
            df = self._retry_call(lambda: ak.stock_financial_analysis_indicator(symbol=code_std))
        except Exception as e:
            errors.append(build_error("akshare", "exception", str(e)))

        if df is None or df.empty:
            try:
                df = self._retry_call(lambda: ak.stock_financial_analysis_indicator_em(symbol=code_std))
            except Exception as e:
                errors.append(build_error("akshare_em", "exception", str(e)))

        if df is not None and not df.empty:
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

    def _financial_from_quote(self, code_std: str, errors: List[Dict[str, str]]) -> Optional[Dict[str, Any]]:
        """从行情估值字段兜底，至少填充 3 个指标。"""

        quote_res = self.get_spot_row_structured(code_std)
        quote = quote_res.data if isinstance(quote_res.data, dict) else {}
        if not quote:
            errors.append(build_error("quote", "empty", "行情估值字段为空，无法兜底财务"))
            return None

        valuation_fields = {
            "pe_ttm": quote.get("pe_ttm"),
            "pb": quote.get("pb"),
            "total_mv": quote.get("total_mv"),
            "float_mv": quote.get("float_mv"),
            "market_cap": quote.get("market_cap"),
        }

        filled = {k: v for k, v in valuation_fields.items() if v not in (None, "", "--")}
        if len(filled) < 3:
            errors.append(build_error("quote", "insufficient", "行情估值字段不足 3 项"))
            errors.extend(quote_res.errors)
            return None

        if quote_res.errors:
            errors.extend(quote_res.errors)

        filled["report_date"] = quote.get("quote_date") or quote.get("ts")
        filled["source"] = f"quote:{quote_res.source or 'unknown'}"
        return filled

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

    def _enrich_financial_scores(self, fin: Dict[str, Any]) -> Dict[str, Any]:
        def _clip(x: float) -> float:
            return max(0.0, min(1.0, float(x)))

        roe_score = _clip(((_safe_float(fin.get("roe"), 0.0)) / 15.0 + 1) / 2)
        gm_score = _clip(_safe_float(fin.get("gross_margin"), 0.0) / 50.0)
        debt_score = _clip(1.0 - _safe_float(fin.get("debt_ratio"), 0.0) / 80.0)
        prof_score = _clip((_safe_float(fin.get("profit_yoy"), 0.0) / 40.0 + 1) / 2)
        rev_score = _clip((_safe_float(fin.get("revenue_yoy"), 0.0) / 30.0 + 1) / 2)

        fin["fundamental_quality"] = _clip(0.40 * roe_score + 0.30 * gm_score + 0.20 * debt_score + 0.10 * _clip(_safe_float(fin.get("net_margin"), 0.0) / 30.0))
        fin["fundamental_growth"] = _clip(0.60 * prof_score + 0.40 * rev_score)
        cf_bonus = 0.05 if _safe_float(fin.get("op_cashflow"), 0.0) > 0 else 0.0
        fin["ops_momentum"] = _clip(0.50 + 0.40 * (fin["fundamental_growth"] - 0.50) + 0.10 * (fin["fundamental_quality"] - 0.50) + cf_bonus)
        return fin

    def get_money_flow_structured(self, code: str) -> FetchResult:
        """资金流信息，带错误原因。"""
        code_std = standardize_code(code)
        errors: List[Dict[str, str]] = []
        out: Dict[str, Any] = {}
        fallback_used = False
        source = "money_flow"

        try:
            if self.capital_engine is not None:
                cap = self.capital_engine.get_capital_features_structured(code_std)
                if isinstance(cap.data, dict):
                    out.update(cap.data)
                errors.extend(cap.errors)
                fallback_used = fallback_used or cap.fallback_used
                source = cap.source or source
            else:
                errors.append(build_error("capital_engine", "missing", "未初始化"))
        except Exception as e:  # noqa: BLE001
            errors.append(build_error("capital_engine", "exception", str(e)))

        if not out:
            errors.append(build_error("money_flow", "empty", "资金流为空"))

        return make_result(out, source=source, errors=errors, fallback_used=fallback_used or bool(errors))

    def get_money_flow(self, code: str) -> Dict[str, Any]:
        return self.get_money_flow_structured(code).data


    # -------------------------------------
    # 5.4 公告 / 研报 / 热点要事
    # -------------------------------------
    def get_announcements_structured(self, code: str, limit: int = 12) -> FetchResult:
        code_std = standardize_code(code)
        errors: List[Dict[str, str]] = []
        chosen: List[Dict[str, Any]] = []
        source = ""
        providers = [
            ("eastmoney", lambda: fetch_announcements_em(code_std, limit=limit)),
            ("tencent", lambda: fetch_announcements_tencent(code_std, limit=limit)),
        ]

        for name, fn in providers:
            try:
                data = self._retry_call(fn, max_retries=2)
            except Exception as e:  # noqa: BLE001
                errors.append(build_error(name, "exception", str(e)))
                continue
            if data:
                chosen = data
                source = name
                break
            errors.append(build_error(name, "empty", f"{name} 公告为空"))

        if not chosen:
            errors.append(build_error("sample", "fallback", "启用离线公告样本，数据可能过期"))
            chosen = sample_announcements(code_std, limit=limit)
            source = "sample_cache"

        return make_result(chosen, source=source, errors=errors, fallback_used=len(errors) > 0)

    def get_research_reports_structured(self, code: str, limit: int = 12) -> FetchResult:
        code_std = standardize_code(code)
        errors: List[Dict[str, str]] = []
        chosen: List[Dict[str, Any]] = []
        source = ""
        providers = [
            ("eastmoney", lambda: fetch_research_reports_em(code_std, limit=limit)),
            ("alt", lambda: fetch_research_reports_alt(code_std, limit=limit)),
        ]

        for name, fn in providers:
            try:
                data = self._retry_call(fn, max_retries=2)
            except Exception as e:  # noqa: BLE001
                errors.append(build_error(name, "exception", str(e)))
                continue
            if data:
                chosen = data
                source = name
                break
            errors.append(build_error(name, "empty", f"{name} 研报为空"))

        if not chosen:
            errors.append(build_error("sample", "fallback", "启用离线研报样本，数据可能过期"))
            chosen = sample_reports(code_std, limit=limit)
            source = "sample_cache"

        return make_result(chosen, source=source, errors=errors, fallback_used=len(errors) > 0)

    def get_hot_topics_structured(self, limit: int = 8) -> FetchResult:
        errors: List[Dict[str, str]] = []
        chosen: List[Dict[str, Any]] = []
        source = ""
        providers = [
            ("eastmoney", lambda: fetch_hot_topics_em(limit=limit)),
            ("akshare", lambda: fetch_hot_topics_ak(limit=limit)),
        ]

        for name, fn in providers:
            try:
                data = self._retry_call(fn, max_retries=2)
            except Exception as e:  # noqa: BLE001
                errors.append(build_error(name, "exception", str(e)))
                continue
            if data:
                chosen = data
                source = name
                break
            errors.append(build_error(name, "empty", f"{name} 热点为空"))

        if not chosen:
            errors.append(build_error("sample", "fallback", "启用离线热点样本，数据可能过期"))
            chosen = sample_hot_topics(limit=limit)
            source = "sample_cache"

        return make_result(chosen, source=source, errors=errors, fallback_used=len(errors) > 0)


    # -------------------------------------
    # 5.5  健康检查（商用可观测性）
    # -------------------------------------
    def health_check(self) -> Dict[str, Any]:
        """
        用于 UI/调度的快速自检：
        - AkShare 是否可用
        - 东财 push2 是否可用
        - spot 快照是否命中缓存/是否陈旧
        """
        report: Dict[str, Any] = {
            "akshare_available": bool(ak),
            "spot_source": "",
            "spot_is_stale": False,
            "spot_rows": 0,
            "hint": "",
        }
        try:
            df = self.get_spot_snapshot(ttl_seconds=10)
            report["spot_source"] = self.spot_source or ""
            report["spot_is_stale"] = bool(self.spot_is_stale)
            report["spot_rows"] = int(len(df)) if df is not None else 0
            if report["spot_rows"] == 0:
                report["hint"] = "行情快照获取失败：建议检查网络/限流，或稍后重试。"
            elif report["spot_is_stale"]:
                report["hint"] = "正在使用历史缓存快照（可能较旧）。建议恢复数据源后刷新。"
        except Exception as e:
            report["hint"] = f"健康检查异常：{e}"
        return report

    # -------------------------------------
    # 6. 全息打包
    # -------------------------------------
    def get_holistic_data(self, code: str) -> Dict[str, Any]:
        code = normalize_code(code)
        spot = self.get_spot_row(code)
        ident = self.get_stock_identity(code)
        
        # 默认取日线做简报技术面分析
        kline = self.get_kline(code, freq="daily", limit=20)
        tech = f"最新价: {kline.iloc[-1]['close']}" if not kline.empty else "无数据"

        fin = self.get_financial_features(code)
        money = self.get_money_flow(code)

        alt_report = {}
        if self.alt_engine:
            alt_report = self.alt_engine.get_alternative_report(code, sector=ident.get('sector', ''))
        else:
            self.logger.info("alternative data engine missing; skipping alt report for %s", code)
        
        return {
            "code": code,
            "timestamp": _now_str(),
            "identity": ident,
            "market_data": spot,
            "financials": fin,
            "money_flow": money,
            "technical_brief": tech,
            "alternative_intelligence": alt_report,
            "macro_context": alt_report.get("macro_environment", {}),
            "corporate_news": alt_report.get("corporate_news", []),
            "macro_news": alt_report.get("macro_news", []),
        }