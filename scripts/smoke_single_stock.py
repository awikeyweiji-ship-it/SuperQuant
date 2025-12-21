"""Single stock smoke test driven by the new provider fan-out pipeline.

验收示例：python -m compileall app.py data_engine.py logging_utils.py alternative_data.py data_sources scripts
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any, Dict, List

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.append(ROOT)

from data_engine import DataEngine, standardize_code
from universe_cache import UniverseCache

NETWORK_KEYWORDS = [
    "network is unreachable",
    "connection refused",
    "timed out",
    "max retries",
    "proxy",
]


def validate_payload(stock: Dict[str, Any]) -> Dict[str, Any]:
    diag = stock.get("diagnostics") or []
    meta = stock.get("_meta") or {}
    failures: List[str] = []
    module_results: List[Dict[str, Any]] = []
    provider_trace = stock.get("provider_trace") or {}

    def _get_meta(name: str) -> Dict[str, Any]:
        val = meta.get(name, {}) if isinstance(meta, dict) else {}
        return val if isinstance(val, dict) else {}

    # 验收 retrieved_at 与 report_period
    fin_meta = _get_meta("financial")
    retrieved_ok = fin_meta.get("retrieved_at") is not None or fin_meta.get("ts") is not None
    report_period = fin_meta.get("report_period")
    if not retrieved_ok:
        failures.append("financial_retrieved_at_missing")
    if report_period in ("2003-12-31",):
        failures.append("financial_report_period_invalid")

    # 核心字段不允许 example.com
    serialized = json.dumps(stock, ensure_ascii=False, default=str)
    if "example.com" in serialized:
        failures.append("contains_example_stub")

    diag_map = {d.get("module"): d for d in diag if isinstance(d, dict)}
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
                if f"{module}_network_blocked" not in module_failures:
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

    # news bundle basic schema
    nb = stock.get("news_bundle") or {}
    if isinstance(nb, dict):
        for key in ["announcements", "reports", "hot_events"]:
            val = nb.get(key) or []
            if val:
                first = val[0]
                for req in ["title", "source"]:
                    if not first.get(req):
                        failures.append(f"news_{key}_missing_{req}")
            else:
                failures.append(f"news_{key}_empty")
    return {"diagnostics": diag, "failures": failures, "module_results": module_results}


def main() -> int:
    inputs = sys.argv[1:] if len(sys.argv) > 1 else ["600519.SH", "000001.SZ", "601872.SH"]
    engine = DataEngine(cache=UniverseCache())
    reports: List[Dict[str, Any]] = []
    any_failures = False

    for raw in inputs:
        code_std = standardize_code(raw)
        stock = engine.single_stock(code_std)
        validation = validate_payload(stock)
        module_results = validation.get("module_results") or []
        entry = {
            "code": code_std,
            "failures": validation.get("failures"),
            "diagnostics": validation.get("diagnostics"),
            "module_results": module_results,
        }
        reports.append(entry)
        any_failures = any_failures or bool(validation.get("failures"))

    print(json.dumps(reports, ensure_ascii=False, indent=2))
    return 1 if any_failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
