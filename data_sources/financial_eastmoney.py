"""东财财务摘要抓取（HTTP 版，带超时和免代理）。"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

import pandas as pd
import requests


def _safe_get(resp: requests.Response) -> Optional[Dict[str, Any]]:
    try:
        if resp.status_code != 200:
            return None
        return resp.json()
    except Exception:
        return None


def fetch_financial_indicator_em(code_std: str, timeout: float = 8.0) -> Optional[pd.DataFrame]:
    """从东财 indicator 接口获取财务摘要。

    返回 DataFrame，包含最近报告期的主要指标；网络失败时返回 None。
    """

    plain, market = code_std.split(".")
    market_flag = "1" if market == "SH" else "0"
    secid = f"{market_flag}.{plain}"
    url = "https://push2his.eastmoney.com/api/qt/stock/finace/indicator"
    fields = (
        "fdate,reportdate,basiceps,bps,weightedroe,roe_dt,roe_avg,grossprofit_margin,"
        "netprofit_margin,netprofit_yoy,roe,roa2_weighted,debtratio,ocfps,totaloperatereve,"
        "ystz,yshz,ylnl,netprofit,opincome,assetsturn,assets_yoy"
    )
    params = {
        "secid": secid,
        "fields": fields,
        "lmt": 5,
        "ut": "f057cbcbce2a86e2866ab8877db1d059",
    }

    try:
        resp = requests.get(url, params=params, timeout=timeout, proxies={"http": None, "https": None})
    except Exception:
        return None

    data = _safe_get(resp)
    if not data or "data" not in data:
        return None

    report_list = data.get("data", {}).get("reportdata") or []
    if not report_list:
        return None
    try:
        df = pd.DataFrame(report_list)
        return df
    except Exception:
        try:
            return pd.DataFrame(json.loads(report_list))  # type: ignore[arg-type]
        except Exception:
            return None

