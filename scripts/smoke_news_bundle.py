"""Validate news bundle structure for a single symbol."""
from __future__ import annotations

import json
import sys
from typing import Any, Dict, List

ROOT = __file__.split("scripts")[0].rstrip("/")
if ROOT and ROOT not in sys.path:
    sys.path.append(ROOT)

from data_engine import DataEngine, standardize_code
from universe_cache import UniverseCache

REQUIRED_FIELDS = ["title", "time", "source", "url", "summary"]


def validate_item(item: Dict[str, Any]) -> List[str]:
    missing = []
    for key in REQUIRED_FIELDS:
        if not item.get(key):
            missing.append(key)
    return missing


def validate_bundle(bundle: Dict[str, Any]) -> List[str]:
    failures: List[str] = []
    if not bundle:
        failures.append("news_bundle_empty")
    for section in ["announcements", "reports", "hot_events"]:
        arr = bundle.get(section) or []
        if not arr:
            failures.append(f"{section}_empty")
            continue
        if not isinstance(arr, list):
            continue
        for itm in arr:
            bad = validate_item(itm if isinstance(itm, dict) else {})
            if bad:
                failures.append(f"{section}_missing_{','.join(bad)}")
                break
    return failures


def main() -> int:
    code = standardize_code(sys.argv[1]) if len(sys.argv) > 1 else "600519.SH"
    engine = DataEngine(cache=UniverseCache())
    stock = engine.single_stock(code)
    bundle = stock.get("news_bundle") if isinstance(stock, dict) else {}
    diagnostics = stock.get("diagnostics") or []
    diag_map = {d.get("module"): d for d in diagnostics if isinstance(d, dict)}
    nb_diag = diag_map.get("news_bundle", {})
    diag_filled = nb_diag.get("filled") or 0
    diag_errs = nb_diag.get("errors_count") or 0
    failures = validate_bundle(bundle if isinstance(bundle, dict) else {})
    if diag_filled == 0 or diag_errs > 0:
        failures.append("news_bundle_unavailable")
    print(json.dumps({"code": code, "failures": failures}, ensure_ascii=False, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
