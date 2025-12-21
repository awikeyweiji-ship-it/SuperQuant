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
NETWORK_KEYWORDS = [
    "network is unreachable",
    "connection refused",
    "timed out",
    "max retries",
    "proxy",
]


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
    provider_trace = stock.get("provider_trace") or {}
    diag_map = {d.get("module"): d for d in diagnostics if isinstance(d, dict)}
    failures = validate_bundle(bundle if isinstance(bundle, dict) else {})

    module_results: List[Dict[str, Any]] = []
    for module in ["quote", "financial", "money_flow", "news_bundle"]:
        info = diag_map.get(module, {})
        filled = info.get("filled") or 0
        err_cnt = info.get("errors_count") or 0
        traces = provider_trace.get(module) if isinstance(provider_trace, dict) else []
        status = "OK"
        module_failures: List[str] = []
        if filled == 0:
            module_failures.append(f"{module}_filled_zero")
        if err_cnt > 0:
            module_failures.append(f"{module}_errors_{err_cnt}")
        for tr in traces or []:
            msg_blob = json.dumps(tr, ensure_ascii=False).lower()
            if any(kw in msg_blob for kw in NETWORK_KEYWORDS):
                status = "INCONCLUSIVE"
                module_failures.append(f"{module}_network_blocked")
        if module_failures:
            status = "FAIL" if status == "OK" else status
            failures.extend(module_failures)
        module_results.append(
            {
                "module": module,
                "filled_metrics": filled,
                "errors_count": err_cnt,
                "status": status,
                "provider_trace": traces,
                "missing_paths": info.get("missing_paths") or [],
            }
        )

    output = {"code": code, "failures": failures, "module_results": module_results}
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
