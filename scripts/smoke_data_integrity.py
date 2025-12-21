"""Integrity check for single stock payload produced by DataEngine.single_stock."""
from __future__ import annotations

import json
import sys
from typing import Any, Dict, List

ROOT = __file__.split("scripts")[0].rstrip("/")
if ROOT and ROOT not in sys.path:
    sys.path.append(ROOT)

from data_engine import DataEngine, standardize_code
from universe_cache import UniverseCache


REQUIRED_FIN_KEYS = ["pe_ttm", "pb", "roe", "report_period"]


def validate(stock: Dict[str, Any]) -> List[str]:
    failures: List[str] = []
    meta = stock.get("_meta", {}) if isinstance(stock, dict) else {}
    fin_meta = meta.get("financial", {}) if isinstance(meta, dict) else {}
    if not fin_meta.get("retrieved_at") and not fin_meta.get("ts"):
        failures.append("missing_financial_retrieved_at")
    rp = fin_meta.get("report_period")
    if rp in ("2003-12-31", "", None):
        failures.append("invalid_report_period")

    fin = stock.get("financial", {}) if isinstance(stock, dict) else {}
    for key in REQUIRED_FIN_KEYS:
        if fin.get(key) in (None, "", "--"):
            failures.append(f"financial_missing_{key}")
            break

    serialized = json.dumps(stock, ensure_ascii=False, default=str)
    if "example.com" in serialized:
        failures.append("example_stub_detected")
    return failures


def main() -> int:
    codes = sys.argv[1:] if len(sys.argv) > 1 else ["600519.SH", "000001.SZ", "601872.SH"]
    engine = DataEngine(cache=UniverseCache())
    report: List[Dict[str, Any]] = []
    any_failures = False

    for raw in codes:
        code_std = standardize_code(raw)
        payload = engine.single_stock(code_std)
        failures = validate(payload)
        any_failures = any_failures or bool(failures)
        report.append({"code": code_std, "failures": failures})

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if any_failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
