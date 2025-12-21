#!/usr/bin/env python
"""Smoke test for Smart Radar output completeness."""
from __future__ import annotations
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.append(ROOT)

import pandas as pd
from data_engine import DataEngine, normalize_code
from opportunity_radar import OpportunityRadar
from universe_cache import UniverseCache


def load_codes(engine: DataEngine, n: int = 20) -> list[str]:
    snap = engine.get_spot_snapshot(ttl_seconds=60)
    if snap is not None and not snap.empty:
        return [normalize_code(c) for c in snap.head(n)["code"].tolist()]
    return ["600519", "000001", "601872", "300750", "002415"]


def main():
    engine = DataEngine(cache=UniverseCache())
    radar = OpportunityRadar(engine)
    radar.capital_engine = None  # 避免资金流接口在无网环境长时间阻塞
    codes = load_codes(engine, 25)
    df = radar.build_radar_table(codes[:5])
    checks = {
        "rows": len(df),
        "min_reasons": int(df["evidence_points"].apply(lambda x: len(x) if isinstance(x, list) else 0).min() if not df.empty else 0),
        "min_links": int(df["evidence_links"].apply(lambda x: len(x) if isinstance(x, list) else 0).min() if not df.empty else 0),
    }
    print("Radar summary", checks)
    print(df[["code", "score_total", "action", "resonance_reason"]].head())


if __name__ == "__main__":
    main()
