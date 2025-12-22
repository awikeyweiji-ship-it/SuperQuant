# Doctor Report

Generated: 2025-12-22T00:00:00Z

## Environment
- Python: 3.11.12
- Platform: Linux

## Commands Executed
- `python -m compileall .` -> ✅ (compilation completed)
- `python scripts/smoke_single_stock.py 600519` -> ❌ (network/proxy blocked upstream providers; baostock not available in container)

### Logs
- compileall produced bytecode for the repo without errors.
- Smoke run failed because outbound requests to Sina/Tencent/Akshare/Eastmoney/CNINFO were blocked by the proxy (HTTP 403) and `baostock` is missing in this sandbox, so quote/K线/公告/财务 payloads remained empty. The smoke script now enforces >=120 K线 rows, >=8 financial numeric fields, and at least one announcement item.

## Status
New BaoStock-first K线/财务 and Eastmoney公告 providers are wired with derived-quote labeling. Run the smoke again on a networked Windows host with `pip install -r requirements.txt` to validate real data availability.
