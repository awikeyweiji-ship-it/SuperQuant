"""Minimal smoke test for single stock data chain.

Fetches quote, kline, financials, capital flow, and alternative intelligence
for a given symbol (default: 600519). Exits with non-zero status if any
critical module is empty while emitting structured reasons.
"""
from __future__ import annotations

import sys
import os
import json
from typing import Any, Dict, List

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.append(ROOT)

from data_engine import DataEngine, normalize_code, standardize_code
from logging_utils import FetchResult
from universe_cache import UniverseCache


def summarize_dict(d: Dict[str, Any], keys: List[str]) -> Dict[str, Any]:
    return {k: d.get(k) for k in keys if isinstance(d, dict) and k in d}


def as_record(step: str, res: FetchResult, summary_keys: List[str]) -> Dict[str, Any]:
    payload = res.data
    if isinstance(payload, dict):
        payload = summarize_dict(payload, summary_keys)
    return {
        "step": step,
        "ok": bool(res.ok),
        "source": res.source,
        "fallback_used": res.fallback_used,
        "errors": res.errors,
        "summary": payload,
    }


def run_symbol(engine: DataEngine, raw: str) -> Dict[str, Any]:
    code_std = standardize_code(raw)
    code = normalize_code(code_std)

    results: List[Dict[str, Any]] = []
    failures: List[str] = []

    # 1) Quote / identity
    try:
        spot = engine.get_spot_row_structured(code)
        results.append(as_record("quote", spot, ["code", "name", "price", "pct_chg", "vol", "amount", "turnover", "source", "market_cap"]))
        if not spot.ok:
            failures.append("quote")
    except Exception as e:
        failures.append("quote")
        results.append({"step": "quote", "ok": False, "errors": [{"source": "script", "error_type": "exception", "message": str(e)}]})

    try:
        ident = engine.get_stock_identity_structured(code)
        results.append(as_record("identity", ident, ["code", "name", "sector", "concepts"]))
        if not ident.ok:
            failures.append("identity")
    except Exception as e:
        failures.append("identity")
        results.append({"step": "identity", "ok": False, "errors": [{"source": "script", "error_type": "exception", "message": str(e)}]})

    # 2) Kline
    try:
        kline = engine.get_kline_structured(code_std, limit=60)
        sample = []
        rows = 0
        if hasattr(kline.data, "empty") and not kline.data.empty:
            rows = len(kline.data)
            tail_df = kline.data.tail(3).copy()
            if "date" in tail_df.columns:
                tail_df["date"] = tail_df["date"].astype(str)
            sample = tail_df.to_dict(orient="records")
        results.append({
            "step": "kline",
            "ok": bool(kline.ok) and rows >= 30,
            "source": kline.source,
            "fallback_used": kline.fallback_used,
            "errors": kline.errors,
            "summary": sample,
            "meta": {"rows": rows, "final_source": kline.source},
        })
        if (not kline.ok) or rows < 30:
            failures.append("kline")
    except Exception as e:
        failures.append("kline")
        results.append({"step": "kline", "ok": False, "errors": [{"source": "script", "error_type": "exception", "message": str(e)}]})

    # 3) Financials
    try:
        fin = engine.get_financial_features_structured(code)
        fin_data = fin.data if isinstance(fin.data, dict) else {}
        filled = [k for k in [
            "revenue",
            "net_profit",
            "gross_margin",
            "net_margin",
            "roe",
            "roa",
            "debt_ratio",
            "op_cashflow",
            "pe_ttm",
            "pb",
            "total_mv",
            "float_mv",
            "market_cap",
        ] if fin_data.get(k) not in (None, "")]
        filled_count = fin.meta.get("filled_metrics") if isinstance(fin.meta, dict) else len(filled)
        ok_fin = bool(fin.ok) and filled_count >= 3 and fin.source not in ("offline_stub", "sample_cache")
        results.append({
            "step": "financials",
            "ok": ok_fin,
            "source": fin.source,
            "fallback_used": fin.fallback_used,
            "errors": fin.errors,
            "summary": summarize_dict(fin_data, ["report_date", "revenue", "net_profit", "gross_margin", "net_margin", "roe", "roa", "debt_ratio", "op_cashflow"]),
            "meta": {"filled_metrics": filled_count},
        })
        if not ok_fin:
            failures.append("financials")
    except Exception as e:
        failures.append("financials")
        results.append({"step": "financials", "ok": False, "errors": [{"source": "script", "error_type": "exception", "message": str(e)}]})

    # 4) Capital flow
    try:
        money = engine.get_money_flow_structured(code)
        money_data = money.data if isinstance(money.data, dict) else {}
        fill_keys = [
            "main_net_inflow",
            "large_net_inflow",
            "super_large_net_inflow",
            "northbound_net_inflow",
            "margin_balance",
        ]
        filled = [k for k in fill_keys if money_data.get(k) not in (None, "")]
        ok_money = bool(money.ok) and len(filled) > 0
        results.append({
            "step": "capital_flow",
            "ok": ok_money,
            "source": money.source,
            "fallback_used": money.fallback_used,
            "errors": money.errors,
            "summary": summarize_dict(
                money_data,
                [
                    "main_net_inflow",
                    "super_large_net_inflow",
                    "large_net_inflow",
                    "medium_net_inflow",
                    "small_net_inflow",
                    "northbound_net_inflow",
                    "margin_balance",
                    "margin_date",
                ],
            ),
            "meta": {"filled_metrics": len(filled)},
        })
        if not ok_money:
            failures.append("capital_flow")
    except Exception as e:
        failures.append("capital_flow")
        results.append({"step": "capital_flow", "ok": False, "errors": [{"source": "script", "error_type": "exception", "message": str(e)}]})

    # 5) Alternative / news
    try:
        if engine.alt_engine:
            alt = engine.alt_engine.get_alternative_report_structured(code, sector="")
            alt_data = alt.data if isinstance(alt.data, dict) else {}
            sentiment = alt_data.get("sentiment", {}) if isinstance(alt_data, dict) else {}
            posts = sentiment.get("sample_posts") or []
            ok_alt = bool(alt.ok) and sentiment.get("sentiment_score") is not None and len(posts) >= 3
            results.append(
                {
                    "step": "alternative",
                    "ok": ok_alt,
                    "source": alt.source,
                    "fallback_used": alt.fallback_used,
                    "errors": alt.errors,
                    "summary": {
                        "sentiment_score": sentiment.get("sentiment_score"),
                        "hot_words": sentiment.get("hot_words", [])[:5],
                        "sample_posts": posts[:3],
                    },
                    "meta": {"post_count": len(posts)},
                }
            )
            if not ok_alt:
                failures.append("alternative")
        else:
            failures.append("alternative")
            results.append({"step": "alternative", "ok": False, "errors": [{"source": "alt_engine", "error_type": "missing", "message": "未初始化"}]})
    except Exception as e:
        failures.append("alternative")
        results.append({"step": "alternative", "ok": False, "errors": [{"source": "script", "error_type": "exception", "message": str(e)}]})

    # 6) 公告
    try:
        ann = engine.get_announcements_structured(code_std, limit=12)
        ann_list = ann.data if isinstance(ann.data, list) else []
        ok_ann = bool(ann.ok) and len(ann_list) >= 10
        results.append(
            {
                "step": "announcements",
                "ok": ok_ann,
                "source": ann.source,
                "fallback_used": ann.fallback_used,
                "errors": ann.errors,
                "summary": ann_list[:3],
                "meta": {"count": len(ann_list)},
            }
        )
        if not ok_ann:
            failures.append("announcements")
    except Exception as e:
        failures.append("announcements")
        results.append({"step": "announcements", "ok": False, "errors": [{"source": "script", "error_type": "exception", "message": str(e)}]})

    # 7) 研报
    try:
        rep = engine.get_research_reports_structured(code_std, limit=12)
        rep_list = rep.data if isinstance(rep.data, list) else []
        ok_rep = bool(rep.ok) and len(rep_list) >= 10
        results.append(
            {
                "step": "research_reports",
                "ok": ok_rep,
                "source": rep.source,
                "fallback_used": rep.fallback_used,
                "errors": rep.errors,
                "summary": rep_list[:3],
                "meta": {"count": len(rep_list)},
            }
        )
        if not ok_rep:
            failures.append("research_reports")
    except Exception as e:
        failures.append("research_reports")
        results.append({"step": "research_reports", "ok": False, "errors": [{"source": "script", "error_type": "exception", "message": str(e)}]})

    # 8) 热点要事
    try:
        hot = engine.get_hot_topics_structured(limit=8)
        hot_list = hot.data if isinstance(hot.data, list) else []
        ok_hot = bool(hot.ok) and len(hot_list) > 0
        results.append(
            {
                "step": "hot_topics",
                "ok": ok_hot,
                "source": hot.source,
                "fallback_used": hot.fallback_used,
                "errors": hot.errors,
                "summary": hot_list[:3],
                "meta": {"count": len(hot_list)},
            }
        )
        if not ok_hot:
            failures.append("hot_topics")
    except Exception as e:
        failures.append("hot_topics")
        results.append({"step": "hot_topics", "ok": False, "errors": [{"source": "script", "error_type": "exception", "message": str(e)}]})

    return {"code": code_std, "results": results, "failures": failures}


def main() -> int:
    inputs = sys.argv[1:] if len(sys.argv) > 1 else ["600519.SH", "000001.SZ", "601872.SH"]
    engine = DataEngine(cache=UniverseCache())

    outputs: List[Dict[str, Any]] = []
    any_failures = False

    for raw in inputs:
        result = run_symbol(engine, raw)
        outputs.append(result)
        if result.get("failures"):
            any_failures = True

    print(json.dumps(outputs, ensure_ascii=False, indent=2))
    return 0 if not any_failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
