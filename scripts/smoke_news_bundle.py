#!/usr/bin/env python
"""Quick smoke test for news bundle completeness."""
from __future__ import annotations
import os
import sys
from typing import Dict, Any

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.append(ROOT)

from data_engine import DataEngine, standardize_code
from universe_cache import UniverseCache


def check_bundle(code: str) -> Dict[str, Any]:
    engine = DataEngine(cache=UniverseCache())
    res = engine.get_news_bundle_structured(code)
    data = res.data if isinstance(res.data, dict) else {}
    non_empty = {k: len(v or []) for k, v in data.items() if isinstance(v, list)}
    coverage = sum(1 for _, cnt in non_empty.items() if cnt > 0)
    missing_fields = []
    for cat, items in data.items():
        for idx, item in enumerate(items):
            for field in ["title", "time", "source", "url"]:
                if not item.get(field):
                    missing_fields.append((cat, idx, field))
    return {
        "code": code,
        "ok": coverage >= 2 and not missing_fields,
        "coverage": coverage,
        "non_empty": non_empty,
        "source": res.source,
        "fallback_used": res.fallback_used,
        "errors": res.errors,
        "missing_fields": missing_fields,
    }


def main():
    for raw in ["600519.SH", "000001.SZ", "601872.SH"]:
        std = standardize_code(raw)
        result = check_bundle(std)
        print(result)


if __name__ == "__main__":
    main()
