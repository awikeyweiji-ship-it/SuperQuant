"""Offline sample payloads used as a last-resort fallback when all providers fail.

The samples are deterministic and lightweight so they can be safely bundled with
the repository to keep smoke tests running in restricted environments (e.g.
proxied sandboxes that block real-time data APIs). These values are derived from
public historical ranges but are **not** intended for trading decisions.
"""

from __future__ import annotations

import datetime as _dt
from typing import Any, Dict, List


def _gen_kline(base_price: float, days: int = 200, start: _dt.date | None = None) -> List[Dict[str, Any]]:
    start_date = start or _dt.date(2024, 1, 2)
    series: List[Dict[str, Any]] = []
    price = base_price
    for i in range(days):
        day = start_date + _dt.timedelta(days=i)
        open_px = price + 0.1 * (i % 7)
        close_px = open_px + ((-1) ** i) * (0.2 + 0.03 * (i % 5))
        high_px = max(open_px, close_px) + 0.15
        low_px = min(open_px, close_px) - 0.15
        volume = 1e5 + i * 150
        series.append(
            {
                "date": day.isoformat(),
                "open": round(open_px, 2),
                "close": round(close_px, 2),
                "high": round(high_px, 2),
                "low": round(low_px, 2),
                "volume": round(volume, 2),
            }
        )
        price = close_px
    return series


_SAMPLE_SERIES = {
    "000801": _gen_kline(8.2),
    "600519": _gen_kline(1550.0),
}


_SAMPLE_FINANCIAL = {
    "000801": {
        "period": "2024-09-30",
        "revenue": 125.4,
        "net_profit": 8.6,
        "roe": 6.8,
        "rev_yoy": 9.7,
        "profit_yoy": 11.2,
        "eps": 0.35,
        "gross_margin": 21.3,
        "net_margin": 6.9,
        "ocf": 10.2,
    },
    "600519": {
        "period": "2024-09-30",
        "revenue": 980.5,
        "net_profit": 486.2,
        "roe": 30.1,
        "rev_yoy": 15.4,
        "profit_yoy": 17.9,
        "eps": 38.6,
        "gross_margin": 91.5,
        "net_margin": 49.6,
        "ocf": 510.3,
    },
}


_SAMPLE_ANNOUNCEMENTS = {
    "000801": [
        {
            "title": "2024年三季报摘要",
            "publish_time": "2024-10-20 08:30:00",
            "source_url": "https://example.com/000801/q3",
            "source": "offline_sample",
            "code": "000801",
        }
    ],
    "600519": [
        {
            "title": "贵州茅台关于分红实施的公告",
            "publish_time": "2024-07-01 09:00:00",
            "source_url": "https://example.com/600519/dividend",
            "source": "offline_sample",
            "code": "600519",
        }
    ],
}


def sample_kline(code: str) -> List[Dict[str, Any]]:
    return list(_SAMPLE_SERIES.get(code, []))


def sample_financial(code: str) -> Dict[str, Any]:
    return dict(_SAMPLE_FINANCIAL.get(code, {}))


def sample_announcements(code: str) -> List[Dict[str, Any]]:
    return list(_SAMPLE_ANNOUNCEMENTS.get(code, []))


def sample_price(code: str) -> float | None:
    series = _SAMPLE_SERIES.get(code)
    if not series:
        return None
    last = series[-1]
    try:
        return float(last.get("close")) if last.get("close") is not None else None
    except Exception:
        return None
