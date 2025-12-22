# Doctor Report

Generated: 2025-12-22T00:00:00Z

## Environment
- Python: 3.11.12
- Platform: Linux

## Commands Executed
- `python -m compileall .` -> ✅ (compilation completed)
- `python scripts/smoke_single_stock.py 600519` -> ❌ (network/proxy blocked upstream providers; baostock unavailable in container)

### Logs
- compileall produced bytecode for the repo without errors.
- Smoke run failed early because all external providers (Sina/Tencent/CNINFO/baoStock/Akshare) were blocked by the proxy in this CI container (HTTP 403) and baostock is not installed here. Quote/K线/公告/财务 payloads remained empty.

## Status
Single-stock pipeline now targets BaoStock (K线+财务) and CNINFO (公告) with derived quote fallback. Local execution in this container failed due to proxy restrictions and missing baostock package; re-run in a networked Windows environment with `pip install -r requirements.txt` should yield non-empty results.
