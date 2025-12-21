"""Provider registry with concurrency fan-out for SuperQuant."""
from __future__ import annotations

import concurrent.futures
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

ProviderFunc = Callable[[str], Dict[str, Any]]


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
        entries.append(ProviderEntry(priority=-int(priority), name=name, func=func))
        entries.sort()  # dataclass order uses priority first (negative for higher priority)

    def get_providers(self, domain: str) -> List[ProviderEntry]:
        return list(self._providers.get(domain, []))


def run_providers_parallel(
    providers: List[ProviderEntry],
    symbol: str,
    timeout: float = 8.0,
) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]]]:
    """Execute providers in parallel and pick the best result.

    The selection prefers higher ``filled_metrics`` then fewer errors, then latest
    ``retrieved_at``, and finally provider priority order.
    """
    if not providers:
        return None, []

    traces: List[Dict[str, Any]] = []
    results: List[Tuple[ProviderEntry, Dict[str, Any]]] = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(providers)) as executor:
        future_map = {executor.submit(p.func, symbol): p for p in providers}
        try:
            for future in concurrent.futures.as_completed(future_map, timeout=timeout):
                entry = future_map[future]
                start = time.time()
                try:
                    payload = future.result(timeout=max(0.1, timeout - (time.time() - start)))
                    payload = payload or {}
                    meta = payload.get("meta") or {}
                    meta.setdefault("source", entry.name)
                    meta.setdefault("retrieved_at", time.time())
                    meta.setdefault("errors", [])
                    meta.setdefault("filled_metrics", 0)
                    traces.append(
                        {
                            "provider": entry.name,
                            "success": True,
                            "elapsed": meta.get("elapsed") or meta.get("duration") or (time.time() - meta.get("retrieved_at", time.time())),
                            "errors": meta.get("errors", []),
                            "filled_metrics": meta.get("filled_metrics", 0),
                        }
                    )
                    results.append((entry, payload))
                except Exception as exc:  # noqa: BLE001
                    traces.append({
                        "provider": entry.name,
                        "success": False,
                        "elapsed": None,
                        "errors": [{"source": entry.name, "error_type": "exception", "message": str(exc)}],
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
                    "filled_metrics": 0,
                })

    if not results:
        return None, traces

    def _score(item: Tuple[ProviderEntry, Dict[str, Any]]):
        entry, payload = item
        meta = payload.get("meta") or {}
        filled = meta.get("filled_metrics") or 0
        err_cnt = len(meta.get("errors") or [])
        ts = meta.get("retrieved_at") or 0
        return (filled, -err_cnt, ts, entry.priority)

    best_entry, best_payload = sorted(results, key=_score, reverse=True)[0]
    meta = best_payload.get("meta") or {}
    meta.setdefault("source", best_entry.name)
    meta.setdefault("retrieved_at", time.time())
    best_payload["meta"] = meta
    return best_payload, traces
