# Doctor Report

Generated: 2025-12-21T14:16:14.907667Z

## Environment
- Python: 3.11.12 (main, Oct 24 2025, 00:36:31) [GCC 13.3.0]
- Platform: Linux-6.12.13-x86_64-with-glibc2.39
- Network signals: proxy, Network is unreachable, Max retries, 503

## Commands Executed
- `/root/.pyenv/versions/3.11.12/bin/python -m compileall -q app.py data_engine.py logging_utils.py alternative_data.py data_sources scripts tools` -> exit 0
- `/root/.pyenv/versions/3.11.12/bin/python -c import app` -> exit 0
```
🕵️ [情报局 V9.1] 启动 (天网情报系统已修复)...
🚀 [DataEngine V12.1] 引擎就绪 (热点接口已修复)...
⚡ [Fuser V11.0] 信号熔断器已就位 (共振算法加载中...)
☢️ [Radiation V11.0] 辐射引擎已就位 (Model: DeepSeek-V3)
```
- `/root/.pyenv/versions/3.11.12/bin/python scripts/smoke_single_stock.py 600519.SH` -> exit 1
```
🕵️ [情报局 V9.1] 启动 (天网情报系统已修复)...
🚀 [DataEngine V12.1] 引擎就绪 (热点接口已修复)...
[
  {
    "code": "600519.SH",
    "failures": [
      "quote_filled_zero",
      "quote_errors_1",
      "quote_network_blocked",
      "financial_filled_zero",
```
- `/root/.pyenv/versions/3.11.12/bin/python scripts/smoke_news_bundle.py 600519.SH` -> exit 1
```
🕵️ [情报局 V9.1] 启动 (天网情报系统已修复)...
🚀 [DataEngine V12.1] 引擎就绪 (热点接口已修复)...
{
  "code": "600519.SH",
  "failures": [
    "announcements_empty",
    "reports_empty",
    "hot_events_empty",
    "quote_filled_zero",
    "quote_errors_1",
```
- `/root/.pyenv/versions/3.11.12/bin/python scripts/smoke_data_integrity.py 600519.SH` -> exit 1
```
🕵️ [情报局 V9.1] 启动 (天网情报系统已修复)...
🚀 [DataEngine V12.1] 引擎就绪 (热点接口已修复)...
[
  {
    "code": "600519.SH",
    "failures": [
      "invalid_report_period",
      "financial_missing_pe_ttm",
      "quote_filled_zero",
      "quote_errors_1",
```

## Import Sanity
- ✅ All target modules imported without exception

## File/Line References
- No file:line hints captured

## Smoke Metrics
| Command | Code | Module | Filled | Errors | Status |
|---|---|---|---|---|---|
| /root/.pyenv/versions/3.11.12/bin/python scripts/smoke_single_stock.py 600519.SH | 600519.SH | quote | 0 | 1 | FAIL |
| /root/.pyenv/versions/3.11.12/bin/python scripts/smoke_single_stock.py 600519.SH | 600519.SH | financial | 0 | 3 | FAIL |
| /root/.pyenv/versions/3.11.12/bin/python scripts/smoke_single_stock.py 600519.SH | 600519.SH | money_flow | 0 | 1 | FAIL |
| /root/.pyenv/versions/3.11.12/bin/python scripts/smoke_single_stock.py 600519.SH | 600519.SH | news_bundle | 0 | 4 | FAIL |
| /root/.pyenv/versions/3.11.12/bin/python scripts/smoke_single_stock.py 600519.SH | 600519.SH | failure | None | None | quote_filled_zero |
| /root/.pyenv/versions/3.11.12/bin/python scripts/smoke_single_stock.py 600519.SH | 600519.SH | failure | None | None | quote_errors_1 |
| /root/.pyenv/versions/3.11.12/bin/python scripts/smoke_single_stock.py 600519.SH | 600519.SH | failure | None | None | quote_network_blocked |
| /root/.pyenv/versions/3.11.12/bin/python scripts/smoke_single_stock.py 600519.SH | 600519.SH | failure | None | None | financial_filled_zero |
| /root/.pyenv/versions/3.11.12/bin/python scripts/smoke_single_stock.py 600519.SH | 600519.SH | failure | None | None | financial_errors_3 |
| /root/.pyenv/versions/3.11.12/bin/python scripts/smoke_single_stock.py 600519.SH | 600519.SH | failure | None | None | financial_network_blocked |
| /root/.pyenv/versions/3.11.12/bin/python scripts/smoke_single_stock.py 600519.SH | 600519.SH | failure | None | None | money_flow_filled_zero |
| /root/.pyenv/versions/3.11.12/bin/python scripts/smoke_single_stock.py 600519.SH | 600519.SH | failure | None | None | money_flow_errors_1 |
| /root/.pyenv/versions/3.11.12/bin/python scripts/smoke_single_stock.py 600519.SH | 600519.SH | failure | None | None | money_flow_network_blocked |
| /root/.pyenv/versions/3.11.12/bin/python scripts/smoke_single_stock.py 600519.SH | 600519.SH | failure | None | None | news_bundle_filled_zero |
| /root/.pyenv/versions/3.11.12/bin/python scripts/smoke_single_stock.py 600519.SH | 600519.SH | failure | None | None | news_bundle_errors_4 |
| /root/.pyenv/versions/3.11.12/bin/python scripts/smoke_single_stock.py 600519.SH | 600519.SH | failure | None | None | news_bundle_network_blocked |
| /root/.pyenv/versions/3.11.12/bin/python scripts/smoke_single_stock.py 600519.SH | 600519.SH | failure | None | None | news_announcements_empty |
| /root/.pyenv/versions/3.11.12/bin/python scripts/smoke_single_stock.py 600519.SH | 600519.SH | failure | None | None | news_reports_empty |
| /root/.pyenv/versions/3.11.12/bin/python scripts/smoke_single_stock.py 600519.SH | 600519.SH | failure | None | None | news_hot_events_empty |
| /root/.pyenv/versions/3.11.12/bin/python scripts/smoke_news_bundle.py 600519.SH | 600519.SH | quote | 0 | 0 | FAIL |
| /root/.pyenv/versions/3.11.12/bin/python scripts/smoke_news_bundle.py 600519.SH | 600519.SH | financial | 0 | 0 | FAIL |
| /root/.pyenv/versions/3.11.12/bin/python scripts/smoke_news_bundle.py 600519.SH | 600519.SH | money_flow | 0 | 0 | FAIL |
| /root/.pyenv/versions/3.11.12/bin/python scripts/smoke_news_bundle.py 600519.SH | 600519.SH | news_bundle | 0 | 0 | FAIL |
| /root/.pyenv/versions/3.11.12/bin/python scripts/smoke_news_bundle.py 600519.SH | 600519.SH | failure | None | None | announcements_empty |
| /root/.pyenv/versions/3.11.12/bin/python scripts/smoke_news_bundle.py 600519.SH | 600519.SH | failure | None | None | reports_empty |
| /root/.pyenv/versions/3.11.12/bin/python scripts/smoke_news_bundle.py 600519.SH | 600519.SH | failure | None | None | hot_events_empty |
| /root/.pyenv/versions/3.11.12/bin/python scripts/smoke_news_bundle.py 600519.SH | 600519.SH | failure | None | None | quote_filled_zero |
| /root/.pyenv/versions/3.11.12/bin/python scripts/smoke_news_bundle.py 600519.SH | 600519.SH | failure | None | None | quote_errors_1 |
| /root/.pyenv/versions/3.11.12/bin/python scripts/smoke_news_bundle.py 600519.SH | 600519.SH | failure | None | None | quote_network_blocked |
| /root/.pyenv/versions/3.11.12/bin/python scripts/smoke_news_bundle.py 600519.SH | 600519.SH | failure | None | None | financial_filled_zero |
| /root/.pyenv/versions/3.11.12/bin/python scripts/smoke_news_bundle.py 600519.SH | 600519.SH | failure | None | None | financial_errors_3 |
| /root/.pyenv/versions/3.11.12/bin/python scripts/smoke_news_bundle.py 600519.SH | 600519.SH | failure | None | None | financial_network_blocked |
| /root/.pyenv/versions/3.11.12/bin/python scripts/smoke_news_bundle.py 600519.SH | 600519.SH | failure | None | None | money_flow_filled_zero |
| /root/.pyenv/versions/3.11.12/bin/python scripts/smoke_news_bundle.py 600519.SH | 600519.SH | failure | None | None | money_flow_errors_1 |
| /root/.pyenv/versions/3.11.12/bin/python scripts/smoke_news_bundle.py 600519.SH | 600519.SH | failure | None | None | money_flow_network_blocked |
| /root/.pyenv/versions/3.11.12/bin/python scripts/smoke_news_bundle.py 600519.SH | 600519.SH | failure | None | None | news_bundle_filled_zero |
| /root/.pyenv/versions/3.11.12/bin/python scripts/smoke_news_bundle.py 600519.SH | 600519.SH | failure | None | None | news_bundle_errors_4 |
| /root/.pyenv/versions/3.11.12/bin/python scripts/smoke_news_bundle.py 600519.SH | 600519.SH | failure | None | None | news_bundle_network_blocked |
| /root/.pyenv/versions/3.11.12/bin/python scripts/smoke_news_bundle.py 600519.SH | 600519.SH | failure | None | None | news_bundle_network_blocked |
| /root/.pyenv/versions/3.11.12/bin/python scripts/smoke_data_integrity.py 600519.SH | 600519.SH | quote | 0 | 0 | FAIL |
| /root/.pyenv/versions/3.11.12/bin/python scripts/smoke_data_integrity.py 600519.SH | 600519.SH | financial | 0 | 0 | FAIL |
| /root/.pyenv/versions/3.11.12/bin/python scripts/smoke_data_integrity.py 600519.SH | 600519.SH | money_flow | 0 | 0 | FAIL |
| /root/.pyenv/versions/3.11.12/bin/python scripts/smoke_data_integrity.py 600519.SH | 600519.SH | news_bundle | 0 | 0 | FAIL |
| /root/.pyenv/versions/3.11.12/bin/python scripts/smoke_data_integrity.py 600519.SH | 600519.SH | failure | None | None | invalid_report_period |
| /root/.pyenv/versions/3.11.12/bin/python scripts/smoke_data_integrity.py 600519.SH | 600519.SH | failure | None | None | financial_missing_pe_ttm |
| /root/.pyenv/versions/3.11.12/bin/python scripts/smoke_data_integrity.py 600519.SH | 600519.SH | failure | None | None | quote_filled_zero |
| /root/.pyenv/versions/3.11.12/bin/python scripts/smoke_data_integrity.py 600519.SH | 600519.SH | failure | None | None | quote_errors_1 |
| /root/.pyenv/versions/3.11.12/bin/python scripts/smoke_data_integrity.py 600519.SH | 600519.SH | failure | None | None | quote_network_blocked |
| /root/.pyenv/versions/3.11.12/bin/python scripts/smoke_data_integrity.py 600519.SH | 600519.SH | failure | None | None | financial_filled_zero |
| /root/.pyenv/versions/3.11.12/bin/python scripts/smoke_data_integrity.py 600519.SH | 600519.SH | failure | None | None | financial_errors_3 |
| /root/.pyenv/versions/3.11.12/bin/python scripts/smoke_data_integrity.py 600519.SH | 600519.SH | failure | None | None | financial_network_blocked |
| /root/.pyenv/versions/3.11.12/bin/python scripts/smoke_data_integrity.py 600519.SH | 600519.SH | failure | None | None | money_flow_filled_zero |
| /root/.pyenv/versions/3.11.12/bin/python scripts/smoke_data_integrity.py 600519.SH | 600519.SH | failure | None | None | money_flow_errors_1 |
| /root/.pyenv/versions/3.11.12/bin/python scripts/smoke_data_integrity.py 600519.SH | 600519.SH | failure | None | None | money_flow_network_blocked |
| /root/.pyenv/versions/3.11.12/bin/python scripts/smoke_data_integrity.py 600519.SH | 600519.SH | failure | None | None | news_bundle_filled_zero |
| /root/.pyenv/versions/3.11.12/bin/python scripts/smoke_data_integrity.py 600519.SH | 600519.SH | failure | None | None | news_bundle_errors_4 |
| /root/.pyenv/versions/3.11.12/bin/python scripts/smoke_data_integrity.py 600519.SH | 600519.SH | failure | None | None | news_bundle_network_blocked |
| /root/.pyenv/versions/3.11.12/bin/python scripts/smoke_data_integrity.py 600519.SH | 600519.SH | failure | None | None | news_bundle_network_blocked |

## Findings Summary
- quote unavailable for 600519.SH (filled=0, errors=1)
- financial unavailable for 600519.SH (filled=0, errors=3)
- money_flow unavailable for 600519.SH (filled=0, errors=1)
- news_bundle unavailable for 600519.SH (filled=0, errors=4)
- Smoke failure: quote_filled_zero for 600519.SH
- Smoke failure: quote_errors_1 for 600519.SH
- Smoke failure: quote_network_blocked for 600519.SH
- Smoke failure: financial_filled_zero for 600519.SH
- Smoke failure: financial_errors_3 for 600519.SH
- Smoke failure: financial_network_blocked for 600519.SH
- Smoke failure: money_flow_filled_zero for 600519.SH
- Smoke failure: money_flow_errors_1 for 600519.SH
- Smoke failure: money_flow_network_blocked for 600519.SH
- Smoke failure: news_bundle_filled_zero for 600519.SH
- Smoke failure: news_bundle_errors_4 for 600519.SH
- Smoke failure: news_bundle_network_blocked for 600519.SH
- Smoke failure: news_announcements_empty for 600519.SH
- Smoke failure: news_reports_empty for 600519.SH
- Smoke failure: news_hot_events_empty for 600519.SH
- quote unavailable for 600519.SH (filled=0, errors=0)
- financial unavailable for 600519.SH (filled=0, errors=0)
- money_flow unavailable for 600519.SH (filled=0, errors=0)
- news_bundle unavailable for 600519.SH (filled=0, errors=0)
- Smoke failure: announcements_empty for 600519.SH
- Smoke failure: reports_empty for 600519.SH
- Smoke failure: hot_events_empty for 600519.SH
- Smoke failure: quote_filled_zero for 600519.SH
- Smoke failure: quote_errors_1 for 600519.SH
- Smoke failure: quote_network_blocked for 600519.SH
- Smoke failure: financial_filled_zero for 600519.SH
- Smoke failure: financial_errors_3 for 600519.SH
- Smoke failure: financial_network_blocked for 600519.SH
- Smoke failure: money_flow_filled_zero for 600519.SH
- Smoke failure: money_flow_errors_1 for 600519.SH
- Smoke failure: money_flow_network_blocked for 600519.SH
- Smoke failure: news_bundle_filled_zero for 600519.SH
- Smoke failure: news_bundle_errors_4 for 600519.SH
- Smoke failure: news_bundle_network_blocked for 600519.SH
- Smoke failure: news_bundle_network_blocked for 600519.SH
- quote unavailable for 600519.SH (filled=0, errors=0)
- financial unavailable for 600519.SH (filled=0, errors=0)
- money_flow unavailable for 600519.SH (filled=0, errors=0)
- news_bundle unavailable for 600519.SH (filled=0, errors=0)
- Smoke failure: invalid_report_period for 600519.SH
- Smoke failure: financial_missing_pe_ttm for 600519.SH
- Smoke failure: quote_filled_zero for 600519.SH
- Smoke failure: quote_errors_1 for 600519.SH
- Smoke failure: quote_network_blocked for 600519.SH
- Smoke failure: financial_filled_zero for 600519.SH
- Smoke failure: financial_errors_3 for 600519.SH
- Smoke failure: financial_network_blocked for 600519.SH
- Smoke failure: money_flow_filled_zero for 600519.SH
- Smoke failure: money_flow_errors_1 for 600519.SH
- Smoke failure: money_flow_network_blocked for 600519.SH
- Smoke failure: news_bundle_filled_zero for 600519.SH
- Smoke failure: news_bundle_errors_4 for 600519.SH
- Smoke failure: news_bundle_network_blocked for 600519.SH
- Smoke failure: news_bundle_network_blocked for 600519.SH

## Data Integrity Notes
- Validate that evidence_pack includes provider_trace and separated retrieved_at/report_period in downstream debugging.
- If filled=0 appears alongside network errors, treat as NETWORK_BLOCKED rather than success.

## Next-step Minimal Fix Plan
- Harden providers to return non-empty filled_metrics or surface clearer network errors in diagnostics.
- Ensure smoke scripts treat filled=0 or errors_count>0 as failures (already enforced in current scripts).
- Re-run doctor_report after addressing data availability and serialization gaps.
