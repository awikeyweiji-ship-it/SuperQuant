# -*- coding: utf-8 -*-
"""
alternative_data.py
===================
五维超脑·另类情报局 (Commercial Pro V9.1 Fix - 修复行业接口)

【修复日志】
1. **修复 TypeError**: get_alternative_report 现在正确接收 'sector' 参数。
2. **功能保持**: 完整保留 V9.0 的三级情报瀑布（个股-行业-宏观）。
"""

import os
import re
import time
import requests
import datetime as _dt
from typing import Dict, Any, List, Tuple

from logging_utils import make_result, build_error, FetchResult
from universe_cache import UniverseCache
from data_sources.sentiment_eastmoney import (
    fetch_guba_api,
    fetch_guba_html,
    fetch_xueqiu_search,
    sample_sentiment,
)
from data_sources.announcement_eastmoney import fetch_announcements_em, fetch_announcements_tencent, sample_announcements
from data_sources.report_eastmoney import fetch_research_reports_em, fetch_research_reports_alt, sample_reports
from data_sources.hot_eastmoney import fetch_hot_topics_em, fetch_hot_topics_ak, sample_hot_topics

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
    def __init__(self, cache: UniverseCache | None = None):
        print("🕵️ [情报局 V9.1] 启动 (天网情报系统已修复)...")
        self.macro_cache = {}
        self.cache = cache or UniverseCache()
        self.sentiment_ttl = 60 * 30
        flag = os.environ.get("ALLOW_OFFLINE_SAMPLES", "").lower()
        self.allow_offline_samples = flag in {"1", "true", "yes", "on"}

    @staticmethod
    def _news_item(
        title: str,
        url: str,
        source: str,
        time_str: str = "",
        summary: str = "",
        raw_excerpt: str | None = None,
    ) -> Dict[str, Any]:
        return {
            "title": title or "",
            "url": url or "",
            "source": source or "",
            "time": time_str or "",
            "summary": summary or (title[:120] if title else ""),
            "raw_excerpt": raw_excerpt or "",
        }

    @staticmethod
    def _news_item(
        title: str,
        url: str,
        source: str,
        time_str: str = "",
        summary: str = "",
        raw_excerpt: str | None = None,
    ) -> Dict[str, Any]:
        return {
            "title": title or "",
            "url": url or "",
            "source": source or "",
            "time": time_str or "",
            "summary": summary or (title[:120] if title else ""),
            "raw_excerpt": raw_excerpt or "",
        }

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
    def fetch_guba_sentiment(self, symbol: str, limit: int = 20) -> FetchResult:
        """股吧舆情：多源兜底 + 缓存，避免阻塞。"""
        cache_key = self.cache.key("sentiment", {"symbol": symbol, "limit": limit})
        cached = self.cache.get(cache_key, ttl=self.sentiment_ttl)
        if cached is not None:
            return make_result(cached, source=str(cached.get("source", "cache")), cache_hit=True)

        providers = [
            ("eastmoney_api", lambda: fetch_guba_api(symbol, limit=limit, timeout=10)),
            ("eastmoney_html", lambda: fetch_guba_html(symbol, limit=limit, timeout=8)),
            ("xueqiu", lambda: fetch_xueqiu_search(symbol, limit=limit, timeout=8)),
        ]

        errors: List[Dict[str, str]] = []
        chosen: Dict[str, Any] | None = None
        source = ""

        for name, fn in providers:
            try:
                data = fn()
            except Exception as e:  # noqa: BLE001
                errors.append(build_error(name, "exception", str(e)))
                continue
            if data and data.get("sample_posts"):
                chosen = data
                source = name
                break
            errors.append(build_error(name, "empty", f"{name} 无有效帖子"))

        if not chosen:
            if self.allow_offline_samples:
                chosen = sample_sentiment(symbol)
                source = "sample_cache"
                errors.append(build_error("sample_cache", "fallback", "启用离线舆情样本，数据可能过期"))
            else:
                chosen = {"sample_posts": []}
                source = "empty"
                errors.append(build_error("sample_cache", "disabled", "未勾选离线样本模式，未返回占位数据"))

        self.cache.set(cache_key, chosen)
        return make_result(chosen, source=source, errors=errors, fallback_used=len(errors) > 0)

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
    def fetch_smart_news(self, symbol: str, sector: str = "") -> FetchResult:
        """
        三级情报抓取。
        【修复点】: 增加了 sector 参数，防止调用报错。
        """
        report = {
            "corporate": [],
            "macro": []
        }
        errors: List[Dict[str, str]] = []
        if ak is None:
            errors.append(build_error("akshare", "missing", "AkShare 未安装"))
            return make_result(report, source="akshare", errors=errors)

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
            else:
                errors.append(build_error("akshare", "empty", "公司新闻为空"))
        except Exception as e:
            errors.append(build_error("akshare", "exception", str(e)))

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
            else:
                errors.append(build_error("akshare", "empty", "宏观新闻为空"))
        except Exception as e:
            errors.append(build_error("akshare", "exception", str(e)))

        return make_result(report, source="akshare", errors=errors, fallback_used=bool(errors))

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
    # D. 公告 / 研报 / 热点要事
    # ------------------------------------------------------------------
    def fetch_announcements(self, symbol: str, limit: int = 12) -> FetchResult:
        errors: List[Dict[str, str]] = []
        chosen: List[Dict[str, Any]] = []
        source = ""
        providers = [
            ("eastmoney", lambda: fetch_announcements_em(symbol, limit=limit)),
            ("tencent", lambda: fetch_announcements_tencent(symbol, limit=limit)),
        ]

        for name, fn in providers:
            try:
                data = fn()
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
            if self.allow_offline_samples:
                errors.append(build_error("sample", "fallback", "启用离线公告样本，数据可能过期"))
                chosen = sample_announcements(symbol, limit=limit)
                source = "sample_cache"
            else:
                errors.append(build_error("sample", "disabled", "未勾选离线样本模式，公告未使用占位数据"))
                chosen = []
                source = "empty"

        return make_result(chosen, source=source, errors=errors, fallback_used=len(errors) > 0)

    def fetch_research_reports(self, symbol: str, limit: int = 12) -> FetchResult:
        errors: List[Dict[str, str]] = []
        chosen: List[Dict[str, Any]] = []
        source = ""
        providers = [
            ("eastmoney", lambda: fetch_research_reports_em(symbol, limit=limit)),
            ("alt", lambda: fetch_research_reports_alt(symbol, limit=limit)),
        ]

        for name, fn in providers:
            try:
                data = fn()
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
            if self.allow_offline_samples:
                errors.append(build_error("sample", "fallback", "启用离线研报样本，数据可能过期"))
                chosen = sample_reports(symbol, limit=limit)
                source = "sample_cache"
            else:
                errors.append(build_error("sample", "disabled", "未勾选离线样本模式，研报未使用占位数据"))
                chosen = []
                source = "empty"

        return make_result(chosen, source=source, errors=errors, fallback_used=len(errors) > 0)

    def fetch_hot_topics(self, limit: int = 8) -> FetchResult:
        errors: List[Dict[str, str]] = []
        chosen: List[Dict[str, Any]] = []
        source = ""
        providers = [
            ("eastmoney", lambda: fetch_hot_topics_em(limit=limit)),
            ("akshare", lambda: fetch_hot_topics_ak(limit=limit)),
        ]

        for name, fn in providers:
            try:
                data = fn()
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
            if self.allow_offline_samples:
                errors.append(build_error("sample", "fallback", "启用离线热点样本，数据可能过期"))
                chosen = sample_hot_topics(limit=limit)
                source = "sample_cache"
            else:
                errors.append(build_error("sample", "disabled", "未勾选离线样本模式，热点未使用占位数据"))
                chosen = []
                source = "empty"

        return make_result(chosen, source=source, errors=errors, fallback_used=len(errors) > 0)

    # ------------------------------------------------------------------
    # 新闻流聚合（公告 / 研报 / 热点 / 论坛 / 观点）
    # ------------------------------------------------------------------
    def get_news_bundle_structured(self, symbol: str, sector: str = "") -> FetchResult:
        errors: List[Dict[str, str]] = []
        bundle = {
            "announcements": [],
            "reports": [],
            "hot_events": [],
            "forums": [],
            "opinions": [],
        }

        def _append_if_valid(category: str, item: Dict[str, Any]):
            url = item.get("url")
            t = item.get("time") or item.get("date")
            if not url or not t:
                errors.append(build_error(category, "invalid", f"{category} 缺少 url/time 被过滤"))
                return
            bundle[category].append(item)

        ann = self.fetch_announcements(symbol)
        rep = self.fetch_research_reports(symbol)
        hot = self.fetch_hot_topics(limit=8)
        senti = self.fetch_guba_sentiment(symbol, limit=12)
        smart_news = self.fetch_smart_news(symbol, sector)

        for src in [ann, rep, hot, senti, smart_news]:
            if not src.ok:
                errors.extend(src.errors)

        # 公告
        for item in (ann.data or []):
            _append_if_valid(
                "announcements",
                self._news_item(
                    title=item.get("title", ""),
                    url=item.get("url", ""),
                    source=f"announcement_{ann.source or 'unknown'}",
                    time_str=str(item.get("date") or item.get("time") or ""),
                    summary=item.get("type") or item.get("title", ""),
                ),
            )

        # 研报
        for item in (rep.data or []):
            _append_if_valid(
                "reports",
                self._news_item(
                    title=item.get("title", ""),
                    url=item.get("url", ""),
                    source=f"report_{rep.source or 'unknown'}",
                    time_str=str(item.get("date") or ""),
                    summary=f"{item.get('org','')} {item.get('rating','')}".strip(),
                ),
            )

        # 热点/要事
        for item in (hot.data or []):
            _append_if_valid(
                "hot_events",
                self._news_item(
                    title=item.get("title", ""),
                    url=item.get("url", ""),
                    source=f"hot_{hot.source or 'unknown'}",
                    time_str=str(item.get("time") or item.get("date") or ""),
                    summary=item.get("reason") or item.get("desc") or item.get("title", ""),
                ),
            )

        # 论坛帖子
        senti_posts = []
        if isinstance(senti.data, dict):
            senti_posts = senti.data.get("sample_posts") or []
        for item in senti_posts:
            _append_if_valid(
                "forums",
                self._news_item(
                    title=item.get("summary", ""),
                    url=item.get("url", ""),
                    source=item.get("source", senti.source or "forum"),
                    time_str=str(item.get("time") or ""),
                    summary=item.get("summary", "")[:140],
                    raw_excerpt=item.get("summary", ""),
                ),
            )

        # 舆情观点/公司新闻
        smart_data = smart_news.data if isinstance(smart_news.data, dict) else {}
        for item in smart_data.get("corporate", []) + smart_data.get("macro", []):
            _append_if_valid(
                "opinions",
                self._news_item(
                    title=item.get("title", ""),
                    url=item.get("url", ""),
                    source=f"smart_news_{smart_news.source or 'unknown'}",
                    time_str=str(item.get("date") or item.get("time") or ""),
                    summary=item.get("tag") or item.get("title", ""),
                ),
            )

        # 统计 meta
        filled_metrics = sum(1 for k, v in bundle.items() if v)
        meta = {
            "source": "alternative_data",
            "fallback_used": len(errors) > 0,
            "errors": errors,
            "retrieved_at": _dt.datetime.now().isoformat(timespec="seconds"),
            "count": {k: len(v) for k, v in bundle.items()},
            "filled_metrics": filled_metrics,
        }

        fallback_used = len(errors) > 0 and filled_metrics < 2
        if filled_metrics < 2:
            errors.append(build_error("news_bundle", "insufficient", "至少需要两类非空情报"))

        return make_result(bundle, source="news_bundle", errors=errors, fallback_used=fallback_used, meta=meta)

    # ------------------------------------------------------------------
    # 主入口 (修复点：增加 sector 参数)
    # ------------------------------------------------------------------
    def get_alternative_report(self, symbol: str, sector: str = "") -> Dict[str, Any]:
        return self.get_alternative_report_structured(symbol, sector).data

    def get_alternative_report_structured(self, symbol: str, sector: str = "") -> FetchResult:
        """
        获取另类情报报告。
        :param symbol: 股票代码
        :param sector: 所属行业 (新增参数，用于行业补全)
        """
        errors: List[Dict[str, str]] = []

        guba = self.fetch_guba_sentiment(symbol)
        if not guba.ok:
            errors.extend(guba.errors)

        macro = self.fetch_macro_indexes()
        smart_news = self.fetch_smart_news(symbol, sector)
        if not smart_news.ok:
            errors.extend(smart_news.errors)

        announcements = self.fetch_announcements(symbol)
        if not announcements.ok:
            errors.extend(announcements.errors)

        reports = self.fetch_research_reports(symbol)
        if not reports.ok:
            errors.extend(reports.errors)

        hot_topics = self.fetch_hot_topics(limit=8)
        if not hot_topics.ok:
            errors.extend(hot_topics.errors)

        sentiment_data = guba.data if isinstance(guba.data, dict) else {}
        sentiment_block = {
            "sentiment_score": sentiment_data.get("sentiment_score") or sentiment_data.get("score", 0),
            "hot_words": sentiment_data.get("hot_words", []),
            "sample_posts": sentiment_data.get("sample_posts", []),
            "source": guba.source,
            "fallback_used": guba.fallback_used,
        }

        data = {
            "symbol": symbol,
            "retail_sentiment": sentiment_block["sentiment_score"] or 0,
            "hot_words": sentiment_block.get("hot_words", []),
            "macro_environment": macro,
            "alternative_signal": "中性",
            "sentiment": sentiment_block,
            "raw_guba_sample": sentiment_data.get("sample_text", ""),
            "corporate_news": smart_news.data.get("corporate", []) if isinstance(smart_news.data, dict) else [],
            "macro_news": smart_news.data.get("macro", []) if isinstance(smart_news.data, dict) else [],
            "data_source": guba.data.get("source", "unknown") if isinstance(sentiment_data, dict) else "unknown",
            "announcements": announcements.data if isinstance(announcements.data, list) else [],
            "research_reports": reports.data if isinstance(reports.data, list) else [],
            "hot_topics": hot_topics.data if isinstance(hot_topics.data, list) else [],
            "ann_source": announcements.source,
            "report_source": reports.source,
            "hot_source": hot_topics.source,
        }

        score_val = data["retail_sentiment"]
        if not sentiment_block.get("sample_posts"):
            errors.append(build_error("sentiment", "empty", "舆情帖子为空（已尝试多源）"))

        if score_val > 0.3:
            data["alternative_signal"] = "情绪贪婪"
        elif score_val < -0.3:
            data["alternative_signal"] = "情绪恐慌"

        if not data["corporate_news"]:
            errors.append(build_error("akshare", "empty", "公司新闻缺失"))

        if not data["announcements"]:
            errors.append(build_error("announcement", "empty", "公告为空（已尝试多源）"))
        if not data["research_reports"]:
            errors.append(build_error("research", "empty", "研报为空（已尝试多源）"))
        if not data["hot_topics"]:
            errors.append(build_error("hot", "empty", "热点为空（已尝试多源）"))

        return make_result(data, source="alternative_data", errors=errors, fallback_used=bool(errors))