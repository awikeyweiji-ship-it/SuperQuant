# 改造路线图（按阶段）

## Stage 1：观测与兜底（当前迭代）
- **目标**：保证关键链路有可观察性，避免空白返回；补充最小冒烟验证。
- **改动文件**：
  - `logging_utils.py`，`data_engine.py`，`fundamental_engine.py`，`capital_engine.py`：统一数据链路 logger；记录行情/财报/资金兜底来源和失败原因。
  - `scripts/smoke_single_stock.py`：单股端到端冒烟脚本（行情/财务/资金/舆情）。
  - `docs/REPO_AUDIT.md`，`docs/ROADMAP.md`：架构地图与可执行计划。
- **验收标准**：
  - `python -m compileall .` 通过。
  - `python scripts/smoke_single_stock.py 600519` 输出完整链路，若数据缺失需包含 `reason` 并 exit code=1；正常命中数据 exit code=0。

## Stage 2：数据可靠性与结构化返回
- **目标**：为每个数据源补充超时/重试/缓存与来源标注，避免静默空值。
- **改动文件**（示例）：
  - `data_engine.py`：为 AkShare/HTTP 请求显式 timeout、重试与指标埋点；返回结构增加 `source`、`fallback_used`、`cache_age`。
  - `alternative_data.py`：新闻/舆情接口增加多源兜底（如备用新闻源/雪球爬虫），并记录失败原因。
  - `capital_engine.py`、`fundamental_engine.py`：补字段映射表，避免列名变更导致全 0。
- **验收标准**：
  - 为上述函数新增最小单测（模拟空/异常）并通过 `pytest tests -q`。
  - `python scripts/smoke_single_stock.py 000001` 在网络可用时返回包含 `source`、`fallback_used` 字段。

## Stage 3：功能扩展与性能
- **目标**：补全热点/研报/公告链路，优化并发与缓存，提升 UI 体验。
- **改动文件**（示例）：
  - `data_engine.py` + 新增 `research_engine.py`：接入研报/公告（如东财研报、巨潮公告）并结构化输出，带缓存与错误标签。
  - `market_scanner.py` / `opportunity_radar.py`：引入宏观/政策/舆情因子权重配置，支持多线程/异步批量扫描。
  - `app.py`：UI 增加“空数据/降级”告警条与数据来源展示。
- **验收标准**：
  - 全量冒烟：`python scripts/smoke_single_stock.py 600519` 输出包含研报/公告摘要与来源。
  - 扫描性能：针对 50 只股票批量扫描的脚本耗时可接受（例如 `python market_scanner.py --codes sample.txt` < 2 分钟），并有日志可追踪。
