"""TuShare Pro announcements/news provider."""
from __future__ import annotations

import time
from typing import Any, Dict, List

from data_sources.provider_registry import ProviderResult


class _MissingToken(Exception):
    pass


def _get_pro(token: str):
    try:
        import tushare as ts  # type: ignore
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"tushare import failed: {exc}") from exc
    if not token:
        raise _MissingToken("TuShare token missing")
    return ts.pro_api(token)


def fetch(ts_code: str, token: str, limit: int = 30) -> ProviderResult:
    errors: List[Dict[str, Any]] = []
    meta: Dict[str, Any] = {"source": "tushare", "retrieved_at": time.time(), "ts_code": ts_code}
    data: Dict[str, Any] = {}
    filled = 0
    try:
        pro = _get_pro(token)
        anns = pro.anns(ts_code=ts_code, limit=limit)
        items: List[Dict[str, Any]] = []
        if anns is not None:
            for _, row in anns.iterrows():
                items.append(
                    {
                        "title": str(row.get("title")),
                        "date": str(row.get("ann_date")),
                        "url": row.get("url"),
                        "source": "tushare",
                    }
                )
        data["announcements"] = items
        filled = len(items)
    except _MissingToken as exc:  # noqa: BLE001
        errors.append({"source": "tushare", "error_type": "token", "message": str(exc)})
    except Exception as exc:  # noqa: BLE001
        errors.append({"source": "tushare", "error_type": "exception", "message": str(exc)})
    meta["filled_metrics"] = filled if filled else 0
    meta["errors"] = errors
    return ProviderResult(data=data, filled_metrics=meta["filled_metrics"], errors=errors, meta=meta)
