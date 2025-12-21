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


def _fail(message: str) -> None:
    print(f"[SMOKE][FAIL] {message}")
    raise SystemExit(1)


def main():
    engine = DataEngine(cache=UniverseCache())
    radar = OpportunityRadar(engine)
    radar.capital_engine = None  # 避免资金流接口在无网环境长时间阻塞
    codes = load_codes(engine, 25)
    df = radar.build_radar_table(codes[:10])
    if df is None or df.empty:
        _fail("radar table is empty")

    rows = len(df)
    min_reasons = int(df["evidence_points"].apply(lambda x: len(x) if isinstance(x, list) else 0).min())
    min_links = int(df["evidence_links"].apply(lambda x: len(x) if isinstance(x, list) else 0).min())
    if rows < 10:
        _fail(f"radar rows below threshold: {rows}")
    if min_reasons < 8:
        _fail(f"evidence_points too sparse: {min_reasons}")
    if min_links < 1:
        _fail("evidence_links empty")

    checks = {"rows": rows, "min_reasons": min_reasons, "min_links": min_links}
    print("Radar summary", checks)
    print(df[["code", "score_total", "action", "resonance_reason"]].head())


if __name__ == "__main__":
    main()
