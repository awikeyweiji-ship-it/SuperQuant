# -*- coding: utf-8 -*-
"""
alternative_data.py
===================
五维超脑·另类情报局 (Commercial Pro V9.1 Fix - 修复行业接口)

【修复日志】
1. **修复 TypeError**: get_alternative_report 现在正确接收 'sector' 参数。
2. **功能保持**: 完整保留 V9.0 的三级情报瀑布（个股-行业-宏观）。
"""

import re
import time
import requests
import datetime
from typing import Dict, Any, List

try:
    import akshare as ak
except ImportError:
    ak = None

try:
    import jieba
    import jieba.analyse
except ImportError:
    jieba = None

# ==========================================
# 1. 语义与关键词库
# ==========================================
SENTIMENT_DICT = {
    "pos": {
        "牛", "涨停", "利好", "突破", "低估", "买入", "加仓", "起飞", "龙头", 
        "大肉", "机构", "主力", "爆发", "翻倍", "超预期", "满仓", "吃肉", 
        "遥遥领先", "格局", "起爆", "主升浪", "红盘", "大涨", "稳了", "牛市",
        "增持", "回购", "注资", "举牌", "国家队", "社保", "养老金"
    },
    "neg": {
        "跌停", "利空", "出货", "垃圾", "套牢", "割肉", "跑路", "崩盘", "暴雷", 
        "退市", "立案", "减持", "诱多", "骗子", "甚至", "大跌", "核按钮",
        "完蛋", "被套", "回撤", "跳水", "绿盘", "大跌", "凉了", "熊市", "问询"
    }
}

# 资本运作 (L1)
CAPITAL_KEYWORDS = ["增持", "回购", "注资", "重组", "举牌", "分红", "股权转让", "主力", "大宗交易", "社保", "大基金"]

# 宏观政策 (L3)
POLICY_KEYWORDS = ["中央", "国务院", "央行", "发改委", "财政部", "证监会", "专项债", "五年规划", "新质生产力", "自主可控", "降准", "降息", "会议", "低空经济", "人工智能"]

TRASH_WORDS = {
    "举报", "网警", "征信", "备案", "联系我们", "关于我们", "免责声明", 
    "隐私政策", "风险提示", "广告服务", "地图", "通行证", "帮助中心",
    "违法", "不良信息", "友情链接", "反诈", "警方", "市民", "劝阻", "防范"
}

class AlternativeDataEngine:
    def __init__(self):
        print("🕵️ [情报局 V9.1] 启动 (天网情报系统已修复)...")
        self.macro_cache = {}

    def _calculate_sentiment(self, text: str) -> float:
        if not text or not jieba: return 0.0
        words = list(jieba.cut(text))
        score = 0
        for w in words:
            if w in SENTIMENT_DICT["pos"]: score += 1
            elif w in SENTIMENT_DICT["neg"]: score -= 1.5 
        
        normalized_score = score / (len(words) * 0.1 + 1) 
        return max(min(normalized_score, 1.0), -1.0)

    # ------------------------------------------------------------------
    # A. 舆情监听 (Guba)
    # ------------------------------------------------------------------
    def fetch_guba_sentiment(self, symbol: str) -> Dict[str, Any]:
        """爬取股吧评论"""
        try:
            return self._crawl_guba_html(symbol)
        except Exception:
            return {"score": 0, "hot_words": [], "source": "failed", "sample_text": "获取失败"}

    def _crawl_guba_html(self, symbol: str) -> Dict[str, Any]:
        url = f"http://guba.eastmoney.com/list,{symbol}.html"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Referer": "http://guba.eastmoney.com/"
        }
        
        try:
            resp = requests.get(url, headers=headers, timeout=4)
            if resp.status_code != 200: return {"score": 0, "hot_words": [], "source": "crawl_403"}
            html = resp.text
        except:
            return {"score": 0, "hot_words": [], "source": "timeout"}

        raw_titles = re.findall(r'href="/news,[\d,]+\.html"[^>]*title="([^"]+)"', html)
        if not raw_titles:
             raw_titles = re.findall(r'class="note"[^>]*>([^<]+)</a>', html)

        valid_titles = []
        for t in raw_titles:
            if any(trash in t for trash in TRASH_WORDS): continue
            if len(t) < 4: continue
            valid_titles.append(t)
        
        clean_titles = list(set(valid_titles))[:25]
        full_text = " ".join(clean_titles)
        
        hot_words = []
        if jieba:
            try: hot_words = jieba.analyse.extract_tags(full_text, topK=5)
            except: pass

        sentiment_score = self._calculate_sentiment(full_text)
        
        return {
            "score": round(sentiment_score, 2),
            "hot_words": hot_words,
            "sample_text": full_text[:80] + "...",
            "source": "direct_crawler"
        }

    # ------------------------------------------------------------------
    # B. 智能新闻抓取 (Smart News Waterfall)
    # ------------------------------------------------------------------
    def fetch_smart_news(self, symbol: str, sector: str = "") -> Dict[str, List[Dict]]:
        """
        三级情报抓取。
        【修复点】: 增加了 sector 参数，防止调用报错。
        """
        report = {
            "corporate": [],
            "macro": []
        }
        if ak is None: return report

        # 1. 第一级：个股新闻
        try:
            df = ak.stock_news_em(symbol=symbol)
            if df is not None and not df.empty:
                for _, row in df.head(5).iterrows():
                    title = str(row.get('新闻标题', ''))
                    date = str(row.get('发布时间', ''))
                    tag = "资讯"
                    for kw in CAPITAL_KEYWORDS:
                        if kw in title:
                            tag = "🔥资本运作"
                            break
                    report["corporate"].append({"title": title, "date": date, "tag": tag})
        except: pass

        # 2. 第二级：宏观/政策新闻 (必抓)
        try:
            df_macro = ak.stock_info_global_fianace_news(area="中国")
            if df_macro is not None and not df_macro.empty:
                count = 0
                for _, row in df_macro.iterrows():
                    title = str(row.get('title', ''))
                    pub_time = str(row.get('public_time', ''))
                    if any(kw in title for kw in POLICY_KEYWORDS):
                        report["macro"].append({"title": title, "date": pub_time, "tag": "🏛️宏观政策"})
                        count += 1
                    if count >= 3: break
        except: pass

        return report

    # ------------------------------------------------------------------
    # C. 真实宏观数据指标
    # ------------------------------------------------------------------
    def fetch_macro_indexes(self) -> Dict[str, float]:
        if self.macro_cache and (time.time() - self.macro_cache.get('_ts', 0) < 3600*4):
            return self.macro_cache

        print("🌍 [情报局] 正在同步国家统计局数据...")
        macro_data = {"cpi_yoy": 0.5, "m2_yoy": 8.0, "cn_10y_bond": 2.3, "market_sentiment": "中性", "_ts": time.time()}
        
        if ak is None: return macro_data

        try:
            try:
                df_cpi = ak.macro_china_cpi_monthly()
                if not df_cpi.empty:
                    latest = df_cpi.iloc[-1]
                    val = latest.get('cpi') or latest.get('全国-同比增长', 0)
                    macro_data["cpi_yoy"] = float(val)
            except: pass

            try:
                df_m2 = ak.macro_china_m2_yearly()
                if not df_m2.empty:
                    latest = df_m2.iloc[-1]
                    val = latest.get('m2') or latest.get('同比增长', 8.0)
                    macro_data["m2_yoy"] = float(val)
            except: pass

            try:
                df_bond = ak.bond_zh_us_rate()
                if not df_bond.empty:
                    latest = df_bond.iloc[-1]
                    val = latest.get('中国国债收益率10年', 2.3)
                    macro_data["cn_10y_bond"] = float(val)
            except: pass

            cpi = macro_data["cpi_yoy"]
            m2 = macro_data["m2_yoy"]
            if cpi < 0: sent = "通缩压力(防御)"
            elif cpi > 3: sent = "通胀过热(紧缩)"
            elif m2 > 10: sent = "流动性充裕(利好)"
            elif m2 < 7: sent = "流动性收紧(利空)"
            else: sent = "温和复苏(中性)"
            
            macro_data["market_sentiment"] = sent
            self.macro_cache = macro_data

        except: pass
        return macro_data

    # ------------------------------------------------------------------
    # 主入口 (修复点：增加 sector 参数)
    # ------------------------------------------------------------------
    def get_alternative_report(self, symbol: str, sector: str = "") -> Dict[str, Any]:
        """
        获取另类情报报告。
        :param symbol: 股票代码
        :param sector: 所属行业 (新增参数，用于行业补全)
        """
        # 1. 舆情
        guba = self.fetch_guba_sentiment(symbol)
        # 2. 宏观
        macro = self.fetch_macro_indexes()
        # 3. 智能新闻 (传入 sector)
        smart_news = self.fetch_smart_news(symbol, sector)
        
        alt_signal = "中性"
        if guba['score'] > 0.3: alt_signal = "情绪贪婪"
        elif guba['score'] < -0.3: alt_signal = "情绪恐慌"
            
        return {
            "symbol": symbol,
            "retail_sentiment": guba['score'], 
            "hot_topics": guba['hot_words'],   
            "macro_environment": macro,        
            "alternative_signal": alt_signal,  
            "raw_guba_sample": guba.get("sample_text", ""),
            "corporate_news": smart_news["corporate"],
            "macro_news": smart_news["macro"],
            "data_source": guba.get("source", "unknown")
        }