# -*- coding: utf-8 -*-
"""
risk_manager.py
===============
五维超脑·首席风控官 (Commercial Pro V8.0 - 全域排雷版)

【核心职能】
1. **硬熔断**: 过滤 ST/微盘/亏损/僵尸股。
2. **新闻排雷**: 扫描官方新闻，拦截“立案”、“减持”、“违规”等黑天鹅。
3. **软审计**: 驳回 AI 的非理性亢奋。
4. **仓位管理**: 基于风险度计算建议头寸。
"""

import re
import pandas as pd
import numpy as np

class RiskManager:
    def __init__(self):
        print("🛡️ [风控官] V8.0 已就位 (新闻排雷+硬风控)...")

    # ------------------------------------------------------------------
    # 1. 硬熔断机制 (基础门槛)
    # ------------------------------------------------------------------
    def check_hard_rules(self, data_pack: dict) -> tuple[bool, str]:
        """
        检查硬性指标。返回 (Passed: bool, Reason: str)
        """
        code = data_pack.get("code", "")
        spot = data_pack.get("market_data", {})
        ident = data_pack.get("identity", {})
        
        name = ident.get("name", spot.get("name", ""))
        price = spot.get("close", 0)
        mcap = spot.get("market_cap", 0) # 亿
        pe = spot.get("pe", 0)
        turnover = spot.get("turnover", 0)
        
        # 规则 A: 拒绝 ST / *ST / 退市
        if "ST" in name or "退" in name:
            return False, f"硬拦截: 退市风险 ({name})"

        # 规则 B: 拒绝微盘股 (市值 < 20亿)
        if mcap > 0 and mcap < 20:
            return False, f"硬拦截: 市值过小 ({mcap}亿)，流动性枯竭风险"

        # 规则 C: 拒绝严重亏损 (PE < 0 且非科创板)
        if pe < 0 and not code.startswith("688"):
            return False, "硬拦截: 业绩亏损"

        # 规则 D: 拒绝僵尸股 (无人交易)
        if turnover > 0 and turnover < 0.5:
            return False, f"硬拦截: 僵尸股 (换手率 {turnover}%)"

        # 规则 E: 股价过低 (面值退市)
        if price > 0 and price < 2.0:
            return False, f"硬拦截: 股价过低 ({price}元)"

        return True, "通过"

    # ------------------------------------------------------------------
    # 2. 新闻排雷 (新增核心)
    # ------------------------------------------------------------------
    def check_news_risks(self, data_pack: dict) -> tuple[bool, str]:
        """
        扫描企业新闻，拦截黑天鹅
        """
        news_list = data_pack.get("corporate_news", [])
        if not news_list:
            return True, "无新闻"
            
        # 致命风险词库
        FATAL_KEYWORDS = [
            "立案", "调查", "违规", "警示函", "被查", "留置", 
            "减持", "清仓", "解禁", "亏损扩大", "暴雷", "无法表示意见"
        ]
        
        for n in news_list:
            title = n.get("title", "")
            for kw in FATAL_KEYWORDS:
                if kw in title:
                    return False, f"新闻排雷: 发现高危词 '{kw}' -> {title}"
        
        return True, "新闻安全"

    # ------------------------------------------------------------------
    # 3. 软审计机制 (AI 逻辑查验)
    # ------------------------------------------------------------------
    def check_ai_audit(self, ai_decision: dict) -> tuple[bool, str]:
        """
        审查 AI 报告
        """
        risk_text = ai_decision.get("risk_warning", "")
        
        # 即使硬指标过了，如果 AI 自己都说有大雷，那必须信 AI
        if "极大风险" in risk_text or "建议卖出" in risk_text:
            return False, "软拦截: AI 提示重大风险"
            
        return True, "通过"

    # ------------------------------------------------------------------
    # 4. 仓位管理
    # ------------------------------------------------------------------
    def calculate_position(self, ai_score: float, risk_factor: float = 1.0, total_cash: float = 100000) -> float:
        """
        计算建议买入金额
        """
        if ai_score < 0.6: return 0.0
        
        # 基础比例
        ratio = (ai_score - 0.5) * 1.5 # 0.6->0.15, 0.8->0.45
        
        # 风险调整
        final_ratio = ratio * risk_factor
        
        # 单票上限 30%
        amt = min(final_ratio * total_cash, total_cash * 0.3)
        
        return round(amt, -2) # 取整到百位

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------
    def assess_risk(self, data_pack: dict, ai_decision: dict) -> dict:
        """
        综合评估
        """
        # 1. 硬风控
        passed, reason = self.check_hard_rules(data_pack)
        if not passed:
            return {"approved": False, "veto_reason": reason, "position": 0}
        
        # 2. 新闻排雷 (New!)
        passed, reason = self.check_news_risks(data_pack)
        if not passed:
            return {"approved": False, "veto_reason": reason, "position": 0}
            
        # 3. 软风控
        passed, reason = self.check_ai_audit(ai_decision)
        if not passed:
            return {"approved": False, "veto_reason": reason, "position": 0}
            
        # 4. 计算仓位
        score = ai_decision.get("ai_score", 0)
        pos = self.calculate_position(score)
        
        return {
            "approved": True, 
            "veto_reason": "风险可控", 
            "position": pos
        }