# Doctor Report

Generated: 2025-02-19T00:00:00Z (sandbox refresh with akshare spot/kline restored)

## Environment
- Python: 3.11.12
- Platform: Linux (sandbox)

## Commands Executed (sandbox)
- `python scripts/smoke_single_stock.py 601872` -> ⚠️ blocked by proxy (all public endpoints 403; baostock login failure). Parser now reports provider errors without crashing.
- `python scripts/smoke_single_stock.py 000801` -> ⚠️ blocked by proxy (k线/quote 403; announcements fell back to sample). Offline sample labeled in provider trace.

### Connectivity diagnostics
- Tencent k线 parser now accepts multiple symbol keys (sh/sz/plain) and qfq/day/daily lists; HTML bodies are flagged as `blocked_html` instead of causing empty rows.
- Exchange / cninfo / Eastmoney announcement fetchers now send UA/Referer headers and return empty lists on HTML/404 so `NoneType.get` crashes are avoided; fallback traces capture the blocking reason.
- Baostock logout is guarded with a sentinel to avoid duplicated socket closes (WinError 10038).
- Sandbox proxy still returns 403 to all external hosts; on a real Windows network the primary Tencent k线/quote paths should populate >=120 rows and a non-blank price.

## Status
- Restored the Tencent fqkline primary path with robust key detection and numeric parsing so real rows are kept when the endpoint responds with JSON.
- Added announcement hardening (headers + safe fallbacks) and guarded baostock logout to prevent WinError 10038.
- UI shows quote source badge and still labels derived closes as “非实时：使用最近收盘价 …” when realtime quotes are missing.

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
