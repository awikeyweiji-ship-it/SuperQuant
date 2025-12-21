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


def validate_payload(stock: Dict[str, Any]) -> Dict[str, Any]:
    diag = stock.get("diagnostics") or []
    meta = stock.get("_meta") or {}
    failures: List[str] = []

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
    return {"diagnostics": diag, "failures": failures}


def main() -> int:
    inputs = sys.argv[1:] if len(sys.argv) > 1 else ["600519.SH", "000001.SZ", "601872.SH"]
    engine = DataEngine(cache=UniverseCache())
    reports: List[Dict[str, Any]] = []
    any_failures = False

    for raw in inputs:
        code_std = standardize_code(raw)
        stock = engine.single_stock(code_std)
        validation = validate_payload(stock)
        any_failures = any_failures or bool(validation.get("failures"))
        reports.append({"code": code_std, "failures": validation.get("failures"), "diagnostics": validation.get("diagnostics")})

    print(json.dumps(reports, ensure_ascii=False, indent=2))
    return 1 if any_failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
