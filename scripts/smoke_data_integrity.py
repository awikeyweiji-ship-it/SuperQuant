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
NETWORK_KEYWORDS = [
    "network is unreachable",
    "connection refused",
    "timed out",
    "max retries",
    "proxy",
]


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
        diagnostics = payload.get("diagnostics") or [] if isinstance(payload, dict) else []
        provider_trace = payload.get("provider_trace") or {}
        diag_map = {d.get("module"): d for d in diagnostics if isinstance(d, dict)}
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

        any_failures = any_failures or bool(failures)
        report.append({"code": code_std, "failures": failures, "module_results": module_results})

    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    return 1 if any_failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
