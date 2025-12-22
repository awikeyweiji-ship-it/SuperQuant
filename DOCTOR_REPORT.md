# Doctor Report

Generated: 2025-12-22T00:00:00Z

## Environment
- Python: 3.11.12
- Platform: Linux

## Commands Executed
- `python scripts/smoke_single_stock.py 600519 <TOKEN>` -> not run (TuShare token not available in CI container).
- `python scripts/smoke_radar.py <TOKEN>` -> not run (TuShare token not available in CI container).

### Logs
- Smokes are gated on an explicit TuShare Pro token argument. Without a provided token, the scripts intentionally exit with usage guidance and do not attempt network calls.

## Status
TuShare Pro is now the primary data backbone. A valid TuShare token must be entered via the Streamlit sidebar or passed to smoke scripts for real data. In this container no token is available, so connectivity and data retrieval were not exercised; users should supply their own TuShare Pro token locally to validate non-empty outputs.
