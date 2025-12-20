# -*- coding: utf-8 -*-
"""paper_portfolio.py

Step5: 模拟仓（沙盘）

- 周/月再平衡
- 等权建仓 TopK
- 止损/止盈
- 输出：净值曲线、交易记录、期末持仓、关键指标

候选池来自：天网雷达/定向爆破后的建仓清单。

⚠️ 本模块仅用于策略验证与沙盘推演，不构成任何投资建议。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import pandas as pd


def _ymd(date_str: str) -> str:
    """YYYY-MM-DD -> YYYYMMDD"""
    s = (date_str or "").strip()
    if not s:
        return ""
    if "-" in s:
        parts = s.split("-")
        if len(parts) >= 3:
            return f"{parts[0]}{parts[1].zfill(2)}{parts[2].zfill(2)}"
    if len(s) == 8 and s.isdigit():
        return s
    return s


def _safe_float(x: Any, default: float = 0.0) -> float:
    try:
        if x is None:
            return float(default)
        return float(x)
    except Exception:
        return float(default)


def _max_drawdown(equity: pd.Series) -> float:
    if equity is None or len(equity) == 0:
        return 0.0
    running_max = equity.cummax()
    dd = (equity / running_max - 1.0).min()
    return float(abs(dd))


@dataclass
class Position:
    code: str
    shares: float
    entry_price: float
    entry_date: str

    def market_value(self, price: float) -> float:
        return float(self.shares) * float(price)


def _pick_rebalance_dates(dates: pd.DatetimeIndex, rebalance: str) -> List[pd.Timestamp]:
    if len(dates) == 0:
        return []
    rebalance = (rebalance or "W").upper().strip()
    if rebalance not in {"W", "M"}:
        rebalance = "W"
    # take the first trading day of each week/month
    s = pd.Series(1, index=dates)
    if rebalance == "W":
        grp = s.groupby([dates.year, dates.isocalendar().week]).sum()
        keys = grp.index
        out = []
        for y, w in keys:
            mask = (dates.year == y) & (dates.isocalendar().week == w)
            out.append(dates[mask][0])
        return out
    # M
    grp = s.groupby([dates.year, dates.month]).sum()
    keys = grp.index
    out = []
    for y, m in keys:
        mask = (dates.year == y) & (dates.month == m)
        out.append(dates[mask][0])
    return out


def _score_by_momentum(df: pd.DataFrame, lookback: int = 20) -> float:
    """Simple backtestable score: momentum - volatility."""
    if df is None or df.empty or "close" not in df.columns:
        return -1e9
    closes = pd.to_numeric(df["close"], errors="coerce").dropna()
    if len(closes) < max(lookback + 2, 10):
        return -1e9
    mom = float(closes.iloc[-1] / closes.iloc[-1 - lookback] - 1.0)
    rets = closes.pct_change().dropna()
    vol = float(rets.tail(lookback).std()) if len(rets) else 0.0
    # avoid extreme
    return float(mom - 0.8 * vol)


def simulate_paper_portfolio(
    engine,
    candidates: List[str],
    start: str,
    end: str,
    top_k: int = 10,
    rebalance: str = "W",
    initial_cash: float = 1_000_000.0,
    stop_loss: float = 0.08,
    take_profit: float = 0.25,
    fee: float = 0.001,
    lookback: int = 20,
) -> Dict[str, Any]:
    """Run a paper portfolio simulation.

    Returns dict:
    {
      ok: bool,
      msg: str,
      metrics: {...},
      equity_curve: DataFrame(date,equity,cash,holdings),
      trades: DataFrame(...),
      positions: [ {code, shares, price, value, weight, entry_price, entry_date} ]
    }
    """

    try:
        candidates = [str(x).strip() for x in (candidates or []) if str(x).strip()]
        candidates = list(dict.fromkeys(candidates))
        if len(candidates) < 2:
            return {"ok": False, "msg": "候选池至少需要2只股票", "metrics": {}}

        start_ymd = _ymd(start)
        end_ymd = _ymd(end)
        if not start_ymd or not end_ymd:
            return {"ok": False, "msg": "开始/结束日期不合法", "metrics": {}}

        # --------
        # Load price data
        # --------
        price_map: Dict[str, pd.DataFrame] = {}
        all_dates: Optional[pd.DatetimeIndex] = None
        for code in candidates:
            try:
                df = engine.get_kline(code, freq="daily", start_date=start_ymd, end_date=end_ymd, limit=None)
            except TypeError:
                # backward compat
                df = engine.get_kline(code, freq="daily", limit=9999)
                if not df.empty and "date" in df.columns:
                    df = df[(df["date"] >= start) & (df["date"] <= end)].copy()
            except Exception:
                df = pd.DataFrame()
            if df is None or df.empty:
                continue
            # normalize
            if "date" in df.columns:
                df["date"] = pd.to_datetime(df["date"])
                df = df.sort_values("date")
                df = df[(df["date"] >= pd.to_datetime(start)) & (df["date"] <= pd.to_datetime(end))]
                df = df.reset_index(drop=True)
            if df.empty:
                continue
            price_map[code] = df
            di = pd.to_datetime(df["date"]).dt.normalize().unique()
            idx = pd.DatetimeIndex(di).sort_values()
            all_dates = idx if all_dates is None else all_dates.union(idx)

        if not price_map or all_dates is None or len(all_dates) < 10:
            return {"ok": False, "msg": "拉取历史K线失败（候选池无足够数据）", "metrics": {}}

        all_dates = all_dates[(all_dates >= pd.to_datetime(start)) & (all_dates <= pd.to_datetime(end))]
        if len(all_dates) < 10:
            return {"ok": False, "msg": "日期区间内交易日不足", "metrics": {}}

        # --------
        # Simulation loop
        # --------
        cash = float(initial_cash)
        positions: Dict[str, Position] = {}
        trade_rows: List[Dict[str, Any]] = []
        curve_rows: List[Dict[str, Any]] = []

        reb_dates = _pick_rebalance_dates(all_dates, rebalance)
        reb_set = set(pd.to_datetime(reb_dates).dt.normalize())

        def _last_close(code: str, dt: pd.Timestamp) -> Optional[float]:
            df = price_map.get(code)
            if df is None or df.empty:
                return None
            # find row with date == dt
            sub = df[df["date"].dt.normalize() == dt]
            if sub.empty:
                # fallback: last available before dt
                sub = df[df["date"] <= dt]
                if sub.empty:
                    return None
                return _safe_float(sub.iloc[-1].get("close"), None)
            return _safe_float(sub.iloc[-1].get("close"), None)

        def _slice_until(code: str, dt: pd.Timestamp) -> pd.DataFrame:
            df = price_map.get(code)
            if df is None or df.empty:
                return pd.DataFrame()
            return df[df["date"] <= dt].copy()

        for dt in all_dates:
            dt = pd.to_datetime(dt).normalize()

            # 1) check stop-loss / take-profit exits (at close)
            to_close = []
            for code, pos in positions.items():
                px = _last_close(code, dt)
                if px is None:
                    continue
                if px <= pos.entry_price * (1.0 - float(stop_loss)):
                    to_close.append((code, px, "STOP_LOSS"))
                elif px >= pos.entry_price * (1.0 + float(take_profit)):
                    to_close.append((code, px, "TAKE_PROFIT"))

            for code, px, reason in to_close:
                pos = positions.get(code)
                if not pos:
                    continue
                proceeds = pos.shares * px
                cost = proceeds * float(fee)
                cash += (proceeds - cost)
                trade_rows.append({
                    "date": dt.strftime("%Y-%m-%d"),
                    "code": code,
                    "side": "SELL",
                    "price": float(px),
                    "shares": float(pos.shares),
                    "value": float(proceeds),
                    "fee": float(cost),
                    "reason": reason,
                })
                del positions[code]

            # 2) rebalance
            if dt in reb_set:
                # score candidates using trailing window up to dt
                scored = []
                for code in candidates:
                    dfh = _slice_until(code, dt)
                    sc = _score_by_momentum(dfh, lookback=int(lookback))
                    if sc <= -1e8:
                        continue
                    scored.append((code, sc))
                scored.sort(key=lambda x: x[1], reverse=True)
                picks = [c for c, _ in scored[: max(1, int(top_k))]]

                # sell positions not in picks (at close)
                for code in list(positions.keys()):
                    if code not in picks:
                        px = _last_close(code, dt)
                        if px is None:
                            continue
                        pos = positions[code]
                        proceeds = pos.shares * px
                        cost = proceeds * float(fee)
                        cash += (proceeds - cost)
                        trade_rows.append({
                            "date": dt.strftime("%Y-%m-%d"),
                            "code": code,
                            "side": "SELL",
                            "price": float(px),
                            "shares": float(pos.shares),
                            "value": float(proceeds),
                            "fee": float(cost),
                            "reason": "REBALANCE",
                        })
                        del positions[code]

                # compute current equity to size buys
                holdings_value = 0.0
                for code, pos in positions.items():
                    px = _last_close(code, dt)
                    if px is None:
                        continue
                    holdings_value += pos.shares * px
                equity = cash + holdings_value

                # buy missing picks
                if picks:
                    target_each = equity / float(len(picks))
                    for code in picks:
                        px = _last_close(code, dt)
                        if px is None or px <= 0:
                            continue
                        # if already held, skip (we keep shares; simple model)
                        if code in positions:
                            continue
                        # shares: round down to 100-share board lot when possible
                        raw_shares = target_each / px
                        lot = 100.0
                        shares = math.floor(raw_shares / lot) * lot if raw_shares >= lot else 0.0
                        if shares <= 0:
                            continue
                        cost_val = shares * px
                        fee_val = cost_val * float(fee)
                        if cost_val + fee_val > cash:
                            continue
                        cash -= (cost_val + fee_val)
                        positions[code] = Position(code=code, shares=float(shares), entry_price=float(px), entry_date=dt.strftime("%Y-%m-%d"))
                        trade_rows.append({
                            "date": dt.strftime("%Y-%m-%d"),
                            "code": code,
                            "side": "BUY",
                            "price": float(px),
                            "shares": float(shares),
                            "value": float(cost_val),
                            "fee": float(fee_val),
                            "reason": "REBALANCE",
                        })

            # 3) record equity
            holdings_value = 0.0
            for code, pos in positions.items():
                px = _last_close(code, dt)
                if px is None:
                    continue
                holdings_value += pos.shares * px
            equity = cash + holdings_value
            curve_rows.append({
                "date": dt.strftime("%Y-%m-%d"),
                "equity": float(equity),
                "cash": float(cash),
                "holdings": float(holdings_value),
            })

        curve = pd.DataFrame(curve_rows)
        if curve.empty:
            return {"ok": False, "msg": "模拟无输出（可能数据不足）", "metrics": {}}

        # metrics
        total_return = float(curve["equity"].iloc[-1] / curve["equity"].iloc[0] - 1.0)
        days = max(1, len(curve))
        annual_return = float((1.0 + total_return) ** (252.0 / days) - 1.0)
        max_dd = _max_drawdown(curve["equity"])
        trades = pd.DataFrame(trade_rows)

        metrics = {
            "total_return": total_return,
            "annual_return": annual_return,
            "max_drawdown": max_dd,
            "n_trades": int(len(trades)),
            "start_equity": float(curve["equity"].iloc[0]),
            "end_equity": float(curve["equity"].iloc[-1]),
        }

        # final positions
        final_equity = float(curve["equity"].iloc[-1])
        pos_list: List[Dict[str, Any]] = []
        for code, pos in positions.items():
            px = _last_close(code, pd.to_datetime(curve["date"].iloc[-1]))
            if px is None:
                continue
            val = pos.shares * px
            w = val / final_equity if final_equity > 0 else 0.0
            pos_list.append({
                "code": code,
                "shares": float(pos.shares),
                "price": float(px),
                "value": float(val),
                "weight": float(w),
                "entry_price": float(pos.entry_price),
                "entry_date": pos.entry_date,
            })

        # prettier trades
        if not trades.empty:
            trades = trades[["date", "code", "side", "price", "shares", "value", "fee", "reason"]]

        return {
            "ok": True,
            "msg": "OK",
            "metrics": metrics,
            "equity_curve": curve,
            "trades": trades,
            "positions": pos_list,
        }

    except Exception as e:
        return {"ok": False, "msg": f"模拟仓异常：{e}", "metrics": {}}
