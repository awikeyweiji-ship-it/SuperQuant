# -*- coding: utf-8 -*-
"""factor_store.py
===================
慢变量因子落盘：Factor Store (SQLite)

目标：把“政策强度/持续性、需求空间、国产替代、市场定价、信息充分性”等慢变量
固化为 **按日** 的可回测因子。

表设计：
- factor_snapshot: (as_of, code) 主键，存储 0~1 的标准化因子。
"""

from __future__ import annotations

import json
import os
import sqlite3
from typing import Any, Dict, List, Optional


class FactorStore:
    def __init__(self, path: str = ".w5brain_factors.sqlite"):
        self.path = path
        self._ensure_db()

    def _ensure_db(self) -> None:
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        with sqlite3.connect(self.path) as conn:
            c = conn.cursor()
            c.execute(
                """
                CREATE TABLE IF NOT EXISTS factor_snapshot (
                    as_of TEXT NOT NULL,
                    code TEXT NOT NULL,
                    policy_strength REAL,
                    policy_persistence REAL,
                    demand_space REAL,
                    domestic_substitution REAL,
                    market_pricing REAL,
                    info_priced_in REAL,
                    slow_total REAL,
                    meta_json TEXT,
                    PRIMARY KEY(as_of, code)
                );
                """
            )
            c.execute("CREATE INDEX IF NOT EXISTS idx_factor_asof ON factor_snapshot(as_of);")
            c.execute("CREATE INDEX IF NOT EXISTS idx_factor_code ON factor_snapshot(code);")
            conn.commit()

    def upsert_many(self, as_of: str, rows: List[Dict[str, Any]]) -> int:
        if not rows:
            return 0
        to_write = []
        for r in rows:
            meta_json = json.dumps(r.get("meta") or {}, ensure_ascii=False)
            to_write.append(
                (
                    str(as_of),
                    str(r.get("code") or ""),
                    float(r.get("policy_strength") or 0.0),
                    float(r.get("policy_persistence") or 0.0),
                    float(r.get("demand_space") or 0.0),
                    float(r.get("domestic_substitution") or 0.0),
                    float(r.get("market_pricing") or 0.0),
                    float(r.get("info_priced_in") or 0.0),
                    float(r.get("slow_total") or 0.0),
                    meta_json,
                )
            )

        with sqlite3.connect(self.path) as conn:
            c = conn.cursor()
            c.executemany(
                """
                INSERT INTO factor_snapshot (
                    as_of, code, policy_strength, policy_persistence, demand_space,
                    domestic_substitution, market_pricing, info_priced_in,
                    slow_total, meta_json
                ) VALUES (?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(as_of, code) DO UPDATE SET
                    policy_strength=excluded.policy_strength,
                    policy_persistence=excluded.policy_persistence,
                    demand_space=excluded.demand_space,
                    domestic_substitution=excluded.domestic_substitution,
                    market_pricing=excluded.market_pricing,
                    info_priced_in=excluded.info_priced_in,
                    slow_total=excluded.slow_total,
                    meta_json=excluded.meta_json;
                """,
                to_write,
            )
            conn.commit()
            return c.rowcount or len(to_write)

    def get_latest(self, code: str) -> Optional[Dict[str, Any]]:
        code = str(code).strip()
        if not code:
            return None
        with sqlite3.connect(self.path) as conn:
            conn.row_factory = sqlite3.Row
            c = conn.cursor()
            c.execute(
                """
                SELECT * FROM factor_snapshot
                WHERE code=?
                ORDER BY as_of DESC
                LIMIT 1;
                """,
                (code,),
            )
            row = c.fetchone()
            if not row:
                return None
            d = dict(row)
            try:
                d["meta"] = json.loads(d.get("meta_json") or "{}")
            except Exception:
                d["meta"] = {}
            d.pop("meta_json", None)
            return d

    def get_for_date(self, as_of: str, codes: List[str]) -> Dict[str, Dict[str, Any]]:
        """批量获取某日的因子快照。返回 code -> factor dict。"""
        if not codes:
            return {}
        codes = [str(c).strip() for c in codes if str(c).strip()]
        if not codes:
            return {}
        placeholders = ",".join(["?"] * len(codes))
        with sqlite3.connect(self.path) as conn:
            conn.row_factory = sqlite3.Row
            c = conn.cursor()
            c.execute(
                f"SELECT * FROM factor_snapshot WHERE as_of=? AND code IN ({placeholders});",
                [str(as_of)] + codes,
            )
            out: Dict[str, Dict[str, Any]] = {}
            for r in c.fetchall():
                d = dict(r)
                try:
                    d["meta"] = json.loads(d.get("meta_json") or "{}")
                except Exception:
                    d["meta"] = {}
                d.pop("meta_json", None)
                out[str(d.get("code"))] = d
            return out
