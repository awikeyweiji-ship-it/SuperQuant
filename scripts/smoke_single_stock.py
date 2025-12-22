"""Smoke test for single stock data availability."""
from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from data_engine import DataEngine
from tools import connectivity_doctor


def run_smoke(code: str, token: str) -> int:
    if not token:
        print("[ERROR] TuShare token missing; please provide as argument")
        return 2
    print("[1/2] connectivity doctor")
    connectivity_doctor.run(code)
    print("[2/2] data engine single_stock_tushare")
    engine = DataEngine()
    result = engine.single_stock_tushare(code, token=token)
    quote_filled = (result.get("quote", {}).get("meta", {}) or {}).get("filled_metrics", 0) or (1 if result.get("quote", {}).get("data") else 0)
    kline_len = len(result.get("kline", {}).get("daily", []))
    news_items = len(result.get("news_bundle", {}).get("announcements", [])) if isinstance(result.get("news_bundle", {}), dict) else 0
    financial_filled = (result.get("financial", {}).get("meta", {}) or {}).get("filled_metrics", 0) or len((result.get("financial", {}).get("data", {}) or {}).get("statements", []))
    print(json.dumps({
        "quote_filled": quote_filled,
        "kline_len": kline_len,
        "news_items": news_items,
        "financial": financial_filled,
        "provider_trace": result.get("provider_trace", {}),
    }, ensure_ascii=False, indent=2))
    if not token:
        return 2
    if quote_filled <= 0 or kline_len < 1 or news_items < 1 or financial_filled <= 0 or len(result.get("evidence_pack", [])) < 12:
        print("Smoke check failed; dumping traces")
        return 2
    return 0


def main() -> int:
    if len(sys.argv) < 3:
        print("Usage: python scripts/smoke_single_stock.py <code> <tushare_token>")
        return 2
    code = sys.argv[1]
    token = sys.argv[2]
    return run_smoke(code, token)


if __name__ == "__main__":
    raise SystemExit(main())
