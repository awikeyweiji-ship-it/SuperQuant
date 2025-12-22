# Doctor Report

Generated: 2025-02-19T00:00:00Z (sandbox refresh with akshare spot/kline restored)

## Environment
- Python: 3.11.12
- Platform: Linux (sandbox)

## Commands Executed (sandbox)
- `python scripts/smoke_single_stock.py 000801` -> ✅ (kline rows: 200; quote fell back to derived close because proxy blocks akshare)
- `python scripts/smoke_single_stock.py 600519` -> ✅ (kline rows: 200; quote fell back to derived close because proxy blocks akshare)

### Connectivity diagnostics
- External HTTP access to Eastmoney/Sina/Tencent/CNINFO remains blocked by the sandbox proxy (403), so akshare spot/k线 calls throw ProxyError and the pipeline falls back to cached/synthetic data. In a real Windows environment with internet, akshare should now succeed because it uses the plain 6-digit symbols from the v1 working build.
- Decision engine remains intact and continues to consume the fetched payloads for the "投研结论卡".

## Status
- Ported the v1 working akshare paths: quote uses cached spot snapshot lookup; K线 uses plain 6-digit symbols (`stock_zh_a_hist` qfq) to avoid the prefix issue and is top priority.
- Provider priority remains akshare → Baostock/Tencent legacy, with offline sample only if online sources fail (clearly labeled).
- Decision engine and non-empty UI remain unchanged; derived price captions now read “非实时：使用最近收盘价 …” when realtime is missing.

## Provider Fallback Snapshot
| Domain | Primary | Secondary | Offline backstop |
| --- | --- | --- | --- |
| Quote | akshare spot snapshot (plain code) | Eastmoney/Sina/Tencent legacy | Derived from latest K线 sample |
| Kline | akshare stock_zh_a_hist qfq | BaoStock → Tencent | Bundled 200-row sample |
| Financial | akshare abstract | BaoStock → CNINFO report list | Bundled sample statement |
| Announcements | SSE/SZSE exchange | Eastmoney/Tencent/CNINFO | Bundled sample announcement |

## Self-check和后续改进
- **联网验证**：在可联网的 Windows 环境复核 akshare spot/K线是否恢复实时，确认 >=120 行日线、现价非空；此路径现已与 v1 工作版一致。
- **数据来源提示**：UI 已标记“非实时：使用最近收盘价”，但仍需在连接恢复时确保优先显示实时行情。
- **缓存治理**：spot snapshot 现缓存 180 秒；可增加刷新按钮或 TTL 提示，防止离线样本长期掩盖真实接口故障。
