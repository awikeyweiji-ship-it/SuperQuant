# -*- coding: utf-8 -*-
"""
backtest_runner.py
==================
五维超脑·时光机 (Backtest System)

from config_manager import get_config

【核心功能】
这是一个“时间旅行”模拟器。它继承了 DataEngine，但重写了所有数据获取方法，
使其返回指定历史时间点的数据，从而欺骗 AI 董事会，进行真实的历史回测。

【回测机制】
1. 频率：周频 (Weekly) - 每周五收盘后决策，下周一开盘执行。
2. 资金管理：全仓买卖 (简化模型，测试 AI 的择时能力)。
3. 成本：已扣除千分之一的手续费。
"""

import time
import pandas as pd
import numpy as np
import datetime
from typing import Dict, Any

# 引入核心组件
from data_engine import DataEngine, normalize_code
import ai_advisor

# 尝试关闭 SettingWithCopyWarning
pd.options.mode.chained_assignment = None 

class HistoricalDataEngine(DataEngine):
    """
    【时光机引擎】
    继承自 DataEngine，但拦截所有数据请求，只返回 simulation_date 之前的数据。
    """
    def __init__(self, code: str):
        super().__init__()
        self.code = code
        self.simulation_date = None # 当前模拟日期 (datetime对象)
        
        print(f"⏳ 正在预加载 {code} 的全量历史数据，请稍候...")
        
        # 1. 预加载所有历史 K 线 (一次性拉取，避免回测时反复请求)
        self.full_kline = super().get_kline(code, freq="D", limit=5000)
        self.full_kline['date'] = pd.to_datetime(self.full_kline['date'])
        
        # 2. 预加载所有财务摘要
        self.full_financials = pd.DataFrame()
        try:
            import akshare as ak
            df = ak.stock_financial_abstract(symbol=code)
            if "截止日期" in df.columns:
                df["截止日期"] = pd.to_datetime(df["截止日期"])
                self.full_financials = df.sort_values("截止日期")
        except:
            print("⚠️ 财务数据预加载失败，将使用空数据回测")

    def travel_to(self, date_str: str):
        """设定当前模拟时间"""
        self.simulation_date = pd.to_datetime(date_str)

    # --- 覆写核心方法 ---

    def get_kline(self, code: str, freq: str = "D", limit: int = 250) -> pd.DataFrame:
        """只返回模拟日期之前的 K 线"""
        if self.full_kline.empty: return pd.DataFrame()
        
        # 切片：只取 date <= simulation_date
        mask = self.full_kline['date'] <= self.simulation_date
        sliced = self.full_kline.loc[mask].copy()
        
        return sliced.tail(limit)

    def get_spot_row(self, code: str) -> Dict[str, Any]:
        """返回模拟当天的收盘价作为'现价'"""
        df = self.get_kline(code, limit=1)
        if df.empty:
            return {"close": 0, "pct": 0, "pe": 0, "market_cap": 0}
        
        row = df.iloc[-1]
        return {
            "close": row['close'],
            "pct": 0.0, # 历史回测中难以精确计算当日涨幅，暂忽略
            "pe": 20.0, # 简化：PE 难以获得历史动态值，暂固定或需额外数据源
            "market_cap": 0 # 暂忽略
        }

    def get_financial_features(self, code: str) -> Dict[str, Any]:
        """返回模拟日期时已经披露的最新财报"""
        if self.full_financials.empty: return {}
        
        # 假设财报披露有滞后，这里简化逻辑：取 截止日期 < 模拟日期 的最新一条
        # 严谨回测应该用 '公告日期'，但 abstract 接口只有截止日期
        mask = self.full_financials["截止日期"] < self.simulation_date
        valid_history = self.full_financials.loc[mask]
        
        if valid_history.empty: return {}
        
        last = valid_history.iloc[-1]
        return {
            "roe": self._safe_val(last, "净资产收益率"),
            "profit_yoy": self._safe_val(last, "净利润同比增长率"),
            "rev_yoy": self._safe_val(last, "营业收入同比增长率")
        }

    def get_macro_context(self) -> Dict[str, Any]:
        """
        模拟宏观数据 (难点)
        这里使用简易逻辑：根据大盘(上证指数)的历史均线来模拟'市场情绪'
        """
        # 在真实商用回测中，这里需要加载历史国债和汇率数据表
        # 这里为了演示，固定返回中性数据
        return {
            "cn_10y_bond": 2.5,
            "market_sentiment": "中性(回测模拟)", 
            "sh_index_change": 0.0
        }
    
    def get_rag_report(self, code: str, limit: int = 5) -> Dict[str, Any]:
        """回测中很难获取历史舆情，暂时屏蔽，避免未来函数"""
        return {"items": [], "sentiment_score": 0}

    def _safe_val(self, row, key):
        try:
            val = str(row.get(key, ""))
            return float(val.replace("万", "").replace("亿", "").replace("%", ""))
        except:
            return 0.0

# ==========================================
# 回测执行器
# ==========================================

class BacktestRunner:
    def __init__(self, code: str, start_date: str, end_date: str, initial_cash: float = 100000.0, api_key: str = ""):
        self.code = normalize_code(code)
        self.start_date = pd.to_datetime(start_date)
        self.end_date = pd.to_datetime(end_date)
        self.cash = initial_cash
        self.holdings = 0
        self.api_key = api_key
        
        # 初始化时光机数据引擎
        self.engine = HistoricalDataEngine(self.code)
        
        # 交易记录
        self.history = []

    def run(self):
        """执行周频回测"""
        print(f"\n🚀 开始回测 {self.code} | 区间: {self.start_date.date()} -> {self.end_date.date()}")
        print("-" * 60)
        
        # 生成每周五的日期序列
        dates = pd.date_range(start=self.start_date, end=self.end_date, freq='W-FRI')
        
        for curr_date in dates:
            date_str = curr_date.strftime("%Y-%m-%d")
            
            # 1. 时光倒流
            self.engine.travel_to(date_str)
            
            # 2. 获取数据 (注意：K线只取到 curr_date)
            # 获取当周收盘价
            kline = self.engine.get_kline(self.code, limit=1)
            if kline.empty: continue
            current_price = kline.iloc[-1]['close']
            
            # 3. 准备 AI 燃料
            data_pack = self.engine.get_holistic_data(self.code)
            
            # 4. 呼叫董事会 (Call AI)
            print(f"📅 [{date_str}] 正在召开董事会...", end="", flush=True)
            
            try:
                # 传入 deep_mode=False 以节省 Token 和时间 (reasoner 比较慢)
                # 实际商用建议用 reasoner
                strategy = ai_advisor.get_ai_strategy(
                    data_pack, 
                    api_key=self.api_key, 
                    model="deepseek-chat" # 回测用V3跑得快，实盘用R1
                )
                
                decision = strategy.get("decision", "观望")
                score = strategy.get("ai_score", 0.5)
                print(f" 🤖 评分:{score:.2f} | 决策:{decision}")
                
                # 5. 执行交易 (简易逻辑)
                self._execute_trade(date_str, decision, score, current_price)
                
            except Exception as e:
                print(f" ❌ AI 掉线: {e}")
                time.sleep(1) # 防止 API 速率限制

            # 6. 记录资产
            total_val = self.cash + self.holdings * current_price
            self.history.append({
                "date": date_str,
                "price": current_price,
                "cash": self.cash,
                "holdings": self.holdings,
                "total": total_val,
                "decision": decision
            })

        self._print_report()

    def _execute_trade(self, date, decision, score, price):
        """简单的全仓买卖逻辑"""
        # 买入逻辑：评分高且决策为买入
        if "买入" in decision and score > 0.7:
            if self.cash > 0:
                # 全仓买入
                can_buy = int(self.cash / (price * 1.001)) # 留千一手续费
                if can_buy > 0:
                    cost = can_buy * price * 1.001
                    self.cash -= cost
                    self.holdings += can_buy
                    print(f"   >>> 🟢 买入 {can_buy} 股 @ {price:.2f}")

        # 卖出逻辑：评分低或决策为卖出/清仓
        elif "卖出" in decision or "清仓" in decision or "减仓" in decision or score < 0.4:
            if self.holdings > 0:
                # 全仓卖出
                revenue = self.holdings * price * 0.999 # 扣千一手续费
                self.cash += revenue
                print(f"   >>> 🔴 卖出 {self.holdings} 股 @ {price:.2f} (盈利: {revenue - (self.holdings*price):.2f})")
                self.holdings = 0

    def _print_report(self):
        if not self.history: return
        
        df = pd.DataFrame(self.history)
        initial = df.iloc[0]['total']
        final = df.iloc[-1]['total']
        ret = (final - initial) / initial * 100
        
        # 计算基准收益 (买入持有)
        first_price = df.iloc[0]['price']
        last_price = df.iloc[-1]['price']
        bench_ret = (last_price - first_price) / first_price * 100
        
        print("\n" + "="*40)
        print("📊 回测总结报告")
        print("="*40)
        print(f"初始资金: {initial:.2f}")
        print(f"最终资金: {final:.2f}")
        print(f"策略收益: {ret:.2f}%")
        print(f"基准收益: {bench_ret:.2f}% (买入持有)")
        print(f"跑赢基准: {ret - bench_ret:.2f}%")
        print("="*40)

# ==========================================
# 快速入口
# ==========================================
if __name__ == "__main__":
    import os
    
    # 【已修改】直接设置 API Key
    cfg = get_config()
    key = (cfg.deepseek_api_key or "").strip()
    if not key:
        print("❌ 请先设置 API Key 才能运行回测")
    else:
        # 示例：回测 贵州茅台 2023年下半年
        runner = BacktestRunner(
            code="600519", 
            start_date="2023-06-01", 
            end_date="2023-12-31", 
            api_key=key
        )
        runner.run()