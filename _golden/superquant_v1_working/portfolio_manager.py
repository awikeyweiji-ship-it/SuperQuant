# -*- coding: utf-8 -*-
"""
portfolio_manager.py
--------------------
马科维茨/有效前沿示例（可选模块）

✅ 修复：pypfopt 未安装时不应导致整个项目 import 崩溃
"""

import pandas as pd


def optimize_portfolio(stock_data_dict, total_cash=100000):
    """
    输入: {'600519': df1, '300750': df2 ...} （df 至少包含 close 列）
    输出: 每只股票建议买入的金额（仅示例，非投资建议）
    """
    try:
        from pypfopt import EfficientFrontier
        from pypfopt import risk_models
        from pypfopt import expected_returns
    except Exception as e:
        print(f"❌ pypfopt 未安装，无法进行组合优化：{e}")
        return {}

    print("\n⚖️ 正在进行 [马科维茨] 投资组合数学优化...")

    df_prices = pd.DataFrame()
    for code, df in stock_data_dict.items():
        if df is None or df.empty or "close" not in df.columns:
            continue
        df_prices[code] = df["close"]

    df_prices.dropna(inplace=True)
    if df_prices.empty:
        print("❌ 数据不足，无法优化")
        return {}

    mu = expected_returns.mean_historical_return(df_prices)
    S = risk_models.sample_cov(df_prices)

    try:
        ef = EfficientFrontier(mu, S)
        ef.max_sharpe()
        cleaned_weights = ef.clean_weights()

        allocation = {}
        for code, weight in cleaned_weights.items():
            if weight and weight > 0:
                allocation[code] = round(total_cash * weight, 2)
        return allocation
    except Exception as e:
        print(f"优化失败（可能是数据太短或线性相关）: {e}")
        avg_money = total_cash / max(1, len(stock_data_dict))
        return {code: round(avg_money, 2) for code in stock_data_dict}
