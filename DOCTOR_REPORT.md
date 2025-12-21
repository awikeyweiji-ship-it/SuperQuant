# Doctor Report

Generated: 2025-12-21T16:04:00Z

## Environment
- Python: 3.11.12
- Platform: Linux

## Commands Executed
- `python -m compileall data_sources/kline_eastmoney.py data_engine.py scripts/smoke_single_stock.py` -> exit 0
- `python scripts/smoke_single_stock.py 600519` -> exit 1 (blocked by upstream proxy)
- `python scripts/smoke_single_stock.py 000001` -> exit 1 (blocked by upstream proxy)

### Logs
- smoke_single_stock 600519 output (proxy 403 on eastmoney/gtimg, kline/news/financial empty).【3718a1†L1-L93】
- smoke_single_stock 000001 output (proxy 403 on eastmoney/gtimg, kline/news/financial empty).【74d1ca†L1-L91】

## Status
Single-stock smokes failed in this environment due to proxy blocks (403 tunnel). Quote, kline, financial, and news endpoints returned no data because remote hosts were unreachable without a proxy.
