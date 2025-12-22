"""Legacy realtime quote provider wrapper for compatibility."""

from __future__ import annotations

from typing import Any, Dict

from data_sources.provider_registry import ProviderResult
from data_sources import quote_sina_live


def fetch(code: str, **_: Any) -> ProviderResult | Dict[str, Any]:
    """Fetch realtime quote using the first-version path (Sina live)."""

    res = quote_sina_live.fetch(code)
    if isinstance(res, ProviderResult):
        meta = {"source": "quote_legacy", **(res.meta or {})}
        return ProviderResult(data=res.data, filled_metrics=meta.get("filled_metrics", res.filled_metrics), errors=res.errors, meta=meta)

    if isinstance(res, dict):
        meta = res.get("meta") or {}
        meta.setdefault("source", "quote_legacy")
        res["meta"] = meta
    return res

