# SuperQuant 仓库审计（Stage 0）

## 1. 仓库地图（按职能）
- **运行入口**：
  - `app.py`：Streamlit 主 UI（天网机会雷达、单股深度博弈、模拟仓、回测）。
  - `run.py`：便捷启动入口，封装 `streamlit run app.py`。
  - `scheduler_service.py`：定时任务塔，调用 `DataEngine.get_holistic_data` 做巡检/推送。
- **数据层**：
  - `data_engine.py`：行情、身份、K线、财务、资金、全息打包；封装 AkShare/东财/Tencent 兜底。
  - `fundamental_engine.py`：F10/财报因子抽取与标准化（quality/growth/ops）。
  - `capital_engine.py`：个股资金流与北向净流；AkShare 多接口兜底。
  - `alternative_data.py`：舆情（股吧）、宏观指标、新闻抓取与情绪打分。
  - `universe_cache.py`：内存/磁盘缓存，支撑行情快照与身份缓存。
- **策略/信号层**：
  - `signal_fuser.py`、`slow_factor_engine.py`、`policy_engine.py`、`radiation_engine.py`、`opportunity_radar.py` 等：融合策略、慢变量、政策量化、宏观辐射、机会雷达评分。
- **AI/搜索层**：
  - `deep_search_agent.py`：Tavily + PolicyEngine 的宏观/政策证据抓取，面向 Radar/SlowFactor。
  - `ai_advisor.py`、`execution_planner.py`、`entry_engine.py` 等：AI 决策与下单建议。
- **前端 UI**：
  - `app.py`（Streamlit 布局、控件、交互逻辑）。
- **配置**：
  - `config_manager.py`（API Key 读写与测试）、`.w5brain_config.json`（运行时生成）。
- **测试**：
  - `tests/test_func.py`（基础函数回归）；新增 `scripts/smoke_single_stock.py` 作为可执行冒烟脚本。

## 2. 入口与调用链
- **Streamlit 主链**：`app.py` → 初始化 `UniverseCache` → `DataEngine` → `MarketScanner/SignalFuser/SlowFactorEngine` → UI 面板（雷达、单股、模拟仓、回测）。
- **单股全息链路**（单股实验室/深度博弈）：`app.py` 中 `_safe_holistic` → `DataEngine.get_holistic_data` → 
  - 行情：`get_spot_row`（AkShare → 东财 push2 → 腾讯兜底 → 历史缓存）。
  - 身份：`get_stock_identity`（AkShare 行业/概念，失败回退缓存）。
  - K线：`get_kline`（AkShare 多周期）。
  - 财务：`get_financial_features`（AkShare 财务分析指标，失败默认全 0）。
  - 资金：`get_money_flow`（spot 主力净流入 + `CapitalEngine` 细项）。
  - 舆情/宏观新闻：`AlternativeDataEngine.get_alternative_report`（股吧爬取 + 宏观指标 + 新闻）。
- **全市场雷达链路**：`app.py` Smart Radar → `MarketScanner`（内部基于 `DataEngine` 行情/身份/slow_factor/radar）→ `opportunity_radar.py` 组合多因子。
- **定时任务链路**：`scheduler_service.py` → `DataEngine.get_holistic_data` → 将全息结果推送/落盘。

## 3. 功能链路与空数据根因
- **单股实验室/全息数据**：依赖 `DataEngine.get_holistic_data`。若 AkShare 不可用或接口变更，`get_spot_row/get_financial_features/get_kline` 会返回空 DataFrame/全 0，原因在于 AkShare 缺失或请求异常被吞掉；此版本已加 logger 提示。
- **F10/财报**：`fundamental_engine.py` & `data_engine.get_financial_features`。空值根因：AkShare 未安装/限流，或列名不匹配；当前返回默认 0，需后续加字段映射与兜底源。
- **资金**：`capital_engine.py` 逐个尝试 AkShare 接口；若全失败则返回 `{}`，原因可能为接口变更或网络失败。
- **热点要事**：`DataEngine.get_market_hot_spots` 调用 AkShare 榜单；AkShare 缺失/限流时仅提示“Akshare 未安装”，无替代源。
- **研报/公告**：未有专门模块，现仅 `AlternativeDataEngine.fetch_smart_news` 拉取东财新闻；若接口变更/HTTP 403 则返回空列表。
- **股吧舆情**：`AlternativeDataEngine.fetch_guba_sentiment` 爬取东财股吧；若超时或解析失败返回 score=0/hot_words 空，原因为网络受限或 HTML 结构变更。

## 4. 风险与质量观测
- **异常吞掉/空返回**：多处 `except: pass`（资金、财报、热点、舆情），导致 UI 静默显示空值；本次为数据链路加统一 logger 但仍需后续改为结构化错误。
- **超时/重试**：行情/热点使用 `_retry_call` 简单重试，无超时配置暴露；外部 HTTP 无全局超时/重试策略。
- **缓存策略**：行情快照使用 `UniverseCache`，但财务/资金/舆情缓存散落，TTL 不统一；无跨进程缓存策略。
- **并行与阻塞**：Streamlit 同步调用外部 HTTP/AkShare，网络慢时会阻塞 UI。
- **结构化返回**：部分接口直接返回 `{}` 或全 0，缺少字段级来源/时间戳，难以追踪数据可信度。

## 5. 质量闸门（建议加入）
- 日志：已新增 `logging_utils.get_data_logger` 并接入行情/财务/资金链路；后续需在 UI/调度侧汇总日志。
- 超时与重试：为外部 HTTP（股吧、新闻、政策搜索）统一 `timeout` 和指数退避重试；AkShare 函数应包裹超时保护。
- Fallback 多源：热点/研报/公告/资金需补二级源（如东财 API、腾讯、雪球爬虫），并在返回结构中标注 `source` 和 `fallback_used`。
- 缓存：统一 TTL 策略（行情秒级、财务天级、舆情小时级），并在结构中附带 `cache_age`。
- 可测试性：为各数据模块补最小单测（模拟空返回、异常），以及端到端 smoke（本次新增）作为发布闸门。

## 6. 验收清单（可执行命令）
- 语法/依赖快检：`python -m compileall .`
- 单股数据链路冒烟：`python scripts/smoke_single_stock.py 600519`
- （如需指定标的）`python scripts/smoke_single_stock.py 000001`
