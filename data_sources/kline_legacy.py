"""Legacy daily K-line provider wrapper (Tencent) for compatibility."""

from __future__ import annotations

from typing import Any, Dict

from data_sources.provider_registry import ProviderResult
from data_sources import kline_tencent_v2


def fetch(code: str, limit: int = 320, **_: Any) -> ProviderResult | Dict[str, Any]:
    res = kline_tencent_v2.fetch(code, freq="day", limit=limit)
    if isinstance(res, ProviderResult):
        meta = {"source": "kline_legacy", **(res.meta or {})}
        return ProviderResult(data=res.data, filled_metrics=meta.get("filled_metrics", res.filled_metrics), errors=res.errors, meta=meta)

    if isinstance(res, dict):
        meta = res.get("meta") or {}
        meta.setdefault("source", "kline_legacy")
        res["meta"] = meta
    return res

