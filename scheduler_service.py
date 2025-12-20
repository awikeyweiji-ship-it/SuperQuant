# -*- coding: utf-8 -*-
"""
scheduler_service.py
====================
五维超脑·自动指挥塔 (Commercial Pro V8.0 - 资本雷达全自动版)

【核心职能】
系统的“心脏”。利用 APScheduler 实现毫秒级任务调度，
将感官(Data)、大脑(AI)、四肢(Scanner)有机串联，实现无人值守的自动化交易闭环。

【升级日志 V8.0】
1. **新闻播报集成**: 自动在日报中高亮“资本运作”新闻（增持/回购/注资）。
2. **宏观自适应调度**: 配合 MarketScanner 自动切换扫描模式。
3. **推送格式优化**: 增强 Markdown 可读性。
"""

import time
import logging
import pandas as pd
from config_manager import get_config
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

# 引入核心组件
from data_engine import DataEngine
from market_scanner import MarketScanner, ScanConfig
import ai_advisor
from notifier import notify_daily_report, send_markdown  # 确保 notifier.py 已配置

# ==========================================
# 配置区 (请务必修改为你的真实 Key)
# ==========================================
# 警告：自动运行时无法从 Streamlit 输入框获取 Key，必须在此硬编码或读取环境变量
cfg = get_config()
API_KEY = (cfg.deepseek_api_key or "").strip()
TARGET_EMAIL = (cfg.target_email or "").strip()
TARGET_PHONE = (cfg.target_phone or "").strip()

# 初始化日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [%(levelname)s] - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

class AutoTraderBrain:
    def __init__(self):
        logging.info("🧠 [五维超脑 V8.0] 自动驾驶系统初始化中...")
        self.engine = DataEngine()
        self.scanner = MarketScanner(self.engine)
        self.scheduler = BackgroundScheduler()
        self.is_running = False

    # ------------------------------------------------------------------
    # 任务 A: 盘前宏观哨兵 (09:15)
    # ------------------------------------------------------------------
    def job_morning_brief(self):
        logging.info("🌞 [早盘] 开始执行宏观环境与政策扫描...")
        try:
            # 1. 唤醒情报局，借用一只股票(如茅台)触发全息数据更新
            data_pack = self.engine.get_holistic_data("600519")
            
            macro = data_pack.get("macro_context", {})
            alt = data_pack.get("alternative_intelligence", {})
            
            # 2. 生成简报文本
            cpi = macro.get('cpi_yoy', '--')
            m2 = macro.get('m2_yoy', '--')
            bond = macro.get('cn_10y_bond', '--')
            sentiment = macro.get('market_sentiment', '数据获取中')
            
            report_text = f"""
**📅 日期:** {datetime.now().strftime('%Y-%m-%d')}
**🌍 宏观定调:** `{sentiment}`

**📊 核心指标:**
- CPI同比: {cpi}%
- M2增速: {m2}%
- 10年国债: {bond}%

**📢 市场噪音:**
> {alt.get('raw_guba_sample', '无')[:60]}...
            """
            
            # 3. 推送
            logging.info("✅ 早盘内参已生成，正在推送...")
            print(report_text) 
            send_markdown("🌞 五维超脑·早盘内参", report_text)
            
        except Exception as e:
            logging.error(f"❌ 早盘任务失败: {e}")

    # ------------------------------------------------------------------
    # 任务 B: 午盘机会雷达 (11:30)
    # ------------------------------------------------------------------
    def job_midday_alert(self):
        logging.info("🥪 [午盘] 执行资金异动扫描...")
        try:
            # 快速扫描策略：寻找“量比放大”且“资金流入”的活跃股
            config = ScanConfig(
                prefer_active=0.6,    # 高度关注活跃度
                prefer_momentum=0.3,  # 关注趋势
                prefer_value=0.1,     # 暂时忽略估值
                penalize_overheat=0.2, # 避免过度追高
                macro_adaptive=True   # 开启宏观自适应
            )
            
            # 扫描全A股
            df_scan, _ = self.scanner.scan_cached("all_a_shares", config, cache_ttl=60)
            
            if not df_scan.empty:
                top_picks = df_scan.head(5)
                msg = "**🚀 午盘异动雷达 (Top 5):**\n\n"
                for _, row in top_picks.iterrows():
                    # 尝试获取实时主力资金
                    money = self.engine.get_money_flow(row['code'])
                    inflow = money.get('main_net_inflow_today', 0)
                    inflow_str = f"{inflow/10000:.1f}亿" if abs(inflow)>10000 else f"{inflow}万"
                    
                    msg += f"- **{row['name']}** ({row['code']}): 量比 `{row['vol_ratio']}` | 主力流入 {inflow_str} | 评分 {row['score']}\n"
                
                logging.info(f"🚀 午盘发现 {len(df_scan)} 个潜在机会")
                send_markdown("🥪 五维超脑·午盘快讯", msg)
                
        except Exception as e:
            logging.error(f"❌ 午盘任务失败: {e}")

    # ------------------------------------------------------------------
    # 任务 C: 收盘深度复盘 (15:30) - 核心重头戏
    # ------------------------------------------------------------------
    def job_market_close_review(self):
        logging.info("🌙 [盘后] 开始执行全市场深度复盘与AI审计...")
        
        if not API_KEY:
            logging.warning("⚠️ 未配置有效 API Key，跳过 AI 审计步骤！")
            return

        try:
            # 1. 量化初筛 (使用宏观自适应)
            config = ScanConfig(macro_adaptive=True) 
            
            # 扫描核心资产池
            logging.info("🔍 正在扫描核心资产池...")
            df_scan, _ = self.scanner.scan_cached("core_assets_top100", config, cache_ttl=10)
            
            # 取前 3 名进行 AI 深度面试
            top_picks = df_scan.head(3)
            final_report_list = []
            
            for index, row in top_picks.iterrows():
                code = row['code']
                name = row['name']
                logging.info(f"🤖 AI 董事会正在审计: {name} ({code})...")
                
                # 获取全息数据 (含新闻)
                data_pack = self.engine.get_holistic_data(code)
                
                # 呼叫 AI 董事会 (Advisor V8.0)
                decision = ai_advisor.get_ai_strategy(
                    data_pack, 
                    api_key=API_KEY,
                    model="deepseek-chat"
                )
                
                # 提取资本运作新闻摘要
                news_tags = [n['tag'] for n in data_pack.get('corporate_news', []) if "资本" in n['tag']]
                capital_op = ",".join(news_tags) if news_tags else "无"
                
                # 整合结果
                row_dict = row.to_dict()
                row_dict['AI综合分'] = decision.get('ai_score', 0)
                row_dict['决策'] = decision.get('decision', '未知')
                row_dict['资本利好'] = capital_op # 新增字段
                row_dict['总评逻辑'] = decision.get('reasoning_summary', ['暂无'])[0]
                row_dict['建议持仓'] = 20000 if decision.get('ai_score', 0) > 0.7 else 0
                
                final_report_list.append(row_dict)
                time.sleep(2) 
            
            # 3. 生成最终日报并推送
            if final_report_list:
                df_final = pd.DataFrame(final_report_list)
                logging.info("📧 正在发送收盘深度研报...")
                notify_daily_report(df_final, target_email=TARGET_EMAIL, target_phone=TARGET_PHONE)
                logging.info("✅ 复盘任务圆满完成！")
            else:
                logging.info("⚠️ 今日无符合条件的高分标的。")

        except Exception as e:
            logging.error(f"❌ 盘后任务失败: {e}")

    # ------------------------------------------------------------------
    # 启动入口
    # ------------------------------------------------------------------
    def start(self):
        # 添加定时任务
        # 1. 早盘 09:15
        self.scheduler.add_job(self.job_morning_brief, CronTrigger(day_of_week='mon-fri', hour=9, minute=15))
        
        # 2. 午盘 11:30
        self.scheduler.add_job(self.job_midday_alert, CronTrigger(day_of_week='mon-fri', hour=11, minute=30))
        
        # 3. 盘后 15:30
        self.scheduler.add_job(self.job_market_close_review, CronTrigger(day_of_week='mon-fri', hour=15, minute=30))
        
        self.scheduler.start()
        self.is_running = True
        
        print("\n" + "="*50)
        print("🚀 [五维超脑 V8.0] 全自动指挥塔已启动")
        print("⏰ 任务列表:")
        print("   - 09:15 早盘内参 (宏观+政策)")
        print("   - 11:30 午盘雷达 (资金异动)")
        print("   - 15:30 收盘复盘 (AI深度审计+资本雷达)")
        print("="*50 + "\n")
        
        try:
            while True:
                time.sleep(1)
        except (KeyboardInterrupt, SystemExit):
            self.stop()

    def stop(self):
        self.scheduler.shutdown()
        self.is_running = False
        logging.info("🛑 系统已安全停机")

if __name__ == "__main__":
    if not API_KEY:
        print("⚠️ 警告: 请先在代码中配置 API_KEY 才能使用 AI 审计功能！")
    bot = AutoTraderBrain()
    bot.start()