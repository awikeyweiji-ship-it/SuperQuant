from __future__ import annotations
import time
from typing import Dict, Any
import requests
from data_sources.identity import canonical_identity
from logging_utils import build_error


FIELDS_MAP = {
    "TOTAL_OPERATE_INCOME": "revenue",
    "PARENT_NETPROFIT": "profit",
    "ROEWEIGHTED": "roe",
    "GROSSMARGIN": "gross_margin",
}

def fetch(code: str) -> Dict[str, Any]:
    ident = canonical_identity(code)
    symbol = ident.symbol
    url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
    params = {
        "reportName": "RPT_F10_FINANCE_MAIN_SUMMARY",
        "columns": ",".join(FIELDS_MAP.keys()) + ",REPORT_DATE",
        "filter": f"(SECUCODE=\"{symbol}\")",
        "pageNumber": 1,
        "pageSize": 5,
    }
    errors = []
    data: Dict[str, Any] = {}
    try:
        resp = requests.get(url, params=params, timeout=8)
        if resp.status_code != 200:
            errors.append(build_error("financial_em_basic", "http_error", f"status {resp.status_code}"))
        else:
            js = resp.json()
            records = (js.get("result") or {}).get("data") if isinstance(js, dict) else None
            if isinstance(records, list) and records:
                rec = records[0]
                for k, out in FIELDS_MAP.items():
                    val = rec.get(k)
                    data[out] = _to_float(val)
                data["report_period"] = rec.get("REPORT_DATE")
            else:
                errors.append(build_error("financial_em_basic", "empty", "no finance rows"))
    except Exception as exc:  # noqa: BLE001
        errors.append(build_error("financial_em_basic", "exception", str(exc)))
    filled = sum(1 for v in data.values() if v not in (None, "", "--"))
    meta = {
        "source": "financial_em_basic",
        "retrieved_at": time.time(),
        "errors": errors,
        "filled_metrics": filled,
        "url": url,
        "used_key": symbol,
    }
    return {"data": data, "meta": meta}

def _to_float(v: Any):
    try:
        if v in (None, "", "--", "—"):
            return None
        return float(v)
    except Exception:
        return None
