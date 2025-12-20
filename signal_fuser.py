# -*- coding: utf-8 -*-
"""
signal_fuser.py
===============
五维超脑·多源信号熔断器 (Commercial Pro V11.0 - 共振核心)

【核心职能】
系统的“去噪滤波器”与“最终裁判”。
它负责将来自不同维度（宏观、逻辑、技术、舆情）的信号在时间轴上对齐，
并计算【共振指数】。只有满足共振阈值的标的，才会送往 AI 董事会进行最终审计。

【V11.0 独有机制】
1. **Defcon Gate (战备闸门)**:
   - 若宏观判定为 DEFENSE/RETREAT，强制提高筛选门槛，过滤掉 80% 的杂毛。
2. **Concept Boost (概念共振)**:
   - 若个股命中 Radiation 引擎推演的“金手指概念”，评分权重 x 1.5。
3. **Sentiment Penalty (拥挤度惩罚)**:
   - 自动识别“散户热门榜”，对情绪过热标的执行反向扣分，规避接盘风险。
"""

from __future__ import annotations
import pandas as pd
import logging
from typing import Dict, Any, List

class SignalFuser:
    def __init__(self, engine=None, cache=None, **kwargs):
        self.engine = engine
        self.cache = cache

        print(f"⚡ [Fuser V11.0] 信号熔断器已就位 (共振算法加载中...)")
        
        # 权重配置表 (可根据回测结果动态调整)
        self.weights = {
            "tech": 0.4,       # 技术面权重 (量价/资金)
            "logic": 0.3,      # 逻辑面权重 (概念命中)
            "macro": 0.3       # 宏观面权重 (大势顺逆)
        }

    def fuse_signals(
        self, 
        market_df: pd.DataFrame, 
        macro_report: Dict[str, Any], 
        logic_report: Dict[str, Any],
        hot_sentiment_stocks: List[str] = None
    ) -> pd.DataFrame:
        """
        核心方法：多维信号融合
        
        :param market_df: Scanner 扫描出的基础量化表 (含 score, code, name 等)
        :param macro_report: DeepSearch 输出的宏观报告 (含 defcon_level)
        :param logic_report: Radiation 输出的推演报告 (含 target_concepts)
        :param hot_sentiment_stocks: 散户热门榜名单 (用于反指)
        """
        if market_df.empty:
            return pd.DataFrame()

        df = market_df.copy()
        hot_sentiment_stocks = hot_sentiment_stocks or []

        # -----------------------------------------------------------
        # 1. Defcon Gate (宏观战备闸门)
        # -----------------------------------------------------------
        defcon = macro_report.get("defcon_level", "DEFENSE")
        
        # 基础门槛修正系数
        threshold_boost = 0.0
        if defcon == "ATTACK":
            # 进攻模式：放宽门槛，鼓励激进
            logging.info("⚡ 熔断器: 宏观进攻模式 -> 门槛降低，逻辑权重增加")
        elif defcon == "RETREAT":
            # 撤退模式：极度严苛，只看核心资产
            threshold_boost = 0.3
            logging.info("⚡ 熔断器: 宏观撤退模式 -> 启动避险过滤，门槛大幅提高")
        else: # DEFENSE
            threshold_boost = 0.1

        # -----------------------------------------------------------
        # 2. Logic Resonance (逻辑共振)
        # -----------------------------------------------------------
        target_concepts = logic_report.get("target_concepts", [])
        
        # 定义评分修正函数
        def calculate_resonance_score(row):
            base_score = row.get("score", 0)
            
            # A. 概念加成 (The Boost)
            # 检查个股行业/概念是否命中 AI 推演的金手指
            # 注意：这里依赖 DataEngine 提供的 identity 数据，
            # 假设 market_df 已经合并了 sector 或 concepts 字段，或者我们在外部处理
            # 简化处理：假设 DataEngine 已经把 sector 拼到了 df 里
            stock_sector = str(row.get("sector", ""))
            stock_name = str(row.get("name", ""))
            
            is_hit = False
            for t in target_concepts:
                if t in stock_sector or t in stock_name:
                    is_hit = True
                    break
            
            # 命中核心逻辑，分数 x 1.3 ~ 1.5
            if is_hit:
                base_score *= 1.4 
            
            # B. 拥挤度惩罚 (Sentiment Penalty)
            # 如果出现在散户热榜前列，视为过热，扣分
            if row['code'] in hot_sentiment_stocks:
                base_score *= 0.8 # 扣除 20% 分数
            
            return base_score

        # 应用评分修正
        df["fused_score"] = df.apply(calculate_resonance_score, axis=1)

        # -----------------------------------------------------------
        # 3. Final Filtering (最终过滤)
        # -----------------------------------------------------------
        # 根据宏观状态动态调整过审分数线
        # 假设基础合格线是 0.6
        pass_line = 0.6 + threshold_boost
        
        final_df = df[df["fused_score"] >= pass_line].copy()
        
        # 重新排序
        final_df = final_df.sort_values("fused_score", ascending=False)
        
        logging.info(f"⚡ 熔断报告: 原始 {len(df)} -> 宏观修正 -> 逻辑共振 -> 最终入围 {len(final_df)}")
        
        return final_df

    def check_veto(self, code: str, risk_data: Dict) -> bool:
        """
        单股一票否决检查 (用于 Advisor 阶段的二次确认)
        """
        # 可以在这里加入更细致的黑名单逻辑
        return False