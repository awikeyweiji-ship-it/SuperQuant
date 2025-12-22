"""Quick connectivity doctor for key providers."""
from __future__ import annotations

import json
import os
import sys
from typing import List, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from data_sources import quote_sina_live, quote_tencent_live, kline_tencent_v2, news_sina_stock

PROVIDERS = {
    "quote_sina": quote_sina_live.fetch,
    "quote_tencent": quote_tencent_live.fetch,
    "kline_tencent": kline_tencent_v2.fetch,
    "news_sina_stock": news_sina_stock.fetch,
}

def run(code: str) -> List[Tuple[str, dict]]:
    results = []
    for name, func in PROVIDERS.items():
        try:
            payload = func(code)
            payload_dict = payload.to_payload(name)
            meta = payload_dict.get("meta", {})
            data = payload_dict.get("data", {})
            parsed_ok = bool(meta.get("filled_metrics", 0))
            print(json.dumps({
                "provider_name": name,
                "url": meta.get("url"),
                "status_code": meta.get("status_code"),
                "filled_metrics": meta.get("filled_metrics"),
                "parsed_ok": parsed_ok,
                "body_snippet": (meta.get("body_snippet") or "")[:120],
                "errors": meta.get("errors", []),
                "data_preview": str(data)[:120],
            }, ensure_ascii=False))
            results.append((name, payload_dict))
        except Exception as exc:  # noqa: BLE001
            print(json.dumps({"provider_name": name, "error": str(exc)}))
    return results


def main() -> int:
    code = sys.argv[1] if len(sys.argv) > 1 else "600519"
    run(code)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
