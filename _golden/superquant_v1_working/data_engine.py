# -*- coding: utf-8 -*-
"""
data_engine.py
==============
全息数据引擎（商用极速版 V3.0）

【修复日志】
1. 财务数据：弃用笨重的 'financial_analysis_indicator'，改用轻量级 'financial_abstract' (F10)，解决超时/NULL问题。
2. 资金数据：修复主力净流入接口，增加清洗逻辑，确保拿到最新交易日数据。
3. 稳定性：全链路增加重试机制，防止单点故障。
"""

from __future__ import annotations

import datetime as _dt
import re
import time
from typing import Dict, Any, Optional, List

import pandas as pd
import numpy as np

try:
    import akshare as ak
except Exception:
    ak = None

from universe_cache import UniverseCache


def _now_str() -> str:
    return _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _safe_float(x, default=np.nan):
    """
    清洗各种奇怪的数值格式
    """
    try:
        if x is None:
            return default
        s = str(x).strip()
        if s in ("", "--", "None", "nan", "NaN", "null"):
            return default
        # 移除中文单位和标点
        s = s.replace("亿", "").replace("万", "").replace("%", "").replace(",", "")
        return float(s)
    except Exception:
        return default


def normalize_code(code: str) -> str:
    code = str(code).strip()
    # 移除后缀
    code = re.sub(r"\.(SH|SZ|BJ|sh|sz|bj)$", "", code)
    if code.isdigit() and len(code) < 6:
        code = code.zfill(6)
    return code


class DataEngine:
    _printed = False

    def __init__(self, cache: Optional[UniverseCache] = None):
        self.cache = cache or UniverseCache()
        if not DataEngine._printed:
            DataEngine._printed = True
            print(f"⚙️ [情报局] 全息数据引擎(Pro V3) 已加载 ({_now_str()})")

    # --- 核心：带重试的请求装饰器 ---
    def _retry_call(self, func, *args, max_retries=3, **kwargs):
        """执行带有重试机制的函数调用"""
        last_err = None
        for i in range(max_retries):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                last_err = e
                # 只有在调试模式下才打印重试信息，避免刷屏
                # print(f"⚠️ [Retrying] {func.__name__}: {e}")
                time.sleep(1) 
        
        print(f"❌ [API Failed] {func.__name__}: {str(last_err)}")
        return None

    def _fuzzy_get(self, df: pd.DataFrame, candidates: List[str]) -> Optional[str]:
        for c in candidates:
            if c in df.columns:
                return c
        return None

    # ------------------------------------------------------------------
    # 0) 全市场快照 (行情基石)
    # ------------------------------------------------------------------

    def get_spot_snapshot(self, ttl_seconds: int = 180) -> pd.DataFrame:
        cached = self.cache.get_spot_snapshot(ttl_seconds=ttl_seconds)
        if cached is not None and isinstance(cached, pd.DataFrame) and not cached.empty:
            return cached

        if ak is None:
            return pd.DataFrame()

        def _fetch():
            return ak.stock_zh_a_spot_em()

        df = self._retry_call(_fetch, max_retries=3)

        if df is None or df.empty:
            return pd.DataFrame()

        # 智能映射
        col_code = self._fuzzy_get(df, ["代码", "股票代码", "symbol", "code"])
        col_name = self._fuzzy_get(df, ["名称", "股票简称", "name"])
        col_close = self._fuzzy_get(df, ["最新价", "最新", "price", "close"])
        col_pct = self._fuzzy_get(df, ["涨跌幅", "涨跌幅(%)", "pct_chg"])
        col_mcap = self._fuzzy_get(df, ["总市值", "总市值(元)", "market_cap"])
        col_pe = self._fuzzy_get(df, ["市盈率-动态", "市盈率", "pe"])
        col_pb = self._fuzzy_get(df, ["市净率", "pb"])
        col_vol = self._fuzzy_get(df, ["成交量", "成交量(手)", "volume"])

        if not col_code:
            return pd.DataFrame()

        out = pd.DataFrame()
        out["code"] = df[col_code].astype(str).map(normalize_code)
        out["name"] = df[col_name].astype(str) if col_name else ""
        out["close"] = pd.to_numeric(df[col_close], errors="coerce") if col_close else np.nan
        out["pct"] = pd.to_numeric(df[col_pct], errors="coerce") if col_pct else np.nan
        
        if col_mcap:
            # 兼容 akshare 有时候返回元，有时候返回亿的情况，这里假设是元，转亿
            # 注意：stock_zh_a_spot_em 返回的是元
            out["market_cap"] = pd.to_numeric(df[col_mcap], errors="coerce") / 1e8
        else:
            out["market_cap"] = np.nan

        out["pe"] = pd.to_numeric(df[col_pe], errors="coerce") if col_pe else np.nan
        out["pb"] = pd.to_numeric(df[col_pb], errors="coerce") if col_pb else np.nan
        out["volume"] = pd.to_numeric(df[col_vol], errors="coerce") if col_vol else np.nan
        out["turnover"] = pd.to_numeric(df[self._fuzzy_get(df, ["换手率", "turnover"])], errors="coerce") if self._fuzzy_get(df, ["换手率", "turnover"]) else np.nan

        out = out.dropna(subset=["code"]).drop_duplicates(subset=["code"]).reset_index(drop=True)
        
        if not out.empty:
            self.cache.set_spot_snapshot(out)
        
        return out

    def get_spot_row(self, code: str, ttl_seconds: int = 180) -> Dict[str, Any]:
        code = normalize_code(code)
        # 强制走快照逻辑，因为单股接口容易被封且慢
        df = self.get_spot_snapshot(ttl_seconds=ttl_seconds)
        
        default_ret = {
            "code": code, "name": "未知", 
            "close": np.nan, "pct": np.nan, 
            "market_cap": np.nan, "pe": np.nan, "pb": np.nan, "turnover": np.nan
        }

        if df is None or df.empty:
            return default_ret

        row = df[df["code"] == code]
        if row.empty:
            return default_ret
            
        return row.iloc[0].to_dict()

    # ------------------------------------------------------------------
    # 1) 身份证/行业
    # ------------------------------------------------------------------
    def get_stock_identity(self, symbol: str) -> Dict[str, Any]:
        symbol = normalize_code(symbol)
        ck = self.cache.key("identity", {"symbol": symbol})
        cached = self.cache.get(ck, ttl=24 * 3600)
        if isinstance(cached, dict) and cached: return cached

        identity = {"code": symbol, "name": "未知", "sector": "未知", "launch_date": "--"}
        if ak is None: return identity

        # 优先从快照拿名字，快
        spot = self.get_spot_row(symbol)
        if spot.get("name") and spot.get("name") != "未知":
            identity["name"] = spot["name"]

        # 查行业
        def _fetch():
            return ak.stock_individual_info_em(symbol=symbol)

        try:
            df = self._retry_call(_fetch, max_retries=1)
            if df is not None and not df.empty:
                # 转为字典
                info = dict(zip(df.iloc[:, 0], df.iloc[:, 1]))
                identity["sector"] = str(info.get("行业", identity["sector"]))
                identity["launch_date"] = str(info.get("上市时间", identity["launch_date"]))
                if identity["name"] == "未知":
                    identity["name"] = str(info.get("股票简称", identity["name"]))
        except:
            pass

        self.cache.set(ck, identity)
        return identity

    # ------------------------------------------------------------------
    # 2) K线
    # ------------------------------------------------------------------
    def get_kline(self, symbol: str, timeframe: str = "D", limit: int = 500) -> pd.DataFrame:
        symbol = normalize_code(symbol)
        period_map = {"D": "daily", "W": "weekly", "M": "monthly"}
        period = period_map.get(timeframe.upper(), "daily")

        ck = self.cache.key("kline", {"s": symbol, "tf": timeframe, "l": limit})
        cached = self.cache.get_df(ck, ttl=600)
        if cached is not None and not cached.empty:
            return cached

        if ak is None: return pd.DataFrame()

        def _fetch():
            return ak.stock_zh_a_hist(symbol=symbol, period=period, adjust="qfq")

        try:
            df = self._retry_call(_fetch, max_retries=3)
        except:
            df = None

        if df is None or df.empty:
            return pd.DataFrame()

        c_date = self._fuzzy_get(df, ["日期", "date"])
        if not c_date: return pd.DataFrame()

        out = pd.DataFrame()
        out["date"] = pd.to_datetime(df[c_date], errors="coerce")
        out["open"] = pd.to_numeric(df["开盘"], errors="coerce")
        out["high"] = pd.to_numeric(df["最高"], errors="coerce")
        out["low"] = pd.to_numeric(df["最低"], errors="coerce")
        out["close"] = pd.to_numeric(df["收盘"], errors="coerce")
        out["volume"] = pd.to_numeric(df["成交量"], errors="coerce")

        out = out.dropna(subset=["date"]).sort_values("date")
        if limit: out = out.tail(limit)
        
        self.cache.set_df(ck, out.reset_index(drop=True))
        return out

    # ------------------------------------------------------------------
    # 3) 深度财务 (核心修复：改用 Light 接口)
    # ------------------------------------------------------------------
    def get_deep_financials(self, symbol: str) -> Dict[str, Any]:
        symbol = normalize_code(symbol)
        ck = self.cache.key("fin_lite", {"s": symbol})
        cached = self.cache.get(ck, ttl=24*3600)
        if isinstance(cached, dict) and cached: return cached

        fin = {
            "roe": "NULL", "gross_margin": "NULL", "net_margin": "NULL", 
            "rev_yoy": "NULL", "profit_yoy": "NULL"
        }
        if ak is None: return fin

        # 策略：使用 stock_financial_abstract (F10摘要)，速度快，数据全
        def _fetch_abstract():
            return ak.stock_financial_abstract(symbol=symbol)

        try:
            df = self._retry_call(_fetch_abstract, max_retries=2)
            if df is not None and not df.empty:
                # df columns 类似: ['截止日期', '净利润', '净利润同比增长率', '营业收入', '营业收入同比增长率', '净资产收益率', '每股收益']
                # 取最新一期 (通常第一行或最后一行，akshare abstract 通常是按日期降序，即 row 0 是最新的)
                # 检查日期，确保不是太旧
                
                # 某些时候数据可能是按时间升序，我们需要按日期排个序
                if "截止日期" in df.columns:
                    df["截止日期"] = pd.to_datetime(df["截止日期"], errors="coerce")
                    df = df.sort_values("截止日期", ascending=True) # 升序，最后一行是最新
                
                last = df.iloc[-1]
                
                # 提取数据
                fin["roe"] = _safe_float(last.get("净资产收益率"))
                fin["rev_yoy"] = _safe_float(last.get("营业收入同比增长率"))
                fin["profit_yoy"] = _safe_float(last.get("净利润同比增长率"))
                
                # 毛利率 Abstract 里可能没有，如果没有就留空，或者尝试计算 (营业收入-营业成本)/营业收入
                # 为了速度，这里不再请求 heavy 接口。如果非要，可以尝试 stock_hk_ggt_components_em 这种偏门但快的，或者放弃。
                # 实际上 F10 摘要里通常有核心数据。
                
        except Exception:
            pass
        
        self.cache.set(ck, fin)
        return fin

    # ------------------------------------------------------------------
    # 4) 资金博弈 (修复：确保取到最新日)
    # ------------------------------------------------------------------
    def get_game_data(self, symbol: str) -> Dict[str, Any]:
        symbol = normalize_code(symbol)
        ck = self.cache.key("game_v2", {"s": symbol})
        cached = self.cache.get(ck, ttl=1800) # 资金流盘中变化快，缓存短点
        if isinstance(cached, dict) and cached: return cached

        game = {"main_flow": "NULL"}
        if ak is None: return game
        
        def _fetch_flow():
            # 东方财富个股资金流接口
            return ak.stock_fund_flow_individual(symbol=symbol)
            
        try:
            df = self._retry_call(_fetch_flow, max_retries=2)
            if df is not None and not df.empty:
                # 确保按日期升序，取最后一行（最新）
                if "日期" in df.columns:
                    df = df.sort_values("日期", ascending=True)
                    last_row = df.iloc[-1]
                    val = last_row.get("主力净流入净额") # 注意列名
                    
                    # 转为万/亿显示
                    f_val = _safe_float(val)
                    if not np.isnan(f_val):
                        # 原单位通常是元
                        if abs(f_val) > 100000000:
                            game["main_flow"] = f"{f_val/100000000:.2f} 亿"
                        elif abs(f_val) > 10000:
                            game["main_flow"] = f"{f_val/10000:.2f} 万"
                        else:
                            game["main_flow"] = f"{f_val:.2f} 元"
        except:
            pass

        self.cache.set(ck, game)
        return game

    # ------------------------------------------------------------------
    # 5) RAG 资讯
    # ------------------------------------------------------------------
    def get_report_rag(self, symbol: str, limit: int = 10) -> Dict[str, Any]:
        symbol = normalize_code(symbol)
        ck = self.cache.key("rag", {"s": symbol, "l": limit})
        cached = self.cache.get(ck, ttl=1800) 
        if isinstance(cached, dict) and cached: return cached

        out = {"status": "ok", "items": [], "source": "unknown"}
        if ak is None:
            out["status"] = "error"
            return out

        items = []
        
        # 策略A：个股新闻
        try:
            def _fetch_news():
                return ak.stock_news_em(symbol=symbol)
            
            df = self._retry_call(_fetch_news, max_retries=1) # 资讯失败就算了，不重试太多
            if df is not None and not df.empty:
                out["source"] = "stock_news_em"
                for _, row in df.head(limit).iterrows():
                    title = str(row.get("新闻标题") or row.get("title") or "")
                    content = str(row.get("新闻内容") or row.get("content") or "")
                    date = str(row.get("发布时间") or row.get("time") or "")
                    if title:
                        items.append({"title": title, "summary": content[:100], "time": date, "source": "News"})
        except Exception:
            pass

        out["items"] = items
        if not items:
            out["status"] = "empty"
        
        self.cache.set(ck, out)
        return out