# -*- coding: utf-8 -*-
"""
universe_cache.py
=================
轻量、可商用的本地缓存层（文件缓存 + 内存缓存），专门解决 Streamlit 反复 rerun 导致的“重复跑 802”的问题。

- DataFrame 优先用 parquet（更快更小），若环境没有 pyarrow/fastparquet，会自动回退到 pickle。
"""

from __future__ import annotations

import os
import json
import time
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import pandas as pd

_DEFAULT_DIR = Path(os.getenv("SUPERQUANT_CACHE_DIR", ".superquant_cache")).resolve()
_DEFAULT_DIR.mkdir(parents=True, exist_ok=True)


def _now() -> float:
    return time.time()


def _sha1(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()


def _safe_json_dumps(obj: Any) -> str:
    try:
        return json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str)
    except Exception:
        return str(obj)


@dataclass
class CacheItem:
    value: Any
    ts: float


class UniverseCache:
    def __init__(self, cache_dir: Path = _DEFAULT_DIR):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._mem: dict[str, CacheItem] = {}

    def key(self, namespace: str, payload: Any) -> str:
        raw = f"{namespace}:{_safe_json_dumps(payload)}"
        return f"{namespace}_{_sha1(raw)}"

    def _meta_path(self, key: str) -> Path:
        return self.cache_dir / f"{key}.meta.json"

    def _pkl_path(self, key: str) -> Path:
        return self.cache_dir / f"{key}.pkl"

    def _parquet_path(self, key: str) -> Path:
        return self.cache_dir / f"{key}.parquet"

    # --------------------------- Generic Get/Set ---------------------------

    def get(self, key: str, ttl: Optional[int] = None) -> Any:
        item = self._mem.get(key)
        if item is not None:
            if ttl is None or (_now() - item.ts) <= ttl:
                return item.value

        meta_path = self._meta_path(key)
        data_path = self._pkl_path(key)
        if meta_path.exists() and data_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                ts = float(meta.get("ts", 0))
                if ttl is not None and (_now() - ts) > ttl:
                    return None
                value = pd.read_pickle(data_path)
                self._mem[key] = CacheItem(value=value, ts=ts)
                return value
            except Exception:
                return None
        return None

    def set(self, key: str, value: Any) -> None:
        ts = _now()
        self._mem[key] = CacheItem(value=value, ts=ts)
        try:
            pd.to_pickle(value, self._pkl_path(key))
            self._meta_path(key).write_text(json.dumps({"ts": ts}, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass

    # --------------------------- DataFrame Helpers ---------------------------

    def get_df(self, key: str, ttl: Optional[int] = None) -> Optional[pd.DataFrame]:
        item = self._mem.get(key)
        if item is not None and isinstance(item.value, pd.DataFrame):
            if ttl is None or (_now() - item.ts) <= ttl:
                return item.value

        meta_path = self._meta_path(key)
        pq_path = self._parquet_path(key)
        pkl_path = self._pkl_path(key)

        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                ts = float(meta.get("ts", 0))
                if ttl is not None and (_now() - ts) > ttl:
                    return None

                if pq_path.exists():
                    try:
                        df = pd.read_parquet(pq_path)
                        self._mem[key] = CacheItem(value=df, ts=ts)
                        return df
                    except Exception:
                        pass

                if pkl_path.exists():
                    try:
                        df = pd.read_pickle(pkl_path)
                        if isinstance(df, pd.DataFrame):
                            self._mem[key] = CacheItem(value=df, ts=ts)
                            return df
                    except Exception:
                        return None
            except Exception:
                return None

        return None

    def set_df(self, key: str, df: pd.DataFrame) -> None:
        ts = _now()
        self._mem[key] = CacheItem(value=df, ts=ts)

        try:
            df.to_parquet(self._parquet_path(key), index=False)
            self._meta_path(key).write_text(json.dumps({"ts": ts}, ensure_ascii=False), encoding="utf-8")
            return
        except Exception:
            pass

        try:
            df.to_pickle(self._pkl_path(key))
            self._meta_path(key).write_text(json.dumps({"ts": ts}, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass

    # --------------------------- Convenience ---------------------------

    def get_spot_snapshot(self, ttl_seconds: int = 180) -> Optional[pd.DataFrame]:
        return self.get_df("spot_snapshot", ttl=ttl_seconds)

    def set_spot_snapshot(self, df: pd.DataFrame) -> None:
        self.set_df("spot_snapshot", df)

    def get_pool(self, pool_id: str, ttl_seconds: int = 24 * 3600) -> Optional[list[str]]:
        key = self.key("pool", {"pool_id": pool_id})
        return self.get(key, ttl=ttl_seconds)

    def set_pool(self, pool_id: str, codes: list[str]) -> None:
        key = self.key("pool", {"pool_id": pool_id})
        self.set(key, codes)

    def get_scan(self, scan_id: str, ttl_seconds: int = 600) -> Optional[pd.DataFrame]:
        key = self.key("scan", {"scan_id": scan_id})
        return self.get_df(key, ttl=ttl_seconds)

    def set_scan(self, scan_id: str, df: pd.DataFrame) -> None:
        key = self.key("scan", {"scan_id": scan_id})
        self.set_df(key, df)
