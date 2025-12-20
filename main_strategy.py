# -*- coding: utf-8 -*-
# 文件名: main_strategy.py
# 作用: Backtrader 主程序（示例）
# ✅ 修复：backtrader / akshare 缺失时给出提示，不影响 Streamlit 运行

import datetime
import pandas as pd

try:
    import backtrader as bt
except Exception as e:
    bt = None
    _bt_err = e

try:
    import akshare as ak
except Exception as e:
    ak = None
    _ak_err = e

import ai_advisor


if bt is None or ak is None:
    print("⚠️ main_strategy.py 仅示例用途：缺少依赖无法运行。")
    if bt is None:
        print(f" - backtrader 缺失：{_bt_err}")
    if ak is None:
        print(f" - akshare 缺失：{_ak_err}")
else:

    class AIDrivenStrategy(bt.Strategy):
        params = (('period', 20),)

        def __init__(self):
            self.dataclose = self.datas[0].close
            self.order = None
            self.ma20 = bt.indicators.SimpleMovingAverage(self.datas[0], period=self.params.period)

        def log(self, txt, dt=None):
            dt = dt or self.datas[0].datetime.date(0)
            print(f"{dt.isoformat()}, {txt}")

        def next(self):
            if self.order:
                return

            if not self.position:
                if self.dataclose[0] > self.ma20[0] and self.dataclose[-1] <= self.ma20[-1]:
                    self.log(f"技术面出现买点 (价格 {self.dataclose[0]:.2f} > MA20)，正在询问 AI 军师...")

                    decision = ai_advisor.get_ai_advice(
                        symbol="600519",
                        data_pack={"close": float(self.dataclose[0]), "trend_status": "回测模式"},
                        news_text="这里应接入真实新闻/RAG（示例文本）",
                        api_key="",  # 可填 DEEPSEEK_API_KEY
                    )

                    self.log(f"AI 回复: {decision.get('reason_summary', '')} (打分: {decision.get('score', 0.0)})")

                    if decision.get('score', 0.0) > 0.6 and not decision.get("veto", False):
                        self.order = self.buy()
            else:
                if self.dataclose[0] < self.ma20[0]:
                    self.log(f"跌破 MA20，卖出 (价格 {self.dataclose[0]:.2f})")
                    self.order = self.sell()

        def notify_order(self, order):
            if order.status in [order.Submitted, order.Accepted]:
                return

            if order.status in [order.Completed]:
                if order.isbuy():
                    self.log(f"买入执行: {order.executed.price:.2f}")
                else:
                    self.log(f"卖出执行: {order.executed.price:.2f}")

            elif order.status in [order.Canceled, order.Margin, order.Rejected]:
                self.log("订单失败/取消")

            self.order = None


    if __name__ == "__main__":
        symbol = "600519"
        cerebro = bt.Cerebro()

        try:
            end = datetime.datetime.now().strftime("%Y%m%d")
            start = (datetime.datetime.now() - datetime.timedelta(days=500)).strftime("%Y%m%d")
            df = ak.stock_zh_a_hist(symbol=symbol, period="daily", start_date=start, end_date=end, adjust="qfq")
            df.rename(columns={'日期': 'datetime', '开盘': 'open', '最高': 'high', '最低': 'low', '收盘': 'close', '成交量': 'volume'}, inplace=True)
            df['datetime'] = pd.to_datetime(df['datetime'])
            df.set_index('datetime', inplace=True)

            data = bt.feeds.PandasData(dataname=df)
            cerebro.adddata(data)

        except Exception as e:
            print(f"数据获取失败: {e}")
            raise SystemExit(1)

        cerebro.addstrategy(AIDrivenStrategy)
        cerebro.broker.setcash(100000.0)
        print('初始资金: %.2f' % cerebro.broker.getvalue())

        cerebro.run()
        print('最终资金: %.2f' % cerebro.broker.getvalue())
