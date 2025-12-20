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
import logging
import requests
from typing import Dict, Any, Optional, List
import pandas as pd
import numpy as np

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
        self.cache = cache or UniverseCache()
        self.alt_engine = AlternativeDataEngine() if AlternativeDataEngine else None
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

    def _market_prefix(self, code: str) -> str:
        code = normalize_code(code)
        if code.startswith('6'): return 'sh'
        if code.startswith(('0','3')): return 'sz'
        if code.startswith(('8','4')): return 'bj'
        return 'sz'

    def _fetch_quote_tencent(self, code: str) -> Dict[str, Any]:
        # Fallback single-symbol quote via Tencent (qt.gtimg.cn).
        code = normalize_code(code)
        try:
            px = self._market_prefix(code)
            q = f's_{px}{code}'
            url = f'https://qt.gtimg.cn/q={q}'
            r = requests.get(url, timeout=6)
            txt = (r.text or '').strip()
            if '~' not in txt:
                return {}
            # v_s_sz000001="51~NAME~000001~PRICE~CHG~PCT~...";
            m = re.search(r'"(.*)"', txt)
            payload = m.group(1) if m else txt
            parts = payload.split('~')
            if len(parts) < 6:
                return {}
            name = parts[1].strip()
            price = parts[3].strip()
            pct = parts[5].strip()
            out = {
                'code': code,
                'name': name,
                'close': _safe_float(price, 0.0),
                'pct_chg': _safe_float(pct, 0.0),
                'source': 'tencent'
            }
            return out
        except Exception:
            return {}

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
                    return df_norm

        # 3) 东财 push2 兜底
        try:
            df_em = self._retry_call(self._fetch_spot_snapshot_eastmoney, max_retries=2)
            df_em = _normalize(df_em)
            if df_em is not None and not df_em.empty:
                self.cache.set_spot_snapshot(df_em)
                self.spot_source = "eastmoney_push2"
                return df_em
        except Exception:
            pass

        # 4) 历史缓存兜底（无 TTL）
        stale = self.cache.get_df("spot_snapshot", ttl=None)
        if stale is not None and not stale.empty:
            self.spot_is_stale = True
            self.spot_source = "stale_cache"
            return stale

        return pd.DataFrame()

    def get_spot_row(self, code: str) -> Dict[str, Any]:
        df = self.get_spot_snapshot()
        if df is not None and not df.empty:
            rows = df[df["code"] == normalize_code(code)]
            if not rows.empty:
                return rows.iloc[0].to_dict()
        # fallback for single symbol
        fb = self._fetch_quote_tencent(code)
        return fb if isinstance(fb, dict) else {}

    # -------------------------------------
    # 3. 身份与行业
    # -------------------------------------
    def get_stock_identity(self, code: str) -> Dict[str, Any]:
        code = normalize_code(code)
        ck = self.cache.key("identity_v12", {"s": code})
        cached = self.cache.get(ck, ttl=7 * 24 * 3600) 
        if isinstance(cached, dict) and cached: return cached

        data = {"code": code, "name": "未知", "sector": "未知", "concepts": []}
        spot = self.get_spot_row(code)
        if spot: data["name"] = spot.get("name", "未知")

        if ak:
            try:
                def _fetch_info(): return ak.stock_individual_info_em(symbol=code)
                df_info = self._retry_call(_fetch_info)
                if df_info is not None and not df_info.empty:
                    info_dict = dict(zip(df_info.iloc[:, 0], df_info.iloc[:, 1]))
                    data["sector"] = str(info_dict.get("行业", "其他"))
            except: pass
        self.cache.set(ck, data)
        return data

    # -------------------------------------
    # 4. K线数据 (多周期)
    # -------------------------------------
    def get_kline(
        self,
        code: str,
        freq: str = "daily",
        limit: Optional[int] = 250,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> pd.DataFrame:
        """K线数据，支持按日期范围拉取（YYYYMMDD）。

        - freq: daily/weekly/monthly
        - start_date/end_date: 形如 20240101
        - limit: None 表示不截断
        """
        if ak is None:
            return pd.DataFrame()
        try:
            period_map = {"daily": "daily", "weekly": "weekly", "monthly": "monthly"}
            p = period_map.get(freq, "daily")

            kwargs = {"symbol": code, "period": p, "adjust": "qfq"}
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
        except Exception:
            return pd.DataFrame()
    # -------------------------------------
    # 5. 深度财务
    # -------------------------------------
    def get_financial_features(self, code: str) -> Dict[str, Any]:
        """财报/运营类特征（结构化输出）。

        - 数据源：优先 AkShare 的财务分析指标；失败则退化为缺省值。
        - 输出：基础指标 + 衍生评分（0~1）：fundamental_quality / fundamental_growth / ops_momentum
        """
        ck = f"fin:{code}"
        cached = self.cache.get(ck, ttl=3600 * 12)
        if cached is not None:
            return cached

        fin: Dict[str, Any] = {
            "roe": 0.0,
            "gross_margin": 0.0,
            "net_margin": 0.0,
            "operating_margin": 0.0,
            "profit_yoy": 0.0,
            "revenue_yoy": 0.0,
            "debt_ratio": 0.0,
            "op_cashflow": 0.0,
            "eps": 0.0,
            "report_date": "",

            # Step4 derived (0~1)
            "fundamental_quality": 0.0,
            "fundamental_growth": 0.0,
            "ops_momentum": 0.0,
        }

        if ak is not None:
            try:
                def _fetch_ind():
                    return ak.stock_financial_analysis_indicator(symbol=code)

                df = self._retry_call(_fetch_ind)
                if df is not None and not df.empty:
                    row = df.iloc[-1]

                    def _pick(*names):
                        for n in names:
                            try:
                                if n in row.index and pd.notna(row.get(n)):
                                    return row.get(n)
                            except Exception:
                                continue
                        return None

                    rd = _pick("日期", "报告期", "报告日期", "公告日期", "截止日期")
                    if rd is not None:
                        fin["report_date"] = str(rd)

                    fin["roe"] = _safe_float(_pick("净资产收益率(%)", "ROE(%)", "净资产收益率"))
                    fin["gross_margin"] = _safe_float(_pick("销售毛利率(%)", "毛利率(%)", "销售毛利率"))
                    fin["net_margin"] = _safe_float(_pick("销售净利率(%)", "净利率(%)", "销售净利率"))
                    fin["operating_margin"] = _safe_float(_pick("营业利润率(%)", "营业利润率"))
                    fin["profit_yoy"] = _safe_float(_pick("净利润增长率(%)", "净利润同比增长率(%)", "净利润增长率", "净利润同比"))
                    fin["revenue_yoy"] = _safe_float(_pick("营业收入增长率(%)", "营业收入同比增长率(%)", "营业收入增长率", "营收同比"))
                    fin["debt_ratio"] = _safe_float(_pick("资产负债率(%)", "资产负债率"))
                    fin["eps"] = _safe_float(_pick("摊薄每股收益(元)", "基本每股收益(元)", "每股收益(元)", "基本每股收益", "每股收益"))
                    fin["op_cashflow"] = _safe_float(_pick(
                        "经营活动产生的现金流量净额",
                        "经营现金流量净额",
                        "经营活动现金流量净额",
                        "经营活动现金流量",
                        "经营现金流",
                    ))
            except Exception:
                pass

        def _clip(x: float) -> float:
            return max(0.0, min(1.0, float(x)))

        # 归一化/衍生
        roe_score = _clip((fin["roe"] / 15.0 + 1) / 2)  # 15% ~ 0.5
        gm_score = _clip(fin["gross_margin"] / 50.0)
        debt_score = _clip(1.0 - fin["debt_ratio"] / 80.0)

        prof_score = _clip((fin["profit_yoy"] / 40.0 + 1) / 2)
        rev_score = _clip((fin["revenue_yoy"] / 30.0 + 1) / 2)

        fin["fundamental_quality"] = _clip(0.40 * roe_score + 0.30 * gm_score + 0.20 * debt_score + 0.10 * _clip(fin["net_margin"] / 30.0))
        fin["fundamental_growth"] = _clip(0.60 * prof_score + 0.40 * rev_score)

        # 经营现金流若为正... slight boost
        cf_bonus = 0.05 if fin["op_cashflow"] > 0 else 0.0
        fin["ops_momentum"] = _clip(0.50 + 0.40 * (fin["fundamental_growth"] - 0.50) + 0.10 * (fin["fundamental_quality"] - 0.50) + cf_bonus)

        self.cache.set(ck, fin)
        return fin

    def get_money_flow(self, code: str) -> Dict[str, Any]:
        """Money flow / capital intelligence (best effort).

        Returns keys (when available):
        - main_net_inflow_today: from spot snapshot (fast)
        - main_net_inflow_detail: from AkShare detail (optional)
        - northbound_net_inflow: market-level northbound summary (optional)
        """
        code = normalize_code(code)
        out: Dict[str, Any] = {}
        try:
            spot = self.get_spot_row(code)
            out['main_net_inflow_today'] = _safe_float(spot.get('main_net_inflow', spot.get('main_net_inflow_today', 0.0)), 0.0)
        except Exception:
            out['main_net_inflow_today'] = 0.0

        try:
            if self.capital_engine is not None:
                out.update(self.capital_engine.get_capital_features(code))
        except Exception:
            pass
        return out


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