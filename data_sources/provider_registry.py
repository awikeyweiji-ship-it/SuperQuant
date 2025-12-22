"""Provider registry with concurrency fan-out for SuperQuant."""
from __future__ import annotations

import concurrent.futures
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

ProviderFunc = Callable[..., "ProviderResult | Dict[str, Any]"]


@dataclass
class ProviderResult:
    """Standardized provider output used for provider arbitration."""

    data: Dict[str, Any]
    filled_metrics: int
    errors: List[Dict[str, Any]]
    meta: Dict[str, Any] = field(default_factory=dict)

    def to_payload(self, default_source: str) -> Dict[str, Any]:
        meta = {"source": default_source, "retrieved_at": time.time(), **(self.meta or {})}
        meta.setdefault("errors", self.errors or [])
        meta.setdefault("filled_metrics", self.filled_metrics or 0)
        meta.setdefault("errors_count", len(meta.get("errors") or []))
        return {"data": self.data or {}, "meta": meta}


@dataclass(order=True)
class ProviderEntry:
    priority: int
    name: str = field(compare=False)
    func: ProviderFunc = field(compare=False)


class ProviderRegistry:
    def __init__(self) -> None:
        self._providers: Dict[str, List[ProviderEntry]] = {}

    def register(self, domain: str, name: str, func: ProviderFunc, priority: int = 0) -> None:
        entries = self._providers.setdefault(domain, [])
        entries.append(ProviderEntry(priority=int(priority), name=name, func=func))
        entries.sort(key=lambda e: e.priority, reverse=True)

    def get_providers(self, domain: str) -> List[ProviderEntry]:
        return list(self._providers.get(domain, []))


def _normalize_payload(raw: Any, default_source: str) -> Dict[str, Any]:
    if isinstance(raw, ProviderResult):
        return raw.to_payload(default_source)
    if isinstance(raw, dict):
        meta = raw.get("meta") or {}
        meta.setdefault("source", default_source)
        meta.setdefault("retrieved_at", time.time())
        meta.setdefault("errors", meta.get("errors") or [])
        meta.setdefault("filled_metrics", meta.get("filled_metrics") or 0)
        meta.setdefault("errors_count", len(meta.get("errors") or []))
        raw["meta"] = meta
        raw.setdefault("data", {})
        return raw
    return {"data": {}, "meta": {"source": default_source, "retrieved_at": time.time(), "errors": [], "filled_metrics": 0}}


def run_providers_parallel(
    providers: List[ProviderEntry],
    symbol: str,
    timeout: float = 8.0,
    retries: int = 0,
    identity: Optional[Dict[str, Any]] = None,
    **kwargs: Any,
) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]]]:
    """Execute providers in parallel and pick the best result.

    The selection prefers higher ``filled_metrics`` then fewer errors, then latest
    ``retrieved_at``, and finally provider priority order.
    """
    if not providers:
        return None, []

    traces: List[Dict[str, Any]] = []
    results: List[Tuple[ProviderEntry, Dict[str, Any]]] = []

    def _invoke(entry: ProviderEntry):
        last_exc: Optional[BaseException] = None
        start = time.time()
        for attempt in range(max(1, retries + 1)):
            try:
                payload = entry.func(symbol, **kwargs)
                return payload, time.time() - start
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                if attempt < retries:
                    time.sleep(0.2 * (attempt + 1))
        if last_exc:
            raise last_exc
        raise RuntimeError("provider invocation failed")

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(providers)) as executor:
        future_map = {executor.submit(_invoke, p): p for p in providers}
        start_wait = time.time()
        try:
            for future in concurrent.futures.as_completed(future_map, timeout=timeout):
                entry = future_map[future]
                try:
                    remaining = max(0.1, timeout - (time.time() - start_wait))
                    payload, elapsed = future.result(timeout=remaining)
                    payload = _normalize_payload(payload, entry.name)
                    meta = payload.get("meta") or {}
                    meta.setdefault("elapsed", meta.get("elapsed") or meta.get("duration") or elapsed)
                    if identity:
                        meta.setdefault("used_key", identity)
                    traces.append(
                        {
                            "provider": entry.name,
                            "success": True,
                            "elapsed": meta.get("elapsed"),
                            "errors": meta.get("errors", []),
                            "url": meta.get("url"),
                            "status_code": meta.get("status_code"),
                            "body_snippet": meta.get("body_snippet"),
                            "filled_metrics": meta.get("filled_metrics", 0),
                            "errors_count": meta.get("errors_count", len(meta.get("errors") or [])),
                        }
                    )
                    results.append((entry, payload))
                except Exception as exc:  # noqa: BLE001
                    traces.append({
                        "provider": entry.name,
                        "success": False,
                        "elapsed": None,
                        "errors": [{"source": entry.name, "error_type": "exception", "message": str(exc)}],
                        "errors_count": 1,
                        "filled_metrics": 0,
                    })
        except concurrent.futures.TimeoutError:
            for fut, entry in future_map.items():
                if fut.done():
                    continue
                traces.append({
                    "provider": entry.name,
                    "success": False,
                    "elapsed": timeout,
                    "errors": [{"source": entry.name, "error_type": "timeout", "message": f">={timeout}s"}],
                    "errors_count": 1,
                    "filled_metrics": 0,
                })

    if not results:
        return None, traces

    def _score(item: Tuple[ProviderEntry, Dict[str, Any]]):
        entry, payload = item
        meta = payload.get("meta") or {}
        filled = meta.get("filled_metrics") or 0
        err_cnt = len(meta.get("errors") or [])
        ts_raw = meta.get("retrieved_at") or meta.get("ts") or 0
        try:
            ts = float(ts_raw)
        except Exception:
            ts = 0
        return (filled, -err_cnt, entry.priority, ts)

    sorted_results = sorted(results, key=_score, reverse=True)
    best_entry, best_payload = sorted_results[0]
    # rule: do not pick filled_metrics=0 if any provider has >0
    if (best_payload.get("meta") or {}).get("filled_metrics", 0) == 0:
        for entry, payload in sorted_results:
            if (payload.get("meta") or {}).get("filled_metrics", 0) > 0:
                best_entry, best_payload = entry, payload
                break
    meta = best_payload.get("meta") or {}
    meta.setdefault("source", best_entry.name)
    meta.setdefault("retrieved_at", time.time())
    if identity:
        meta.setdefault("used_key", identity)
    best_payload["meta"] = meta
    return best_payload, traces
