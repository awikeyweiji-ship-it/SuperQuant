"""Smoke test for single stock data availability."""
from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from data_engine import DataEngine
from research.decision_engine import build_decision


def run_smoke(code: str) -> int:
    print("[1/1] data engine single_stock")
    engine = DataEngine()
    result = engine.single_stock(code)
    quote_meta = (result.get("_meta", {}) or {}).get("quote", {})
    quote_filled = quote_meta.get("filled_metrics", 0) or (1 if result.get("quote", {}).get("data") else 0)
    kline = result.get("kline", {}).get("daily", [])
    kline_len = len(kline)
    announcements = len(result.get("announcements", {}).get("data", {}).get("announcements", []))
    financial_fields = 0
    fin_meta = (result.get("_meta", {}) or {}).get("financial", {})
    if isinstance(result.get("financial"), dict):
        stmt = (result.get("financial", {}).get("data", {}) or {}).get("statements") or []
        if stmt:
            financial_fields = len([v for v in stmt[0].values() if isinstance(v, (int, float)) and v is not None])
    financial_fields = max(financial_fields, fin_meta.get("filled_metrics", 0) or 0)
    provider_trace = result.get("provider_trace", {})
    print(json.dumps({
        "quote_filled": quote_filled,
        "quote_is_derived": quote_meta.get("is_derived"),
        "kline_len": kline_len,
        "announcements": announcements,
        "financial_fields": financial_fields,
        "provider_trace": provider_trace,
    }, ensure_ascii=False, indent=2))
    kline_trace = provider_trace.get("kline", []) if isinstance(provider_trace, dict) else []
    for tr in kline_trace:
        print(f"KLINE provider {tr.get('provider')}: filled={tr.get('filled_metrics')} errors={tr.get('errors')}")
    price_val = None
    quote_data = result.get("quote", {}).get("data") or {}
    if isinstance(quote_data, dict):
        price_val = quote_data.get("price") or quote_data.get("close")
    if price_val in (None, "", "--"):
        if kline:
            price_val = kline[-1].get("close")
    decision = build_decision(result)
    decision_card = decision.get("decision_card", {}) if isinstance(decision, dict) else {}
    verdict = decision_card.get("verdict")
    dq_score = decision_card.get("data_quality_score")
    print("Decision card:")
    print(json.dumps(decision_card, ensure_ascii=False, indent=2))
    if price_val in (None, "", "--"):
        print("Smoke check failed: quote missing")
        return 2
    if kline_len < 120:
        print("Smoke check failed: insufficient kline rows")
        return 2
    if financial_fields < 8:
        print("Smoke check failed: insufficient financial fields")
        return 2
    if announcements < 1:
        print("Smoke check failed: no announcements")
        return 2
    if verdict not in {"BUY", "WATCH", "AVOID"}:
        print("Smoke check failed: invalid verdict")
        return 2
    if dq_score is None:
        print("Smoke check failed: missing data quality score")
        return 2
    return 0


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python scripts/smoke_single_stock.py <code>")
        return 2
    code = sys.argv[1]
    return run_smoke(code)


if __name__ == "__main__":
    raise SystemExit(main())
