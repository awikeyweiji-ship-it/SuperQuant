# -*- coding: utf-8 -*-

"""capital_engine.py
Step5: Capital/flow intelligence (optional)
- Provides extra money-flow and capital-operation features with graceful fallback.
"""

from __future__ import annotations

from typing import Any, Dict

try:
    import akshare as ak
except Exception:
    ak = None


def _safe_float(x, default=0.0) -> float:
    try:
        if x is None:
            return float(default)
        s = str(x).strip().replace(',', '').replace('%', '')
        if s in ('', '--', 'nan', 'None', 'NaN'):
            return float(default)
        return float(s)
    except Exception:
        return float(default)


class CapitalEngine:
    """Fetch capital-flow related features.

    Notes:
    - AkShare interfaces vary by version. This engine tries multiple function names
      and returns best-effort outputs, never raising to callers.
    """

    def __init__(self):
        pass

    def _try(self, fn_name: str, **kwargs):
        if ak is None:
            return None
        fn = getattr(ak, fn_name, None)
        if not callable(fn):
            return None
        try:
            return fn(**kwargs)
        except Exception:
            return None

    def get_capital_features(self, code: str) -> Dict[str, Any]:
        code = str(code).strip()
        out: Dict[str, Any] = {}

        # 1) Individual fund flow (best effort)
        for fn in (
            'stock_individual_fund_flow',
            'stock_individual_fund_flow_em',
            'stock_individual_fund_flow_rank',
        ):
            df = self._try(fn, symbol=code) or self._try(fn, stock=code)
            if df is None or getattr(df, 'empty', True):
                continue
            try:
                last = df.iloc[-1].to_dict()
                # common columns
                for k in ['主力净流入-净额', '主力净流入', '净流入', '主力净流入净额', 'main_net_inflow']:
                    if k in last:
                        out['main_net_inflow_detail'] = _safe_float(last.get(k))
                        break
            except Exception:
                pass
            break

        # 2) Northbound summary (market-level)
        for fn in (
            'stock_hsgt_fund_flow_summary_em',
            'stock_hsgt_fund_flow_summary',
        ):
            df = self._try(fn)
            if df is None or getattr(df, 'empty', True):
                continue
            try:
                # try find total net flow
                row0 = df.iloc[0].to_dict()
                for k in ['当日资金流入', '当日资金净流入', '净流入', '资金净流入']:
                    if k in row0:
                        out['northbound_net_inflow'] = _safe_float(row0.get(k))
                        break
            except Exception:
                pass
            break

        return out
