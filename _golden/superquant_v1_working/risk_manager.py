# 文件名: risk_manager.py
# 作用: 负责硬风控（过滤垃圾）和软风控（老炮审计）

import pandas as pd
import numpy as np

class RiskManager:
    def __init__(self):
        print("🛡️ [风控官] 极速版已就位 (按需计算模式)")

    def fast_veto(self, data_pack):
        """[第一级] 毫秒级硬风控：只看基础面数据，不联网"""
        # 1. 回款红线：应收账款周转天数过大
        try:
            days_str = str(data_pack.get('turnover_days', '0'))
            # 提取数字
            import re
            nums = re.findall(r'\d+', days_str)
            if nums:
                days = int(nums[0])
                if days > 400: return False, f"财务雷：回款太慢({days}天)"
        except: pass

        # 2. 壳资源/小票亏损过滤
        try:
            pe = float(data_pack.get('pe', 0))
            mcap = float(data_pack.get('market_cap', 0))
            # 亏损且市值小于35亿
            if pe < 0 and mcap < 35: return False, "风险项：微型亏损股"
        except: pass
        
        return True, "通过"

    def check_ai_veto(self, ai_response):
        """[第二级] AI 软审计：检查老炮观点"""
        hustler_view = ai_response.get('role_insights', {}).get('hustler_street', '')
        red_flags = ["杀猪盘", "出货", "财务造假", "庞氏", "退市", "立案"]
        for flag in red_flags:
            if flag in hustler_view: return False, f"老炮警告：探测到{flag}信号"
        return True, "通过"

    def calculate_atr_positions(self, valid_stocks_dict, total_cash=200000):
        """[第三级] ATR 仓位管理 (仅演示逻辑，不影响运行)"""
        return {code: 0 for code in valid_stocks_dict}