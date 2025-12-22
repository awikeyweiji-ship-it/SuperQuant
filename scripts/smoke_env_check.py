"""Environment smoke to ensure backbone deps and network are ready."""
from __future__ import annotations

import json
import os
import sys
import time
from typing import Dict, Any

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _check_imports() -> Dict[str, Any]:
    status: Dict[str, Any] = {"baostock": False, "requests": False}
    try:
        import baostock as bs  # type: ignore

        status["baostock"] = bs is not None
    except Exception as exc:  # noqa: BLE001
        status["baostock_error"] = str(exc)
    try:
        import requests  # type: ignore

        status["requests"] = requests is not None
    except Exception as exc:  # noqa: BLE001
        status["requests_error"] = str(exc)
    return status


def _check_endpoint(name: str, url: str, timeout: float = 5.0) -> Dict[str, Any]:
    import requests

    meta = {"endpoint": name, "url": url, "ok": False, "status": None, "elapsed": None, "error": None}
    try:
        start = time.time()
        resp = requests.get(url, timeout=timeout)
        meta["elapsed"] = round(time.time() - start, 3)
        meta["status"] = resp.status_code
        meta["ok"] = resp.ok
    except Exception as exc:  # noqa: BLE001
        meta["error"] = str(exc)
    return meta


def main() -> int:
    results = {"imports": _check_imports()}
    checks = [
        ("sse", "https://www.sse.com.cn/disclosure/listedinfo/announcement/"),
        ("szse", "https://www.szse.cn/disclosure/index.html"),
        ("eastmoney", "https://data.eastmoney.com/"),
    ]
    results["network"] = [_check_endpoint(name, url) for name, url in checks]
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

