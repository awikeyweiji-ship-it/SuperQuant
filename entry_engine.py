# -*- coding: utf-8 -*-
"""entry_engine.py
Step5: 入场/建仓信号（技术面）

输出：entry_score(0~1)、action(BUILD/WATCH/AVOID)、止损价。
仅依赖 OHLCV，失败不崩溃。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd


def _clip01(x: float) -> float:
    try:
        return float(max(0.0, min(1.0, float(x))))
    except Exception:
        return 0.0


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    close = pd.to_numeric(close, errors='coerce').fillna(method='ffill')
    delta = close.diff()
    up = delta.clip(lower=0)
    down = (-delta).clip(lower=0)
    ma_up = up.rolling(period).mean()
    ma_down = down.rolling(period).mean().replace(0, np.nan)
    rs = ma_up / ma_down
    rsi = 100 - (100 / (1 + rs))
    return rsi.fillna(50)


def _atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    high = pd.to_numeric(high, errors='coerce')
    low = pd.to_numeric(low, errors='coerce')
    close = pd.to_numeric(close, errors='coerce')
    prev_close = close.shift(1)
    tr = pd.concat([
        (high - low).abs(),
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean().fillna(method='bfill')


@dataclass
class EntrySignal:
    score: float
    action: str
    stop_loss_price: Optional[float]
    meta: Dict[str, Any]


class EntryEngine:
    """轻量技术入场引擎。"""

    def score(self, kline: pd.DataFrame, as_of: Optional[str] = None) -> EntrySignal:
        if kline is None or len(kline) < 30:
            return EntrySignal(score=0.5, action='WATCH', stop_loss_price=None, meta={'reason': 'insufficient_kline'})

        df = kline.copy()
        # normalize column names
        if 'date' in df.columns:
            df['date'] = pd.to_datetime(df['date'], errors='coerce')
        else:
            # try index
            df = df.reset_index().rename(columns={'index': 'date'})
            df['date'] = pd.to_datetime(df['date'], errors='coerce')

        if as_of:
            try:
                cutoff = pd.to_datetime(as_of)
                df = df[df['date'] <= cutoff]
            except Exception:
                pass

        df = df.dropna(subset=['close']).sort_values('date')
        if len(df) < 30:
            return EntrySignal(score=0.5, action='WATCH', stop_loss_price=None, meta={'reason': 'insufficient_kline'})

        close = pd.to_numeric(df['close'], errors='coerce')
        high = pd.to_numeric(df.get('high', close), errors='coerce')
        low = pd.to_numeric(df.get('low', close), errors='coerce')
        vol = pd.to_numeric(df.get('volume', 0), errors='coerce').fillna(0)

        ma20 = close.rolling(20).mean()
        ma60 = close.rolling(60).mean()
        rsi14 = _rsi(close, 14)
        atr14 = _atr(high, low, close, 14)

        # latest values
        c = float(close.iloc[-1])
        ma20v = float(ma20.iloc[-1]) if not np.isnan(ma20.iloc[-1]) else c
        ma60v = float(ma60.iloc[-1]) if not np.isnan(ma60.iloc[-1]) else ma20v
        r = float(rsi14.iloc[-1]) if not np.isnan(rsi14.iloc[-1]) else 50.0
        atr = float(atr14.iloc[-1]) if not np.isnan(atr14.iloc[-1]) else (0.03 * c)

        # trend filter
        trend = 0.0
        if c >= ma20v:
            trend += 0.25
        if ma20v >= ma60v:
            trend += 0.20

        # momentum (5d)
        ret5 = 0.0
        try:
            ret5 = float(close.iloc[-1] / close.iloc[-6] - 1.0)
        except Exception:
            ret5 = 0.0
        mom = 0.15 if ret5 > 0 else 0.05

        # rsi comfort zone
        rsi_score = 0.20 if (45 <= r <= 70) else (0.10 if (35 <= r <= 80) else 0.05)

        # breakout / consolidation
        hi20 = float(high.rolling(20).max().iloc[-1])
        lo20 = float(low.rolling(20).min().iloc[-1])
        pos = 0.5
        if hi20 > lo20:
            pos = float((c - lo20) / (hi20 - lo20))
        # volume ratio
        vol20 = float(vol.rolling(20).mean().iloc[-1]) if len(vol) >= 20 else float(vol.mean() or 0)
        vr = float(vol.iloc[-1] / vol20) if vol20 > 0 else 1.0

        breakout = 0.0
        if c >= hi20 * 0.97 and vr >= 1.2:
            breakout = 0.20
        # mean reversion buy the dip (only if trend not broken)
        dip = 0.0
        if pos <= 0.40 and r <= 45 and c >= ma60v * 0.95:
            dip = 0.15

        # risk penalty: chasing / extreme move
        penalty = 0.0
        if vr >= 2.2:
            penalty += 0.05
        if abs(ret5) >= 0.20:
            penalty += 0.05

        score = _clip01(trend + mom + rsi_score + max(breakout, dip) - penalty)

        if score >= 0.72:
            action = 'BUILD'
        elif score >= 0.58:
            action = 'WATCH'
        else:
            action = 'AVOID'

        # stop loss: max(2*ATR, 7% price)
        stop_gap = max(2.0 * atr, 0.07 * c)
        stop_price = max(0.01, c - stop_gap)

        meta = {
            'close': c,
            'ma20': ma20v,
            'ma60': ma60v,
            'rsi14': r,
            'ret5': ret5,
            'vol_ratio': vr,
            'pos_20': pos,
            'atr14': atr,
            'penalty': penalty,
        }
        return EntrySignal(score=float(score), action=action, stop_loss_price=float(stop_price), meta=meta)

