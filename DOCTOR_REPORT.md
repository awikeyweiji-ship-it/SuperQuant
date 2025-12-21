# Doctor Report

Generated: 2025-12-21T16:15:50Z

## Environment
- Python: 3.11.12
- Platform: Linux

## Commands Executed
- `python -m compileall data_sources/quote_sina.py data_sources/kline_tencent.py data_sources/financial_em_basic.py data_sources/announcements_cninfo.py data_sources/news_sina.py data_engine.py` -> exit 0.【e33eb9†L1-L8】
- `python scripts/smoke_single_stock.py 600519` -> exit 1 (proxy 403 blocked all providers).【efc203†L1-L118】

### Logs
- smoke_single_stock 600519 output shows 403 proxy failures across quote/kline/financial/news providers, yielding empty data and failing hard as required.【efc203†L1-L118】

## Status
Single-stock smokes failed in this environment due to proxy blocks (403 tunnel). Quote, kline, financial, and news endpoints returned no data because remote hosts were unreachable without a proxy.
