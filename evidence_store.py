# -*- coding: utf-8 -*-
"""evidence_store.py
====================
证据链落盘：Evidence Store (SQLite)

用途：
1) 为“政策强度/持续性、需求空间、国产替代、信息充分性”等慢变量提供可追溯证据。
2) 将外部搜索/新闻抓取的碎片化信息固化为时间序列，支持样本外回测。

约束：
- 轻量、零依赖（标准库 sqlite3）。
- 字段尽量通用：source/title/snippet/url/published_at/tags/score。
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from typing import Any, Dict, List, Optional


def _utc_ts() -> int:
    return int(time.time())


class EvidenceStore:
    def __init__(self, path: str = ".w5brain_evidence.sqlite"):
        self.path = path
        self._ensure_db()

    def _ensure_db(self) -> None:
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        with sqlite3.connect(self.path) as conn:
            c = conn.cursor()
            c.execute(
                """
                CREATE TABLE IF NOT EXISTS evidence (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ingested_ts INTEGER NOT NULL,
                    published_at TEXT,
                    source TEXT,
                    title TEXT,
                    snippet TEXT,
                    url TEXT,
                    tags_json TEXT,
                    policy_strength REAL,
                    policy_sustain REAL,
                    demand_signal REAL,
                    substitution_signal REAL,
                    trust REAL
                );
                """
            )
            c.execute("CREATE INDEX IF NOT EXISTS idx_evidence_ingested ON evidence(ingested_ts);")
            c.execute("CREATE INDEX IF NOT EXISTS idx_evidence_source ON evidence(source);")
            conn.commit()

    def add_many(self, items: List[Dict[str, Any]], default_source: str = "") -> int:
        """批量写入证据。

        item 字段建议：
        - title/snippet/url/source/published_at
        - policy_strength/policy_sustain/demand_signal/substitution_signal
        - tags (dict/list)
        - trust (0~1)
        """
        if not items:
            return 0
        rows = []
        ts = _utc_ts()
        for it in items:
            tags = it.get("tags")
            tags_json = json.dumps(tags, ensure_ascii=False) if tags is not None else "{}"
            rows.append(
                (
                    ts,
                    str(it.get("published_at") or ""),
                    str(it.get("source") or default_source or ""),
                    str(it.get("title") or ""),
                    str(it.get("snippet") or it.get("content") or ""),
                    str(it.get("url") or ""),
                    tags_json,
                    float(it.get("policy_strength") or 0.0),
                    float(it.get("policy_sustain") or 0.0),
                    float(it.get("demand_signal") or 0.0),
                    float(it.get("substitution_signal") or 0.0),
                    float(it.get("trust") or 0.5),
                )
            )

        with sqlite3.connect(self.path) as conn:
            c = conn.cursor()
            c.executemany(
                """
                INSERT INTO evidence (
                    ingested_ts, published_at, source, title, snippet, url, tags_json,
                    policy_strength, policy_sustain, demand_signal, substitution_signal, trust
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?);
                """,
                rows,
            )
            conn.commit()
            return c.rowcount or len(rows)

    def query_recent(self, days: int = 30, limit: int = 500) -> List[Dict[str, Any]]:
        """查询近 N 天写入的证据。"""
        since_ts = _utc_ts() - int(days * 86400)
        with sqlite3.connect(self.path) as conn:
            conn.row_factory = sqlite3.Row
            c = conn.cursor()
            c.execute(
                """
                SELECT * FROM evidence
                WHERE ingested_ts >= ?
                ORDER BY ingested_ts DESC
                LIMIT ?;
                """,
                (since_ts, int(limit)),
            )
            out = []
            for r in c.fetchall():
                d = dict(r)
                try:
                    d["tags"] = json.loads(d.get("tags_json") or "{}")
                except Exception:
                    d["tags"] = {}
                d.pop("tags_json", None)
                out.append(d)
            return out

    def vacuum(self) -> None:
        with sqlite3.connect(self.path) as conn:
            conn.execute("VACUUM;")
            conn.commit()
