# Doctor Report

Generated: 2025-12-22T00:00:00Z

## Environment
- Python: 3.11.12
- Platform: Linux

## Commands Executed (sandbox)
- `python -m compileall .` -> ✅ (compilation completed)
- `python scripts/smoke_single_stock.py 600519` -> ❌ (proxy blocks all upstreams; baostock/login unreachable)
- `python scripts/smoke_single_stock.py 000001` -> ❌ (proxy blocks all upstreams; baostock/login unreachable)

### Logs
- compileall produced bytecode for the repo without errors.
- Smoke runs failed because outbound requests to SSE/SZSE/Eastmoney/Tencent/Sina/CNINFO were blocked by the sandbox proxy (HTTP 403) and baostock cannot log in here, so quote/K线/公告/财务 payloads stayed empty. The smoke script enforces >=120 K线 rows, >=8 financial numeric fields, >=1 announcement, and a non-empty (derived) price.

## Status
Backbone now prioritizes BaoStock for K线和财务，交易所公告为首选并带东财兜底，同时增加了磁盘缓存以在实时失败时返回上次成功结果。UI 现已去除 TuShare token 门槛，现价会在行情缺失时用最新日线收盘价标注“非实时：最新收盘价”。需在联网的 Windows 环境下用 `pip install -r requirements.txt` 后重跑 smoke 以验证真实可用性。

## Self-check和后续改进
- **数据可用性**：当前沙箱被代理阻断，需在实际联网环境验证交易所公告、BaoStock K线/财务的可用性并确认缓存能回填失败场景。
- **韧性/缓存**：已增加磁盘缓存兜底，但缺少缓存 TTL/刷新策略与健康指标。应补充“最近成功时间”提示和强制刷新按钮，避免长时间使用陈旧数据。
- **财报丰富度**：BaoStock 提供基础指标（eps/roe/net_profit/revenue/ocf 等），可补充估值/分部披露来源（如 Eastmoney 财报概览）以提升字段覆盖度。
- **公告多源**：已接入上交所/深交所公开接口并以东财为兜底，建议增加简易 RSS/镜像源与去重逻辑，以减少单点故障。
- **测试/诊断**：新增 `scripts/smoke_env_check.py` 用于依赖与网络探测，但 CI 仍缺少离线 fixture。应补充录播样本或 mock 层，让流水线可验证非实时派生价与缓存回退逻辑。
- **产品化**：需在 UI 中提示数据是否来自缓存/是否非实时，并扩展策略评分（政策强度/需求空间/技术成熟度/估值等）形成可落地的买卖建议表格。
