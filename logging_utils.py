"""Shared logging utilities for data pipelines."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


def get_data_logger(name: str = "superquant.data", level: int = logging.INFO) -> logging.Logger:
    """Return a configured logger for data fetchers.

    Idempotent setup: only attaches handlers once and keeps propagation off
    so Streamlit or notebooks won't duplicate output.
    """
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] %(name)s - %(message)s")
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.propagate = False
    logger.setLevel(level)
    return logger


@dataclass
class FetchResult:
    """统一的数据获取返回结构，避免静默空白。"""

    data: Any
    ok: bool
    source: str = ""
    fallback_used: bool = False
    errors: List[Dict[str, str]] = field(default_factory=list)
    ts: float = field(default_factory=lambda: time.time())
    cache_hit: bool = False
    cache_age: Optional[float] = None
    meta: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        meta_dict: Dict[str, Any] = self.meta if isinstance(self.meta, dict) else {}
        return {
            "data": self.data,
            "ok": bool(self.ok),
            "source": self.source,
            "fallback_used": self.fallback_used,
            "errors": self.errors,
            "ts": self.ts,
            "cache_hit": self.cache_hit,
            "cache_age": self.cache_age,
            "meta": meta_dict,
        }


def build_error(source: str, error_type: str, message: str) -> Dict[str, str]:
    return {"source": source, "error_type": error_type, "message": str(message)}


def make_result(
    data: Any,
    source: str,
    fallback_used: bool = False,
    errors: Optional[List[Dict[str, str]]] = None,
    cache_hit: bool = False,
    cache_age: Optional[float] = None,
    meta: Optional[Dict[str, Any]] = None,
) -> FetchResult:
    ok = False
    if isinstance(data, dict):
        ok = bool(data)
    elif hasattr(data, "empty"):
        ok = not getattr(data, "empty")
    elif isinstance(data, (list, tuple)):
        ok = len(data) > 0
    else:
        ok = data is not None

    return FetchResult(
        data=data,
        ok=ok,
        source=source,
        fallback_used=fallback_used,
        errors=errors or [],
        cache_hit=cache_hit,
        cache_age=cache_age,
        meta=meta,
    )
