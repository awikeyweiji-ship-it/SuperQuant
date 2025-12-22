"""TuShare Pro financial provider."""
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


def fetch(ts_code: str, token: str, limit: int = 8) -> ProviderResult:
    errors: List[Dict[str, Any]] = []
    meta: Dict[str, Any] = {"source": "tushare", "retrieved_at": time.time(), "ts_code": ts_code}
    data: Dict[str, Any] = {}
    filled = 0
    try:
        pro = _get_pro(token)
        inc = pro.income(ts_code=ts_code, limit=limit)
        bal = pro.balancesheet(ts_code=ts_code, limit=limit)
        cash = pro.cashflow(ts_code=ts_code, limit=limit)
        indi = pro.fina_indicator(ts_code=ts_code, limit=limit)
        records: List[Dict[str, Any]] = []
        for idx in range(min(len(inc or []), limit)):
            try:
                inc_row = inc.iloc[idx] if inc is not None else None
            except Exception:
                inc_row = None
            record = {"period": None, "revenue": None, "profit": None, "roe": None, "gross_margin": None}
            if inc_row is not None:
                record["period"] = str(inc_row.get("end_date"))
                record["revenue"] = _safe_float(inc_row.get("total_revenue")) or _safe_float(inc_row.get("revenue"))
                record["profit"] = _safe_float(inc_row.get("n_income")) or _safe_float(inc_row.get("netprofit"))
            try:
                indi_row = indi.iloc[idx] if indi is not None else None
                if indi_row is not None:
                    record["roe"] = _safe_float(indi_row.get("roe"))
                    record["gross_margin"] = _safe_float(indi_row.get("grossprofit_margin"))
            except Exception:
                pass
            try:
                bal_row = bal.iloc[idx] if bal is not None else None
                if bal_row is not None:
                    record["assets"] = _safe_float(bal_row.get("total_assets"))
                    record["liabilities"] = _safe_float(bal_row.get("total_liab"))
            except Exception:
                pass
            try:
                cash_row = cash.iloc[idx] if cash is not None else None
                if cash_row is not None:
                    record["net_operate_cashflow"] = _safe_float(cash_row.get("n_cashflow_act"))
            except Exception:
                pass
            records.append(record)
        data["statements"] = records
        filled = len([r for r in records if any(v is not None for v in r.values())])
    except _MissingToken as exc:  # noqa: BLE001
        errors.append({"source": "tushare", "error_type": "token", "message": str(exc)})
    except Exception as exc:  # noqa: BLE001
        errors.append({"source": "tushare", "error_type": "exception", "message": str(exc)})
    meta["filled_metrics"] = filled if filled else 0
    meta["errors"] = errors
    return ProviderResult(data=data, filled_metrics=meta["filled_metrics"], errors=errors, meta=meta)


def _safe_float(val: Any):
    try:
        if val is None:
            return None
        return float(val)
    except Exception:
        return None
