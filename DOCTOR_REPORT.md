# Doctor Report

Generated: 2025-02-19T00:00:00Z (sandbox refresh with UI normalization + debug expander)

## Environment
- Python: 3.11.12
- Platform: Linux (sandbox)

## Commands Executed (sandbox)
- `python -m compileall .` -> ✅ completes (very slow due to full site-packages scan).
- `python scripts/smoke_single_stock.py 601872` -> ❌ proxy 403 on quote/k线/announcement; baostock login fails; smoke reports errors but exits cleanly (no WinError 10038).
- `python scripts/smoke_single_stock.py 000801` -> ⚠️ proxy 403 so quote/k线 fall back to derived/sample; announcements use labeled sample; smoke finishes without exceptions.
- `streamlit run app.py --server.headless true --server.port 8501` (timeout 20s) -> ✅ launches and renders headless; terminated manually after startup.

### Connectivity diagnostics
- Tencent k线 parser accepts sh/sz/plain symbols and qfq/day/daily keys; HTML bodies flagged as `blocked_html`. When reachable it returns numeric bars into the normalized payload so Streamlit tabs render immediately.
- Announcement fetchers return [] with explicit errors on HTML/404 and now set UA/Referer headers; provider_trace errors surface in the new debug expander instead of crashing the page.
- Baostock logout still guarded; Broken pipe warnings from the proxy do not bubble into WinError 10038.
- Sandbox proxy returns 403 to all external hosts, so realtime quote/k线 stay empty here. On a real Windows network the restored Tencent/baostock paths should fill >=120 rows and non-blank price.

## Status
- Normalized `single_stock` payloads (quote/k线/财务/公告) for Streamlit so “现价” and charts read the real fields instead of nested blobs; added a debug expander that prints the raw payload + provider_trace for on-screen triage.
- K线 tab now prefers the fetched daily bars (DataFrame if available) and renders MA/volume charts without re-fetching.
- Announcement empty states no longer blank the page; errors are shown inline and metrics remain visible.

## Provider Fallback Snapshot
| Domain | Primary | Secondary | Offline backstop |
| --- | --- | --- | --- |
| Quote | akshare spot snapshot (plain code) | Eastmoney/Sina/Tencent legacy | Derived from latest K线 sample |
| Kline | Tencent fqkline (qfqday/day auto-parse) | akshare stock_zh_a_hist → BaoStock | Bundled 200-row sample |
| Financial | akshare abstract | BaoStock → CNINFO report list | Bundled sample statement |
| Announcements | SSE/SZSE exchange | Eastmoney/Tencent/CNINFO | Bundled sample announcement |

## Self-check和后续改进
- **联网验证**：在可联网的 Windows 环境复核 akshare spot/K线是否恢复实时，确认 >=120 行日线、现价非空；此路径现已与 v1 工作版一致。
- **数据来源提示**：UI 已标记“非实时：使用最近收盘价”，但仍需在连接恢复时确保优先显示实时行情。
- **缓存治理**：spot snapshot 现缓存 180 秒；可增加刷新按钮或 TTL 提示，防止离线样本长期掩盖真实接口故障。
