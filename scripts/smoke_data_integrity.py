"""快速校验核心字段缩放与覆盖率。

运行示例：
    python scripts/smoke_data_integrity.py 600519.SH 000001.SZ 601872
"""
from __future__ import annotations

import json
import sys
from typing import Any, Dict, List

ROOT = __file__.split("scripts")[0].rstrip("/")
if ROOT and ROOT not in sys.path:
    sys.path.append(ROOT)

from data_engine import DataEngine, standardize_code
from universe_cache import UniverseCache


def summarize_quote(q: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "price": q.get("price"),
        "pct_chg": q.get("pct_chg"),
        "amount": q.get("amount"),
        "vol": q.get("vol"),
        "market_cap": q.get("market_cap"),
        "pe_ttm": q.get("pe_ttm"),
        "pb": q.get("pb"),
        "source": q.get("source"),
    }


def main() -> int:
    codes = sys.argv[1:] if len(sys.argv) > 1 else ["600519.SH", "000001.SZ", "601872.SH"]
    engine = DataEngine(cache=UniverseCache())
    report: List[Dict[str, Any]] = []

    for raw in codes:
        code_std = standardize_code(raw)
        entry: Dict[str, Any] = {"code": code_std, "checks": []}

        quote_res = engine.get_spot_row_structured(code_std)
        quote = quote_res.data if isinstance(quote_res.data, dict) else {}
        anomalies: List[str] = []
        price = quote.get("price")
        if price is None or price <= 0 or price > 10000:
            anomalies.append("price_out_of_range")
        pct = quote.get("pct_chg")
        if pct is None or abs(pct) > 20:
            anomalies.append("pct_suspect")
        if quote.get("market_cap") in (None, 0):
            anomalies.append("market_cap_missing")
        entry["quote"] = {
            "summary": summarize_quote(quote),
            "source": quote_res.source,
            "fallback_used": quote_res.fallback_used,
            "errors": quote_res.errors,
            "anomalies": anomalies,
        }

        fin_res = engine.get_financial_features_structured(code_std)
        fin = fin_res.data if isinstance(fin_res.data, dict) else {}
        filled = [k for k, v in fin.items() if v not in (None, "", "--")]
        entry["financial"] = {
            "filled_metrics": len(filled),
            "source": fin_res.source,
            "fallback_used": fin_res.fallback_used,
            "errors": fin_res.errors,
        }

        money_res = engine.get_money_flow_structured(code_std)
        money = money_res.data if isinstance(money_res.data, dict) else {}
        filled_money = [k for k, v in money.items() if v not in (None, "")]
        entry["money_flow"] = {
            "filled_metrics": len(filled_money),
            "source": money_res.source,
            "fallback_used": money_res.fallback_used,
            "errors": money_res.errors,
        }

        report.append(entry)

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
