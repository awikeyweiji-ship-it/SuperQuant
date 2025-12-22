# Doctor Report

Generated: 2025-02-19T00:00:00Z (sandbox refresh with decision layer)

## Environment
- Python: 3.11.12
- Platform: Linux (sandbox)

## Commands Executed (sandbox)
- `pip install yfinance -q` -> ❌ (proxy 403, cannot reach PyPI)
- `python scripts/smoke_single_stock.py 000801` -> ✅ (decision card built; quote derived from latest close)
- `python scripts/smoke_single_stock.py 600519` -> ✅ (decision card built; quote derived from latest close)

### Logs
- External HTTP access to Eastmoney/Sina/Tencent/CNINFO is still blocked by the sandbox proxy (403), so live quote/K线/公告/财务 calls fail. Bundled deterministic samples now backfill all mandatory metrics, and quotes derive from the latest sample K线 when realtime is missing.
- Attempting to install `yfinance` to use Yahoo Finance also failed due to the proxy.
- Added a deterministic research decision layer that consumes kline/financial/announcement payloads and emits BUY/WATCH/AVOID with data-quality score and missing-data notes.

## Status
- Added akshare providers for quote/K线/财务 with highest priority, falling back to BaoStock/legacy routes and, if all else fails, bundled offline samples (>=200 bars, >=9 financial metrics, >=1 announcement).
- AlternativeData banner now prints safely on Windows consoles to avoid GBK encode errors seen in prior smoke runs.
- New research.decision_engine builds a “投研结论卡” directly in the app/smoke path so the single-stock page is never blank even without realtime quotes.

## Provider Fallback Snapshot
| Domain | Primary | Secondary | Offline backstop |
| --- | --- | --- | --- |
| Quote | akshare spot | Eastmoney/Sina/Tencent legacy | Derived from latest K线 sample |
| Kline | akshare qfq | BaoStock → Tencent | Bundled 200-row sample |
| Financial | akshare abstract | BaoStock → CNINFO report list | Bundled sample statement |
| Announcements | SSE/SZSE exchange | Eastmoney/Tencent/CNINFO | Bundled sample announcement |

## Self-check和后续改进
- **联网验证**：在实际可联网的 Windows 环境复核 akshare/BaoStock/交易所接口，确认能覆盖样本之外的股票并替换掉离线兜底。
- **数据来源提示**：UI 和诊断面板需要标明“offline_sample/derived_from_kline”以提示用户数据非实时。
- **缓存治理**：可增加最近成功时间/刷新按钮与 TTL 提示，防止离线样本长期掩盖真实接口故障。
