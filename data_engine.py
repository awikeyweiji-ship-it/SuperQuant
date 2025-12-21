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
import os
import requests
from typing import Dict, Any, Optional, List

# 确保优先使用系统 site-packages，避免本地 Windows 版依赖污染
site_paths = [p for p in sys.path if "site-packages" in p]
other_paths = [p for p in sys.path if p not in site_paths and p != ""]
sys.path = site_paths + other_paths + [""]

PD_IMPORT_ERROR: Optional[str] = None
NP_IMPORT_ERROR: Optional[str] = None

try:
    import pandas as pd  # type: ignore
except (MemoryError, ImportError) as exc:  # noqa: PIE786
    PD_IMPORT_ERROR = f"{exc.__class__.__name__}: {exc}"
    pd = None  # type: ignore[assignment]
else:
    PD_IMPORT_ERROR = None

try:
    import numpy as np  # type: ignore
except Exception as exc:  # noqa: BLE001
    NP_IMPORT_ERROR = f"{exc.__class__.__name__}: {exc}"
    np = None  # type: ignore[assignment]

from logging_utils import get_data_logger, make_result, build_error, FetchResult
from data_sources.provider_registry import ProviderRegistry, run_providers_parallel
from data_sources.identity import canonical_identity
from data_sources.quote_eastmoney import fetch as fetch_quote_eastmoney
from data_sources.financial_eastmoney import fetch as fetch_financial_eastmoney
from data_sources.moneyflow_eastmoney import fetch as fetch_moneyflow_eastmoney
from data_sources.identity_eastmoney import fetch_identity_em
from data_sources.news_announcements_eastmoney import fetch as fetch_news_announcements
from data_sources.news_reports_eastmoney import fetch as fetch_news_reports
from data_sources.news_hot_eastmoney import fetch as fetch_news_hot
from data_sources.kline_eastmoney import fetch as fetch_kline_eastmoney
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
    return canonical_identity(code).symbol


# Backward-compatible alias
standardize_code = normalize_code


def to_tencent_symbol(code: str) -> str:
    ident = canonical_identity(code)
    return ident.prefixed


def to_eastmoney_secid(code: str) -> str:
    ident = canonical_identity(code)
    return ident.secid

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
        default_val = np.nan if np is not None else None
        val = _safe_float(x, default=default_val) if default_val is not None else _safe_float(x, default=0.0)
        if np is not None and pd is not None:
            try:
                if pd.isna(val):
                    return None
            except Exception:
                pass
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
        self.provider_registry = ProviderRegistry()
        self._register_default_providers()

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

    @staticmethod
    def _json_safe(value: Any) -> Any:
        """Recursively convert values into JSON-serializable primitives."""

        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        if pd is not None and value is getattr(pd, "NaT", None):
            return None
        if isinstance(value, (_dt.date, _dt.datetime)):
            try:
                return value.isoformat()
            except Exception:
                return str(value)
        if pd is not None and isinstance(value, getattr(pd, "Timestamp", ())):
            try:
                return value.isoformat()
            except Exception:
                return str(value)
        if np is not None and isinstance(value, (np.generic,)):
            try:
                return value.item()
            except Exception:
                return value.tolist() if hasattr(value, "tolist") else str(value)
        if np is not None and isinstance(value, np.ndarray):
            try:
                return [DataEngine._json_safe(v) for v in value.tolist()]
            except Exception:
                return str(value)
        if isinstance(value, dict):
            return {k: DataEngine._json_safe(v) for k, v in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [DataEngine._json_safe(v) for v in value]
        try:
            return float(value)
        except Exception:
            try:
                return str(value)
            except Exception:
                return None

    def _register_default_providers(self) -> None:
        # Quote providers
        self.provider_registry.register(
            "quote",
            "quote_eastmoney",
            lambda code, **kwargs: self._provider_quote_module(code, fetch_quote_eastmoney),
            priority=10,
        )
        self.provider_registry.register(
            "quote",
            "quote_tencent",
            lambda code, **kwargs: self._provider_quote_from_func(code, self._fetch_quote_tencent, "tencent"),
            priority=7,
        )
        self.provider_registry.register(
            "quote",
            "quote_akshare",
            lambda code, **kwargs: self._provider_quote_from_func(code, self._fetch_quote_akshare, "akshare"),
            priority=5,
        )

        # Financial & money flow providers
        self.provider_registry.register(
            "financial",
            "financial_eastmoney",
            lambda code, **kwargs: fetch_financial_eastmoney(code),
            priority=10,
        )
        self.provider_registry.register(
            "financial", "legacy_financial", lambda code, **kwargs: self._provider_financial(code), priority=5
        )
        self.provider_registry.register(
            "money_flow",
            "moneyflow_eastmoney",
            lambda code, **kwargs: fetch_moneyflow_eastmoney(code),
            priority=10,
        )
        self.provider_registry.register(
            "money_flow", "legacy_money_flow", lambda code, **kwargs: self._provider_money_flow(code), priority=5
        )

        # News bundle
        self.provider_registry.register(
            "news_bundle",
            "news_bundle_eastmoney",
            lambda code, **kwargs: self._provider_news_bundle_eastmoney(code),
            priority=10,
        )
        self.provider_registry.register("news_bundle", "legacy_news_bundle", lambda code, **kwargs: self._provider_news_bundle(code), priority=5)

    @staticmethod
    def _count_filled_fields(payload: Dict[str, Any]) -> int:
        if not isinstance(payload, dict):
            return 0
        return sum(1 for _, v in payload.items() if v not in (None, "", "--"))

    @staticmethod
    def _sanitize_stub_data(payload: Dict[str, Any]) -> Tuple[Dict[str, Any], List[Dict[str, str]]]:
        errors: List[Dict[str, str]] = []
        if not isinstance(payload, dict):
            return {}, errors
        text_blob = json.dumps(payload, ensure_ascii=False, default=str)
        if "example.com" in text_blob or "sample_cache" in text_blob or "offline_stub" in text_blob:
            errors.append(build_error("validator", "stub_blocked", "过滤占位数据"))
            return {}, errors
        return payload, errors

    def _fetchresult_to_provider_payload(self, fr: FetchResult, label: str) -> Dict[str, Any]:
        data = fr.data
        if hasattr(data, "to_dict") and not isinstance(data, dict):
            try:
                data = data.to_dict()  # type: ignore[assignment]
            except Exception:
                data = {}
        if not isinstance(data, dict):
            data = {}
        data, blocked_errors = self._sanitize_stub_data(data)
        errors = list(fr.errors or []) + blocked_errors
        if (fr.source or "").startswith("sample") or (fr.source or "") in {"offline_stub", "sample_cache"}:
            errors.append(build_error(fr.source or label, "disabled", "默认禁用样本数据"))
            data = {}
        meta = {
            "source": fr.source or label,
            "retrieved_at": time.time(),
            "cache_hit": fr.cache_hit,
            "cache_age": fr.cache_age,
            "ttl_sec": None,
            "fallback_used": fr.fallback_used or bool(blocked_errors),
            "errors": errors,
            "filled_metrics": self._count_filled_fields(data),
        }
        if isinstance(getattr(fr, "meta", None), dict):
            meta.update(fr.meta)  # type: ignore[arg-type]
            meta["filled_metrics"] = meta.get("filled_metrics", self._count_filled_fields(data))
        return {"data": data, "meta": meta}

    def _provider_quote_from_func(self, code: str, fetcher, source: str) -> Dict[str, Any]:
        code_std = standardize_code(code)
        data = self._standardize_quote(fetcher(code_std), code_std, source)
        meta = {
            "source": source,
            "retrieved_at": time.time(),
            "errors": [],
            "fallback_used": False,
            "cache_hit": False,
            "ttl_sec": None,
            "filled_metrics": self._count_filled_fields(data),
        }
        if not data:
            meta["errors"].append(build_error(source, "empty", f"{source} 行情返回空"))
        return {"data": data, "meta": meta}

    def _provider_quote_module(self, code: str, provider_func) -> Dict[str, Any]:
        payload = provider_func(code)
        payload = payload or {}
        data = payload.get("data", {}) if isinstance(payload, dict) else {}
        meta = payload.get("meta", {}) if isinstance(payload, dict) else {}
        meta.setdefault("source", "quote_eastmoney")
        meta.setdefault("retrieved_at", time.time())
        meta.setdefault("errors", [])
        meta.setdefault("fallback_used", False)
        meta.setdefault("cache_hit", False)
        meta.setdefault("filled_metrics", self._count_filled_fields(data))
        if not data:
            meta["errors"].append(build_error(meta["source"], "empty", "行情数据为空"))
        return {"data": data, "meta": meta}

    def _provider_financial(self, code: str) -> Dict[str, Any]:
        res = self.get_financial_features_structured(code)
        payload = self._fetchresult_to_provider_payload(res, "financial")
        rp = payload["data"].get("report_period") or payload["data"].get("report_date")
        if rp:
            payload["meta"]["report_period"] = rp
        return payload

    def _provider_money_flow(self, code: str) -> Dict[str, Any]:
        res = self.get_money_flow_structured(code)
        return self._fetchresult_to_provider_payload(res, "money_flow")

    def _provider_news_bundle_eastmoney(self, code: str) -> Dict[str, Any]:
        code_std = standardize_code(code)
        meta_errors: List[Dict[str, str]] = []
        data = {"announcements": [], "reports": [], "hot_events": []}

        for fetcher, key in [
            (fetch_news_announcements, "announcements"),
            (fetch_news_reports, "reports"),
            (fetch_news_hot, "hot_events"),
        ]:
            try:
                payload = fetcher(code_std)
                section = payload.get("data", {}).get(key, []) if isinstance(payload, dict) else []
                if section:
                    data[key] = section
                meta_errors.extend(payload.get("meta", {}).get("errors", []) if isinstance(payload, dict) else [])
            except Exception as exc:  # noqa: BLE001
                meta_errors.append(build_error(key, "exception", str(exc)))

        coverage = sum(1 for v in data.values() if v)
        if coverage == 0:
            meta_errors.append(build_error("news_bundle", "insufficient", "新闻、公告、热点均为空"))
        elif coverage == 1:
            meta_errors.append(build_error("news_bundle", "partial", "仅一类资讯可用，信心较低"))

        meta = {
            "source": "news_bundle_eastmoney",
            "retrieved_at": time.time(),
            "errors": meta_errors,
            "errors_count": len(meta_errors),
            "fallback_used": False,
            "cache_hit": False,
            "filled_metrics": sum(len(v) for v in data.values()),
        }
        return {"data": data, "meta": meta}

    def _provider_news_bundle(self, code: str) -> Dict[str, Any]:
        res = self.get_news_bundle_structured(code)
        return self._fetchresult_to_provider_payload(res, "news_bundle")

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
            r = requests.get(url, timeout=8)
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
            r = requests.get(url, params=params, timeout=10)
            data = (r.json() or {}).get("data") or {}
            if not data:
                return {}
            def _price(v: Any) -> Optional[float]:
                if v in (None, "", "--"):
                    return None
                try:
                    return float(v) / 100.0
                except Exception:
                    return None
            def _pct(v: Any) -> Optional[float]:
                if v in (None, "", "--"):
                    return None
                try:
                    return float(v) / 100.0
                except Exception:
                    return None
            def _to_num(v: Any) -> Optional[float]:
                try:
                    if v in (None, "", "--"):
                        return None
                    return float(v)
                except Exception:
                    return None
            vol_raw = _to_num(data.get("f47"))  # 单位：手
            amount_raw = _to_num(data.get("f48"))  # 单位：元
            return {
                "code": normalize_code(code_std),
                "name": data.get("f58", ""),
                "price": _price(data.get("f43")),
                "open": _price(data.get("f46")),
                "high": _price(data.get("f44")),
                "low": _price(data.get("f45")),
                "preclose": _price(data.get("f60")),
                "pct_chg": _pct(data.get("f170")),
                "vol": vol_raw * 100 if vol_raw is not None else None,  # 转换为股
                "amount": amount_raw,
                "turnover": _pct(data.get("f84")),
                "pe_ttm": data.get("f162"),
                "pb": data.get("f167"),
                "total_mv": _to_num(data.get("f116")),
                "float_mv": _to_num(data.get("f117")),
                "quote_date": data.get("f71"),
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
                "vol": 5.2e7,
                "amount": 5.5e8,
                "turnover": 0.9,
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
                "price": 8.52,
                "pct_chg": -0.6,
                "vol": 1.3e7,
                "amount": 1.1e8,
                "turnover": 0.4,
                "high": 8.66,
                "low": 8.43,
                "open": 8.60,
                "preclose": 8.57,
                "pe_ttm": 12.0,
                "pb": 1.2,
                "total_mv": 8.9e10,
                "float_mv": 6.5e10,
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
        r = requests.get(url, params=params, headers=headers, timeout=12)
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

    def get_spot_row_structured(self, code: str, force_refresh: bool = False) -> FetchResult:
        ident = canonical_identity(code)
        code_std = ident.symbol
        cache_key = self.cache.key("quote_v1", {"code": code_std})
        errors: List[Dict[str, str]] = []
        cache_age = self._cache_age(cache_key)

        if not force_refresh:
            cached = self.cache.get(cache_key, ttl=30)
            if isinstance(cached, dict) and cached:
                return make_result(cached, source=cached.get("source", "cache"), cache_hit=True, cache_age=cache_age)

        payload, _ = run_providers_parallel(
            self.provider_registry.get_providers("quote"),
            code_std,
            timeout=8.0,
            retries=1,
            identity=ident.to_dict(),
            force_refresh=force_refresh,
        )

        if payload:
            data = payload.get("data", {}) if isinstance(payload, dict) else {}
            meta = payload.get("meta", {}) if isinstance(payload, dict) else {}
            if data:
                self.cache.set(cache_key, data)
            return make_result(
                data,
                source=meta.get("source", "quote"),
                fallback_used=meta.get("fallback_used", False),
                errors=meta.get("errors", []),
                cache_hit=False,
                cache_age=None,
                meta=meta,
            )

        if not force_refresh:
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
                resp = requests.get(url, params=params, timeout=10)
                resp.raise_for_status()
                payload = resp.json()
                klines = payload.get("data", {}).get("klines", []) if isinstance(payload, dict) else []
                if not klines:
                    last_err = Exception("empty kline data")
                    continue
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
        # best-effort: never raise, just return empty on failures
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

        if pd is None or np is None:
            if PD_IMPORT_ERROR:
                errors.append(build_error("pandas", "import_error", PD_IMPORT_ERROR))
            if NP_IMPORT_ERROR:
                errors.append(build_error("numpy", "import_error", NP_IMPORT_ERROR))
            return make_result([], source="unavailable", fallback_used=True, errors=errors)

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
        source_chain: List[str] = []
        fallback_used = False
        fin: Dict[str, Any] = {}
        allow_samples = os.environ.get("ALLOW_SAMPLE_CACHE", "").lower() in {"1", "true", "yes", "on"} or os.environ.get("ALLOW_OFFLINE_SAMPLES", "").lower() in {"1", "true", "yes", "on"}

        # 1) 东财主路径
        em_errors: List[Dict[str, str]] = []
        fin_em = self._fetch_financial_from_eastmoney(code_std, em_errors)
        errors.extend(em_errors)
        if fin_em:
            fin.update(fin_em)
            source_chain.append("eastmoney")
        else:
            fallback_used = True

        # 2) AkShare 兼容兜底（补足缺失字段）
        ak_errors: List[Dict[str, str]] = []
        fin_ak = self._fetch_financial_from_ak(code_std, ak_errors)
        errors.extend(ak_errors)
        if fin_ak:
            for k, v in fin_ak.items():
                if fin.get(k) in (None, "", "--") and v not in (None, "", "--"):
                    fin[k] = v
            if not source_chain:
                source_chain.append("akshare")
            else:
                fallback_used = True

        # 3) 行情估值兜底（填补 pe/pb 等必填）
        quote_errors: List[Dict[str, str]] = []
        quote_fin = self._financial_from_quote(code_std, quote_errors)
        errors.extend(quote_errors)
        if quote_fin:
            for k, v in quote_fin.items():
                if fin.get(k) in (None, "", "--") and v not in (None, "", "--"):
                    fin[k] = v
            if not source_chain:
                source_chain.append(quote_fin.get("source", "quote"))
                fallback_used = True

        # 4) 离线样本补齐必填字段
        required_keys = ["pe_ttm", "pb", "roe", "revenue_yoy", "profit_yoy", "gross_margin"]
        filled_required = [k for k in required_keys if fin.get(k) not in (None, "", "--")]
        if len(filled_required) < 4 and allow_samples:
            stub = self._financial_offline_stub(code_std) or {}
            if stub:
                for k, v in stub.items():
                    if fin.get(k) in (None, "", "--") and v not in (None, "", "--"):
                        fin[k] = v
                if "offline_stub" not in source_chain:
                    source_chain.append("offline_stub")
                errors.append(build_error("offline_stub", "used", "实时源不可用，使用内置示例财务数据，可能过期"))
                fallback_used = True
        elif len(filled_required) < 4 and not allow_samples:
            errors.append(build_error("offline_stub", "disabled", "未启用样本模式，缺少必填财务字段"))

        # 4) 缓存兜底（不引入假数据）
        if not fin:
            stale = self.cache.get(ck, ttl=None)
            if stale:
                errors.append(build_error("cache", "stale", "实时源失败，使用历史缓存，数据可能过期"))
                filled_stale = len([v for v in stale.values() if v not in (None, "", "--")])
                return FetchResult(
                    data=stale,
                    ok=True,
                    source="stale_cache",
                    fallback_used=True,
                    errors=errors,
                    cache_hit=True,
                    cache_age=self._cache_age(ck),
                    meta={"filled_metrics": filled_stale},
                )

        # 5) 离线兜底（显式标注 fallback）
        if not fin and allow_samples:
            fallback_used = True
            fin = self._financial_offline_stub(code_std) or {}
            if fin:
                errors.append(build_error("offline_stub", "used", "实时源不可用，使用内置示例财务数据，可能过期"))
                source_chain.append("offline_stub")
            else:
                errors.append(build_error("financial", "unavailable", "所有财务数据源均失败"))
        elif not fin:
            errors.append(build_error("financial", "unavailable", "所有财务数据源均失败且禁用样本"))

        if not fin:
            return FetchResult(data={}, ok=False, source="unavailable", fallback_used=True, errors=errors)

        # 字段补齐
        fin = self._enrich_financial_scores(fin)
        fin["report_period"] = fin.get("report_date") or fin.get("report_period")
        required_keys = ["pe_ttm", "pb", "roe", "revenue_yoy", "profit_yoy", "gross_margin"]
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
        filled_required = [k for k in required_keys if fin.get(k) not in (None, "", "--")]

        ok_flag = len(filled_required) >= 4
        if ok_flag:
            self.cache.set(ck, fin)
        return FetchResult(
            data=fin,
            ok=ok_flag,
            source=source_chain[0] if source_chain else "unknown",
            fallback_used=fallback_used,
            errors=errors,
            cache_age=self._cache_age(ck),
            meta={
                "filled_metrics": len(filled_keys),
                "filled_required": len(filled_required),
                "report_period": fin.get("report_period"),
                "sources": source_chain,
            },
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
            payload = fetch_financial_eastmoney(code_std)
            data = payload.get("data", {}) if isinstance(payload, dict) else {}
            if data:
                return data
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
                "pe_ttm": 25.0,
                "pb": 6.5,
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
                "pe_ttm": 7.5,
                "pb": 0.9,
            },
            "601872.SH": {
                "report_date": "2024-09-30",
                "revenue": 170.2 * 1e8,
                "net_profit": 22.4 * 1e8,
                "gross_margin": 32.5,
                "net_margin": 13.2,
                "roe": 8.7,
                "roa": 5.1,
                "debt_ratio": 55.0,
                "op_cashflow": 30.0 * 1e8,
                "profit_yoy": 9.5,
                "revenue_yoy": 7.8,
                "eps": 0.86,
                "pe_ttm": 15.0,
                "pb": 1.5,
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
        meta: Dict[str, Any] = {}

        try:
            if self.capital_engine is not None:
                cap = self.capital_engine.get_capital_features_structured(code_std)
                if isinstance(cap.data, dict):
                    out.update(cap.data)
                errors.extend(cap.errors)
                fallback_used = fallback_used or cap.fallback_used
                source = cap.source or source
                meta = cap.meta if isinstance(getattr(cap, "meta", None), dict) else {}
            else:
                errors.append(build_error("capital_engine", "missing", "未初始化"))
        except Exception as e:  # noqa: BLE001
            errors.append(build_error("capital_engine", "exception", str(e)))

        if not out:
            errors.append(build_error("money_flow", "empty", "资金流为空"))
        filled_keys = [
            "main_net_inflow",
            "super_large_net_inflow",
            "large_net_inflow",
            "medium_net_inflow",
            "small_net_inflow",
            "northbound_net_inflow",
        ]
        filled_metrics = sum(1 for k in filled_keys if out.get(k) not in (None, "", "--"))
        meta = meta if isinstance(locals().get("meta", {}), dict) else {}
        meta.update({"filled_metrics": filled_metrics, "retrieved_at": time.time()})

        return make_result(
            out,
            source=source,
            errors=errors,
            fallback_used=fallback_used or bool(errors),
            meta=meta,
        )

    def get_money_flow(self, code: str) -> Dict[str, Any]:
        return self.get_money_flow_structured(code).data


    # -------------------------------------
    # 5.4 公告 / 研报 / 热点要事
    # -------------------------------------
    def get_news_bundle_structured(self, code: str, limit: int = 8) -> FetchResult:
        """聚合公告/研报/热点/论坛/观点，优先使用情报引擎统一 schema。"""

        code_std = standardize_code(code)
        if self.alt_engine and hasattr(self.alt_engine, "get_news_bundle_structured"):
            try:
                return self.alt_engine.get_news_bundle_structured(code_std)
            except Exception as e:  # noqa: BLE001
                err = build_error("alternative", "exception", str(e))
                errors = [err]
        else:
            errors = [build_error("alternative", "missing", "情报引擎未初始化")]

        # 保底：使用本地聚合，字段保持一致
        bundle: Dict[str, Any] = {
            "announcements": [],
            "reports": [],
            "hot_events": [],
            "forums": [],
            "opinions": [],
        }
        sources: Dict[str, str] = {}
        fallback_used = False

        ann = self.get_announcements_structured(code_std, limit=limit)
        bundle["announcements"] = ann.data if isinstance(ann.data, list) else []
        sources["announcements"] = ann.source
        errors.extend(ann.errors)
        if ann.fallback_used:
            fallback_used = True

        rep = self.get_research_reports_structured(code_std, limit=limit)
        bundle["reports"] = rep.data if isinstance(rep.data, list) else []
        sources["reports"] = rep.source
        errors.extend(rep.errors)
        if rep.fallback_used:
            fallback_used = True

        hot = self.get_hot_topics_structured(limit=limit)
        bundle["hot_events"] = hot.data if isinstance(hot.data, list) else []
        sources["hot_events"] = hot.source
        errors.extend(hot.errors)
        if hot.fallback_used:
            fallback_used = True

        coverage = sum(1 for k in ["announcements", "reports", "hot_events"] if bundle.get(k))
        if coverage == 0:
            errors.append(build_error("news_bundle", "insufficient", "公告、研报、热点均为空"))
            fallback_used = True
        elif coverage == 1:
            errors.append(build_error("news_bundle", "partial", "资讯来源只有一类，谨慎参考"))
        meta = {"sources": sources, "filled_sections": coverage, "retrieved_at": _now_str(), "filled_metrics": coverage}
        return make_result(bundle, source="news_bundle", errors=errors, fallback_used=fallback_used, meta=meta)

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
            payload_items = data.get("items", []) if isinstance(data, dict) else data
            errors.extend(data.get("errors", []) if isinstance(data, dict) else [])
            if payload_items:
                chosen = payload_items
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
            payload_items = data.get("items", []) if isinstance(data, dict) else data
            errors.extend(data.get("errors", []) if isinstance(data, dict) else [])
            if payload_items:
                chosen = payload_items
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
            payload_items = data.get("items", []) if isinstance(data, dict) else data
            errors.extend(data.get("errors", []) if isinstance(data, dict) else [])
            if payload_items:
                chosen = payload_items
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
    def single_stock(
        self,
        code: str,
        sample_mode: bool = False,
        offline_mode: bool = False,
        force_refresh: bool = False,
    ) -> Dict[str, Any]:
        ident_obj = canonical_identity(code)
        code_std = ident_obj.symbol
        if not sample_mode:
            os.environ["ALLOW_SAMPLE_CACHE"] = "0"
        if not offline_mode:
            os.environ["ALLOW_OFFLINE_SAMPLES"] = "0"
        # 基础链路
        basic_meta: Dict[str, Any] = {}

        def _safe_fetch(fn, label: str) -> Dict[str, Any]:
            try:
                res = fn()
                data = res.data if isinstance(res.data, dict) else {}
                data, blocked_errors = self._sanitize_stub_data(data)
                meta = {
                    "source": res.source or label,
                    "fallback_used": res.fallback_used,
                    "cache_hit": res.cache_hit,
                    "cache_age": res.cache_age,
                    "errors": list(res.errors or []) + blocked_errors,
                    "ts": getattr(res, "ts", time.time()),
                    "filled_metrics": self._count_filled_fields(data),
                }
                basic_meta[label] = meta
                return data
            except Exception as e:  # noqa: BLE001
                meta = {"source": label, "errors": [build_error(label, "exception", str(e))], "fallback_used": True}
                basic_meta[label] = meta
                return {}

        identity = _safe_fetch(lambda: self.get_stock_identity_structured(code_std), "identity")
        kline_payload = fetch_kline_eastmoney(code_std, limit=400)
        kline_rows = []
        if isinstance(kline_payload, dict):
            kline_rows = kline_payload.get("data", {}).get("rows", []) if isinstance(kline_payload.get("data"), dict) else []
        kline_rows = kline_rows or []
        kline_meta = (kline_payload.get("meta", {}) if isinstance(kline_payload, dict) else {}) or {}
        kline_meta.setdefault("filled_metrics", len(kline_rows))
        kline_meta.setdefault("errors", [])
        kline_meta.setdefault("source", "kline_eastmoney")
        kline_data = {"daily": kline_rows}
        basic_meta["kline"] = kline_meta

        # 并行 provider 域
        provider_trace: Dict[str, Any] = {
            "kline_daily": [
                {
                    "provider": "kline_eastmoney",
                    "success": bool(kline_rows),
                    "filled_metrics": len(kline_rows),
                    "errors": kline_meta.get("errors", []),
                    "errors_count": len(kline_meta.get("errors", [])),
                    "used_key": kline_meta.get("used_key"),
                }
            ]
        }
        def _run(domain: str, **kwargs: Any):
            payload, traces = run_providers_parallel(
                self.provider_registry.get_providers(domain),
                code_std,
                timeout=8.0,
                retries=1,
                identity=ident_obj.to_dict(),
                **kwargs,
            )
            provider_trace[domain] = traces
            if payload:
                meta = payload.get("meta", {}) if isinstance(payload, dict) else {}
                meta.setdefault("filled_metrics", self._count_filled_fields(payload.get("data", {})))
                payload["meta"] = meta
                return payload
            return {
                "data": {},
                "meta": {"source": "unavailable", "errors": [build_error(domain, "empty", "无有效数据")], "filled_metrics": 0},
            }

        def _clean(payload: Dict[str, Any]) -> Dict[str, Any]:
            data = payload.get("data", {}) if isinstance(payload, dict) else {}
            meta = payload.get("meta", {}) if isinstance(payload, dict) else {}
            if isinstance(data, dict):
                data, blocked = self._sanitize_stub_data(data)
                if blocked:
                    meta.setdefault("errors", []).extend(blocked)
                    meta["fallback_used"] = True
            payload["data"] = data
            payload["meta"] = meta
            return payload

        quote_payload = _clean(_run("quote", force_refresh=force_refresh))
        financial_payload = _clean(_run("financial"))
        money_payload = _clean(_run("money_flow"))
        news_payload = _clean(_run("news_bundle"))

        quote = quote_payload.get("data", {}) if isinstance(quote_payload, dict) else {}
        basic_meta["quote"] = quote_payload.get("meta", {}) if isinstance(quote_payload, dict) else {}

        # 汇总与 evidence + advice
        def _build_evidence_and_advice() -> Dict[str, Any]:
            ev: List[Dict[str, Any]] = []
            fin_data = financial_payload.get("data", {}) if isinstance(financial_payload, dict) else {}
            money_data = money_payload.get("data", {}) if isinstance(money_payload, dict) else {}
            news_data = news_payload.get("data", {}) if isinstance(news_payload, dict) else {}
            kline_rows_local = kline_rows
            missing_refs: List[str] = []

            diag_meta_map = {
                "quote": quote_payload.get("meta", {}),
                "financial": financial_payload.get("meta", {}),
                "money_flow": money_payload.get("meta", {}),
                "news_bundle": news_payload.get("meta", {}),
            }

            def _add_missing(ref: str, summary: str):
                missing_refs.append(ref)
                _add(ref, summary)

            def _add(ref: str, summary: str, value: Any = None, url: str = ""):
                entry = {"ref": ref, "summary": summary}
                if value is not None:
                    entry["value"] = value
                if url:
                    entry["url"] = url
                ev.append(entry)

            # provider trace failures
            for mod, traces in (provider_trace or {}).items():
                for tr in traces or []:
                    if tr.get("success") is False:
                        errs = tr.get("errors") or []
                        msg = errs[0].get("message") if errs and isinstance(errs[0], dict) else "provider failure"
                        _add(f"$.provider_trace.{mod}.{tr.get('provider')}", f"{mod} provider {tr.get('provider')} failed: {msg}")

            # Missing critical fields
            for key in ["pe_ttm", "pb", "roe", "revenue_yoy", "profit_yoy", "gross_margin", "report_period"]:
                if fin_data.get(key) in (None, "", "--"):
                    _add_missing(f"$.financial.{key}", f"财务字段缺失: {key}")

            for key in ["main_net_inflow", "super_large", "large", "mid", "small"]:
                if money_data.get(key) in (None, "", "--"):
                    _add_missing(f"$.money_flow.{key}", f"资金流字段缺失: {key}")

            news_sections = ["announcements", "reports", "hot_events"]
            missing_news = [k for k in news_sections if not news_data.get(k)]
            if len(missing_news) == len(news_sections):
                _add_missing("$.news_bundle", "新闻/公告为空，需补充信息披露")
            elif missing_news:
                _add_missing("$.news_bundle.sections", f"资讯缺少: {', '.join(missing_news)}")

            if not kline_rows_local:
                _add_missing("$.kline.daily", "日线为空，需检查行情链路")
            else:
                last_row = kline_rows_local[-1]
                _add("$.kline.daily.last_close", f"最新收盘 {last_row.get('close')} @ {last_row.get('date')}", last_row.get("close"))
                if len(kline_rows_local) >= 2:
                    prev_row = kline_rows_local[-2]
                    if isinstance(prev_row, dict) and prev_row.get("close") is not None and last_row.get("close") is not None:
                        mom = (float(last_row["close"]) - float(prev_row["close"])) / float(prev_row["close"]) * 100
                        _add("$.kline.daily.momentum", f"近1日动量 {mom:.2f}%", mom)
                if len(kline_rows_local) >= 20:
                    closes = [r.get("close") for r in kline_rows_local[-20:] if isinstance(r, dict)]
                    closes = [c for c in closes if c is not None]
                    if closes:
                        avg20 = sum(closes) / len(closes)
                        _add("$.kline.daily.avg20", f"20日均价 {avg20:.2f}", avg20)

            if quote.get("price") is not None:
                _add("$.quote.price", f"现价 {quote.get('price')}", quote.get("price"))
            if fin_data.get("pe_ttm") is not None:
                _add("$.financial.pe_ttm", f"市盈率TTM {fin_data.get('pe_ttm')}", fin_data.get("pe_ttm"))
            if fin_data.get("roe") is not None:
                _add("$.financial.roe", f"ROE {fin_data.get('roe')}%", fin_data.get("roe"))
            if fin_data.get("revenue_yoy") is not None:
                _add("$.financial.revenue_yoy", f"营收同比 {fin_data.get('revenue_yoy')}%", fin_data.get("revenue_yoy"))
            if fin_data.get("gross_margin") is not None:
                _add("$.financial.gross_margin", f"毛利率 {fin_data.get('gross_margin')}%", fin_data.get("gross_margin"))
            if not fin_data:
                _add("$.financial", "财务数据缺失，建议观望")
            if money_data.get("main_net_inflow") is not None:
                _add("$.money_flow.main_net_inflow", f"主力净流入 {money_data.get('main_net_inflow')}", money_data.get("main_net_inflow"))
            if money_data.get("super_large") is not None:
                _add("$.money_flow.super_large", "超大单净流", money_data.get("super_large"))
            if not money_data:
                _add("$.money_flow", "资金流缺失，无法判断主力态度")
            if news_data.get("announcements"):
                ann = news_data.get("announcements", [])[0]
                _add("$.news_bundle.announcements[0]", ann.get("title", "公告"), url=ann.get("url", ""))
            if news_data.get("reports"):
                rep = news_data.get("reports", [])[0]
                _add("$.news_bundle.reports[0]", rep.get("title", "研报"), url=rep.get("url", ""))
            if news_data.get("hot_events"):
                hot = news_data.get("hot_events", [])[0]
                _add("$.news_bundle.hot_events[0]", hot.get("title", "热点"), url=hot.get("url", ""))
            if not any(news_data.get(k) for k in ["announcements", "reports", "hot_events"]):
                _add("$.news_bundle", "新闻/公告缺失，需关注信息披露")

            # Next steps checklist
            _add("$.next_steps.smoke", "建议重跑 smoke_single_stock <code> 并检查代理/网络")
            _add("$.next_steps.provider", "确认东财/腾讯接口是否可访问，必要时切换代理")

            while len(ev) < 5:
                _add("$.diagnostics", "关键信息缺失，建议谨慎观望")

            score = 0
            pe = fin_data.get("pe_ttm")
            roe = fin_data.get("roe")
            rev = fin_data.get("revenue_yoy")
            money = money_data.get("main_net_inflow")
            if pe is not None:
                if pe < 25:
                    score += 1
                elif pe > 60:
                    score -= 1
            if roe is not None and roe > 12:
                score += 1
            if rev is not None and rev > 5:
                score += 1
            if money is not None:
                if money > 0:
                    score += 1
                else:
                    score -= 1
            if news_data.get("announcements") and news_data.get("reports"):
                score += 1

            action = "WATCH"
            module_missing = any((diag_meta_map.get(m, {}).get("filled_metrics") or 0) == 0 for m in diag_meta_map)
            rationale_parts = []
            if module_missing or missing_refs:
                rationale_parts.append("数据不完整，采取保守决策")

            if not module_missing and ev:
                if score >= 3:
                    action = "BUY"
                    rationale_parts.append("估值、盈利、资金、资讯综合得分较高")
                elif score >= 1:
                    action = "HOLD"
                    rationale_parts.append("指标表现尚可，但需要持续跟踪")
                elif score <= -1:
                    action = "AVOID"
                    rationale_parts.append("估值或资金流不利，暂不介入")
                else:
                    action = "WATCH"
                    rationale_parts.append("信号中性，继续观察")
            else:
                action = "WATCH"
                rationale_parts.append("关键模块缺失，仅提供观望建议")

            rationale = "; ".join(rationale_parts) if rationale_parts else "规则决策：估值、盈利、资金、资讯综合打分"
            return {"evidence": ev, "action": action, "rationale": rationale, "missing_paths": missing_refs}

        advice_pack = _build_evidence_and_advice()
        evidence_pack = advice_pack.get("evidence", [])

        meta_map = {
            "quote": basic_meta.get("quote", {}),
            "identity": basic_meta.get("identity", {}),
            "kline": kline_meta,
            "financial": financial_payload.get("meta", {}),
            "money_flow": money_payload.get("meta", {}),
            "news_bundle": news_payload.get("meta", {}),
        }

        diagnostics = []
        for module_key, label in [
            ("quote", "quote"),
            ("identity", "identity"),
            ("kline", "kline_daily"),
            ("financial", "financial"),
            ("money_flow", "money_flow"),
            ("news_bundle", "news_bundle"),
        ]:
            mm = meta_map.get(module_key, {})
            diagnostics.append({
                "module": label,
                "source": mm.get("source"),
                "fallback_used": mm.get("fallback_used"),
                "cache_hit": mm.get("cache_hit"),
                "ttl_sec": mm.get("ttl_sec"),
                "retrieved_at": mm.get("retrieved_at") or mm.get("ts"),
                "filled": mm.get("filled_metrics"),
                "errors_count": len(mm.get("errors") or []),
            })

        result = {
            "code": code_std,
            "quote": quote,
            "identity": identity,
            "kline": kline_data,
            "financial": financial_payload.get("data", {}),
            "money_flow": money_payload.get("data", {}),
            "news_bundle": news_payload.get("data", {}),
            "diagnostics": diagnostics,
            "evidence_pack": evidence_pack,
            "advice": advice_pack,
            "provider_trace": provider_trace,
            "_meta": meta_map,
        }

        return DataEngine._json_safe(result)

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