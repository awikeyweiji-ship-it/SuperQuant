"""Financial indicator provider using Eastmoney datacenter with AkShare fallback."""
from __future__ import annotations

import re
import time
from typing import Any, Dict, List, Optional

import akshare as ak
import requests


def _standardize(code: str) -> str:
    code = str(code).strip()
    code = re.sub(r"\.(SH|SZ|BJ|sh|sz|bj)$", "", code)
    if code.isdigit() and len(code) < 6:
        code = code.zfill(6)
    market = "SZ"
    if code.startswith("6"):
        market = "SH"
    elif code.startswith(("8", "4")):
        market = "BJ"
    return f"{code}.{market}"


def _to_float(val: Any) -> Optional[float]:
    if val in (None, "", "--"):
        return None
    try:
        return float(val)
    except Exception:
        try:
            return float(str(val).replace("%", ""))
        except Exception:
            return None


def _count(data: Dict[str, Any]) -> int:
    return sum(1 for v in data.values() if v not in (None, "", "--"))


def _fetch_from_datacenter(code_std: str) -> Dict[str, Any]:
    url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
    params = {
        "reportName": "RPT_LICO_FN_CPD",
        "columns": "REPORT_DATE,OR_YOY,NP_YOY,GROSSMARGIN,AVG_ROE,PE_TTM,PB",
        "filter": f'(SECUCODE="{code_std}")',
        "pageNumber": 1,
        "pageSize": 1,
        "sortColumns": "REPORT_DATE",
        "sortTypes": "-1",
        "source": "WEB",
        "client": "WEB",
    }
    errors: List[Dict[str, str]] = []
    try:
        resp = requests.get(url, params=params, timeout=8)
        payload = resp.json() or {}
    except Exception as exc:  # noqa: BLE001
        errors.append({"source": "financial_eastmoney", "error_type": "exception", "message": str(exc)})
        return {"data": {}, "errors": errors}

    try:
        data_rows = payload.get("result", {}).get("data") if isinstance(payload, dict) else []
        if not isinstance(data_rows, list) or not data_rows:
            errors.append({"source": "financial_eastmoney", "error_type": "empty", "message": "no datacenter rows"})
            return {"data": {}, "errors": errors}
        row = data_rows[0] if isinstance(data_rows[0], dict) else {}
        parsed = {
            "pe_ttm": _to_float((row or {}).get("PE_TTM")),
            "pb": _to_float((row or {}).get("PB")),
            "roe": _to_float((row or {}).get("AVG_ROE")),
            "revenue_yoy": _to_float((row or {}).get("OR_YOY")),
            "profit_yoy": _to_float((row or {}).get("NP_YOY")),
            "gross_margin": _to_float((row or {}).get("GROSSMARGIN")),
            "report_period": (row or {}).get("REPORT_DATE"),
        }
        return {"data": parsed, "errors": errors}
    except Exception as exc:  # noqa: BLE001
        errors.append({"source": "financial_eastmoney", "error_type": "invalid", "message": str(exc)})
        return {"data": {}, "errors": errors}


def _akshare_indicator(code_std: str) -> Dict[str, Any]:
    symbol_plain = code_std.split(".")[0]
    df = ak.stock_financial_analysis_indicator(symbol=symbol_plain)
    if df is None or df.empty:
        return {}
    row = df.iloc[0].to_dict()
    mapping = {
        "pe_ttm": row.get("市盈率(TTM)"),
        "pb": row.get("市净率"),
        "roe": row.get("净资产收益率(加权)(%)"),
        "revenue_yoy": row.get("营业总收入同比增长率(%)"),
        "profit_yoy": row.get("归母净利润同比增长率(%)"),
        "gross_margin": row.get("销售毛利率(%)"),
        "report_period": row.get("报告期"),
    }
    return {k: _to_float(v) if k != "report_period" else v for k, v in mapping.items()}


def fetch(symbol: str, **_: Any) -> Dict[str, Any]:
    code_std = _standardize(symbol)
    meta = {
        "source": "financial_eastmoney",
        "retrieved_at": time.time(),
        "errors": [],
        "fallback_used": False,
        "cache_hit": False,
        "filled_metrics": 0,
    }

    data: Dict[str, Any] = {}
    dc_payload = _fetch_from_datacenter(code_std)
    dc_data = dc_payload.get("data", {}) if isinstance(dc_payload, dict) else {}
    meta["errors"].extend(dc_payload.get("errors", []) if isinstance(dc_payload, dict) else [])

    if isinstance(dc_data, dict) and any(v not in (None, "", "--") for v in dc_data.values()):
        data.update(dc_data)

    try:
        ak_data = _akshare_indicator(code_std)
        if isinstance(ak_data, dict):
            for key, val in ak_data.items():
                if data.get(key) in (None, "", "--") and val not in (None, "", "--"):
                    data[key] = val
            if not data:
                data = ak_data
            if ak_data:
                meta["fallback_used"] = meta["fallback_used"] or not dc_data
                meta["source"] = "financial_akshare"
    except Exception as exc:  # noqa: BLE001
        meta["errors"].append({"source": "financial_akshare", "error_type": "exception", "message": str(exc)})

    meta["report_period"] = data.get("report_period")
    meta["filled_metrics"] = _count({k: v for k, v in data.items() if k != "report_period"})
    if meta["filled_metrics"] == 0:
        meta["errors"].append({"source": meta["source"], "error_type": "empty", "message": "no data"})

    return {"data": data, "meta": meta}
