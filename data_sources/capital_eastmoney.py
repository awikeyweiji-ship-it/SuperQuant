"""东财资金与融资数据抓取（轻量版兜底）"""
from __future__ import annotations

import re
import time
import re
from typing import Dict, Any, Optional

import requests


def _standardize_code(code: str) -> str:
    code = str(code).strip()
    code = re.sub(r"\.(SH|SZ|BJ|sh|sz|bj)$", "", code)
    if code.isdigit() and len(code) < 6:
        code = code.zfill(6)
    market = "SH" if code.startswith("6") else "SZ"
    if code.startswith(("8", "4")):
        market = "BJ"
    return f"{code}.{market}"


def to_eastmoney_secid(code: str) -> str:
    code_std = _standardize_code(code)
    plain, market = code_std.split(".")
    market_flag = "1" if market == "SH" else "0"
    return f"{market_flag}.{plain}"


def _retry_get(url: str, params: Dict[str, Any], max_retries: int = 3, timeout: float = 10.0) -> Optional[Dict[str, Any]]:
    last_err: Optional[Exception] = None
    for i in range(max_retries):
        try:
            resp = requests.get(url, params=params, timeout=timeout)
            if resp.status_code == 200:
                return resp.json()
        except Exception as e:  # noqa: BLE001
            last_err = e
        time.sleep(0.6 * (2 ** i))
    if last_err:
        raise last_err
    return None


def fetch_capital_flow_em(code: str) -> Optional[Dict[str, Any]]:
    """获取个股资金流（主力/大单/北向等），不足字段由上层兜底。"""
    secid = to_eastmoney_secid(code)
    url = "https://push2.eastmoney.com/api/qt/stock/fflow/daykline/get"
    params = {
        "lmt": 1,
        "klt": 101,
        "fields1": "f1,f2,f3,f7",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "secid": secid,
    }
    data = _retry_get(url, params)
    klines = (((data or {}).get("data") or {}).get("klines"))
    if not klines:
        return None
    try:
        latest = klines[-1].split(",")
        # f51 日期, f52 主力净流入(万元), f53 小单, f54 中单, f55 大单, f56 超大单
        return {
            "report_date": latest[0],
            "main_net_inflow": float(latest[1]) * 1e4 if latest[1] not in ("", "--") else None,
            "small_net_inflow": float(latest[2]) * 1e4 if latest[2] not in ("", "--") else None,
            "medium_net_inflow": float(latest[3]) * 1e4 if latest[3] not in ("", "--") else None,
            "large_net_inflow": float(latest[4]) * 1e4 if latest[4] not in ("", "--") else None,
            "super_large_net_inflow": float(latest[5]) * 1e4 if latest[5] not in ("", "--") else None,
        }
    except Exception:
        return None


def fetch_margin_balance_em(code: str) -> Optional[Dict[str, Any]]:
    """东财融资融券余额（若不可用则返回 None）"""
    plain = _standardize_code(code).split(".")[0]
    url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
    params = {
        "reportName": "RPT_MARGINEM_DETAIL",
        "columns": "SECURITY_CODE,TRADE_DATE,RZYE,RQYL,RZMRE,RQYLJE",
        "pageNumber": 1,
        "pageSize": 1,
        "sortColumns": "TRADE_DATE",
        "sortTypes": "-1",
        "filter": f"(SECURITY_CODE=\"{plain}\")",
    }
    data = _retry_get(url, params)
    items = (((data or {}).get("result") or {}).get("data"))
    if not items:
        return None
    row = items[0]
    try:
        return {
            "margin_balance": float(row.get("RZYE", 0.0)),
            "short_balance": float(row.get("RQYLJE", 0.0)),
            "margin_date": row.get("TRADE_DATE"),
        }
    except Exception:
        return None


def fetch_northbound_market_em() -> Optional[Dict[str, Any]]:
    """获取北向资金市场级净流入（万元）。"""
    url = "https://push2.eastmoney.com/api/qt/kamt.rtmin/get"
    params = {
        "fields1": "f1,f2,f3,f7",
        "fields2": "f51,f52,f54",
    }
    data = _retry_get(url, params)
    items = (((data or {}).get("data") or {}).get("s2n"))
    if not items:
        return None
    try:
        latest = items[-1]
        # f52 北向净流入(亿元)
        val = latest.get("f52")
        return {"northbound_net_inflow": float(val) * 1e8 if val is not None else None}
    except Exception:
        return None
