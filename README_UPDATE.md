# 五维超脑 更新包 v1

## 你得到的变化
1) 不再在代码里硬编码密钥：统一由 `.w5brain_config.json` / 环境变量读取
2) Streamlit 侧边栏新增：保存配置 + 测试 DeepSeek/Tavily 连通
3) 行情快照获取加固：AkShare -> 东财 push2 -> 历史缓存兜底（UI 不再空白）
4) 侧边栏新增：数据源健康自检（Spot 来源/是否陈旧）
5) DeepSearch 离线时不再“空白”，会给出提示
6) 机会雷达升级：新增 `opportunity_radar.py`，把政策/情绪/资金/估值/需求/宏观 七维因子编排成可比分数+买入建议表格（缺数据时自动降级为中性）。

## 如何使用（替换）
- 解压覆盖到你的项目目录（建议先备份原目录）
- 运行：
- Web：`streamlit run app.py`
- 定时指挥塔：`python scheduler_service.py`

### 机会雷达（新）
- 直接引用：
  ```python
  from opportunity_radar import OpportunityRadar
  radar = OpportunityRadar()
  df = radar.build_radar_table(["000001", "600519"])  # 输出多维评分 + 建议
  ```
  可传入 MarketScanner 的 `scan` 结果或 DataEngine 快照，自动对齐 sector/资金/舆情因子。
  表字段示例：`policy_score/sentiment_score/capital_score/valuation_score/demand_score/growth_score/momentum_score/macro_score/radar_score/recommendation/data_gaps/evidence`，其中 `data_gaps` 提示缺失因子，`evidence` 汇总政策/资金/估值/宏观等依据。

## 配置方式
### 方式1：在 Web 页面保存（推荐）
- 侧边栏 -> “神经连接(API Keys)” -> 填 Key -> 点击“保存配置”
- 会生成/更新：`.w5brain_config.json`（与代码同目录）

### 方式2：环境变量
- `DEEPSEEK_API_KEY=...`
- `TAVILY_API_KEY=...`

（可选通知）
- `W5_TARGET_EMAIL=...`
- `W5_TARGET_PHONE=...`
- SMTP: `W5_SMTP_SERVER` / `W5_SMTP_PORT` / `W5_SENDER_EMAIL` / `W5_SENDER_PASS`
