"""Rule-based research decision engine for single-stock page."""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class TrendMetrics:
    returns_20: Optional[float] = None
    returns_60: Optional[float] = None
    returns_120: Optional[float] = None
    atr_ratio: Optional[float] = None
    last_close: Optional[float] = None
    last_date: Optional[str] = None


def _safe_pd():
    try:
        import pandas as pd  # type: ignore

        return pd
    except Exception:
        return None


def _to_float(val: Any) -> Optional[float]:
    try:
        f = float(val)
        if math.isnan(f) or math.isinf(f):
            return None
        return f
    except Exception:
        return None


def _calc_returns(series: List[float], window: int) -> Optional[float]:
    if not series or len(series) <= window:
        return None
    try:
        start = series[-window - 1]
        end = series[-1]
        if start in (0, None):
            return None
        return (end - start) / start
    except Exception:
        return None


def _trend_from_kline(kline: Any) -> TrendMetrics:
    pd = _safe_pd()
    closes: List[float] = []
    highs: List[float] = []
    lows: List[float] = []
    dates: List[str] = []

    if pd is not None and hasattr(kline, "get"):
        series = kline.get("daily") if isinstance(kline, dict) else None
    else:
        series = kline

    if pd is not None and hasattr(pd, "DataFrame") and not isinstance(series, list) and series is not None:
        try:
            df = pd.DataFrame(series)
        except Exception:
            df = pd.DataFrame()
    else:
        try:
            df = pd.DataFrame(series) if pd is not None else None  # type: ignore[var-annotated]
        except Exception:
            df = None

    if df is not None and getattr(df, "empty", True) is False:
        lower_cols = {str(c).lower(): c for c in df.columns}
        close_col = next((lower_cols[c] for c in lower_cols if c in {"close", "收盘", "收盘价"}), None)
        high_col = next((lower_cols[c] for c in lower_cols if c in {"high", "最高"}), None)
        low_col = next((lower_cols[c] for c in lower_cols if c in {"low", "最低"}), None)
        date_col = next((lower_cols[c] for c in lower_cols if c in {"date", "trade_date", "时间"}), None)
        if date_col:
            try:
                df = df.sort_values(by=date_col)
            except Exception:
                pass
        if close_col:
            closes = [_to_float(x) for x in df[close_col].tolist() if _to_float(x) is not None]
        if high_col:
            highs = [_to_float(x) for x in df[high_col].tolist() if _to_float(x) is not None]
        if low_col:
            lows = [_to_float(x) for x in df[low_col].tolist() if _to_float(x) is not None]
        if date_col:
            dates = [str(x) for x in df[date_col].tolist()]
    elif isinstance(series, list):
        for row in series:
            if not isinstance(row, dict):
                continue
            closes.append(_to_float(row.get("close")) or _to_float(row.get("收盘")) or _to_float(row.get("收盘价")) or 0.0)
            highs.append(_to_float(row.get("high")) or _to_float(row.get("最高")) or 0.0)
            lows.append(_to_float(row.get("low")) or _to_float(row.get("最低")) or 0.0)
            dates.append(str(row.get("date") or row.get("trade_date") or row.get("时间") or ""))

    closes = [c for c in closes if c is not None]
    highs = [h for h in highs if h is not None]
    lows = [l for l in lows if l is not None]

    if not closes:
        return TrendMetrics()

    returns_20 = _calc_returns(closes, 20)
    returns_60 = _calc_returns(closes, 60)
    returns_120 = _calc_returns(closes, 120)

    atr_ratio = None
    if highs and lows:
        true_ranges = [abs(h - l) for h, l in zip(highs[-30:], lows[-30:]) if h is not None and l is not None]
        try:
            atr = statistics.mean(true_ranges) if true_ranges else None
            last_close = closes[-1]
            if atr is not None and last_close not in (None, 0):
                atr_ratio = atr / last_close
        except Exception:
            atr_ratio = None

    last_date = dates[-1] if dates else None

    return TrendMetrics(
        returns_20=returns_20,
        returns_60=returns_60,
        returns_120=returns_120,
        atr_ratio=atr_ratio,
        last_close=closes[-1] if closes else None,
        last_date=last_date,
    )


def _financial_signals(financial: Dict[str, Any]) -> Dict[str, Any]:
    data = financial.get("data") if isinstance(financial, dict) else {}
    stmt = None
    statements = []
    if isinstance(data, dict):
        statements = data.get("statements") or []
        if statements:
            stmt = statements[0]
    signals = {}
    if isinstance(stmt, dict):
        for key in [
            "revenue",
            "revenue_yoy",
            "profit",
            "profit_yoy",
            "roe",
            "gross_margin",
            "operating_cashflow",
            "free_cashflow",
            "net_margin",
            "total_debt",
            "assets",
            "cashflow_yoy",
        ]:
            if key in stmt:
                signals[key] = stmt.get(key)
    return signals


def _announcement_signals(announcements: List[Dict[str, Any]]) -> Dict[str, Any]:
    negatives = ["风险", "诉讼", "减持", "亏损", "终止", "问询", "调查", "退市"]
    recent_negative = []
    for ann in announcements[:30]:
        title = str((ann or {}).get("title") or "")
        if any(word in title for word in negatives):
            recent_negative.append(title)
    return {"count": len(announcements), "negative_titles": recent_negative}


def _score_from_trend(trend: TrendMetrics) -> float:
    score = 50.0
    for w, ret in [(20, trend.returns_20), (60, trend.returns_60), (120, trend.returns_120)]:
        if ret is None:
            continue
        bump = min(20, max(-20, ret * 100)) * (0.25 if w == 20 else 0.35 if w == 60 else 0.4)
        score += bump
    if trend.atr_ratio is not None:
        if trend.atr_ratio > 0.08:
            score -= 8
        elif trend.atr_ratio < 0.03:
            score += 3
    return max(0.0, min(100.0, score))


def _score_from_financials(signals: Dict[str, Any]) -> float:
    if not signals:
        return 0.0
    score = 0.0

    def bump(key: str, weight: float, positive: bool = True):
        nonlocal score
        val = _to_float(signals.get(key))
        if val is None:
            return
        if not positive:
            val = -val
        score += weight * val

    bump("roe", 0.8)
    bump("gross_margin", 0.3)
    bump("profit_yoy", 0.25)
    bump("revenue_yoy", 0.2)
    bump("operating_cashflow", 0.05)
    bump("net_margin", 0.2)
    score = max(-20.0, min(40.0, score))
    return score


def _data_quality(
    kline_ok: bool, fin_ok: bool, ann_ok: bool, kline_len: int, financial_fields: int
) -> Tuple[int, List[str]]:
    score = 100
    notes: List[str] = []
    if not kline_ok:
        score -= 35
        notes.append("K线不足，趋势无法全面评估")
    elif kline_len < 150:
        score -= 5
        notes.append("K线覆盖 <150 条，长期趋势有限")
    if not fin_ok:
        score -= 30
        notes.append("财务缺失，无法验证盈利质量")
    elif financial_fields < 12:
        score -= 8
        notes.append("财务字段较少，分析精度下降")
    if not ann_ok:
        score -= 15
        notes.append("公告缺失，事件风险不可见")
    score = max(0, min(100, score))
    return score, notes


def build_decision(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Build a deterministic research decision card.

    Returns a dict with keys: decision_card, evidence_map, scored_factors.
    """

    kline = payload.get("kline") if isinstance(payload, dict) else {}
    kline_series = []
    if isinstance(kline, dict):
        kline_series = kline.get("daily") or kline.get("data") or []
    elif isinstance(kline, list):
        kline_series = kline
    financial = payload.get("financial") if isinstance(payload, dict) else {}
    announcements = []
    ann_obj = payload.get("announcements") if isinstance(payload, dict) else {}
    if isinstance(ann_obj, dict):
        announcements = (ann_obj.get("data") or {}).get("announcements", []) or ann_obj.get("announcements", []) or []

    trend = _trend_from_kline({"daily": kline_series})
    fin_signals = _financial_signals(financial)
    ann_signals = _announcement_signals(announcements)

    kline_ok = bool(kline_series)
    fin_ok = bool(fin_signals)
    ann_ok = ann_signals.get("count", 0) > 0
    financial_fields = len([v for v in fin_signals.values() if _to_float(v) is not None])
    data_quality_score, missing_notes = _data_quality(kline_ok, fin_ok, ann_ok, len(kline_series), financial_fields)

    trend_score = _score_from_trend(trend)
    fin_score = _score_from_financials(fin_signals)
    ann_penalty = -8 if ann_signals.get("negative_titles") else 0

    composite = max(0.0, min(100.0, trend_score + fin_score + ann_penalty))

    verdict = "WATCH"
    horizon = "1m"
    if composite >= 75 and trend_score >= 55:
        verdict = "BUY"
        horizon = "1-3m" if fin_score > 5 else "1m"
    elif composite <= 45:
        verdict = "AVOID"
        horizon = "1w"

    evidence_map: Dict[str, Dict[str, Any]] = {}
    if trend.returns_120 is not None:
        evidence_map["price_trend"] = {
            "type": "kline",
            "summary": f"120日涨幅 {trend.returns_120*100:.1f}%；20日 {(trend.returns_20 or 0)*100:.1f}%",
        }
    if fin_signals:
        roe = _to_float(fin_signals.get("roe"))
        gm = _to_float(fin_signals.get("gross_margin"))
        pyoy = _to_float(fin_signals.get("profit_yoy"))
        evidence_map["financials"] = {
            "type": "financial",
            "summary": f"ROE {roe if roe is not None else '—'}%, 毛利率 {gm if gm is not None else '—'}%, 利润增速 {pyoy if pyoy is not None else '—'}%",
        }
    if ann_signals.get("negative_titles"):
        evidence_map["announcement_risk"] = {
            "type": "announcement",
            "summary": f"风险公告 {len(ann_signals['negative_titles'])} 条: {ann_signals['negative_titles'][:2]}",
        }
    if not evidence_map:
        evidence_map["insufficient"] = {"type": "missing", "summary": "证据不足"}

    def _with_ev(text: str, ev_key: str | None) -> str:
        return f"{text}（证据:{ev_key}）" if ev_key else text

    thesis = []
    if "price_trend" in evidence_map:
        thesis.append(_with_ev("趋势保持向上", "price_trend"))
    if "financials" in evidence_map:
        thesis.append(_with_ev("盈利质量可见", "financials"))
    if "announcement_risk" not in evidence_map and ann_ok:
        thesis.append("公告频次正常（证据:announcements)")
    if not thesis:
        thesis.append("insufficient evidence：缺少趋势/财务数据")
        data_quality_score = max(0, data_quality_score - 10)

    risks = []
    if "announcement_risk" in evidence_map:
        risks.append(_with_ev("公告含风险信号", "announcement_risk"))
    if trend.atr_ratio and trend.atr_ratio > 0.08:
        risks.append("波动高于常态（证据:kline volatility)")
    if not risks:
        risks.append("insufficient evidence：未捕获公告/波动风险")
        data_quality_score = max(0, data_quality_score - 5)

    triggers = []
    if trend.returns_20 is not None and trend.returns_20 < 0:
        triggers.append("若20日跌幅收窄至0，考虑转多（证据:price_trend)")
    if ann_signals.get("negative_titles"):
        triggers.append("风险公告落地后情绪企稳再参与（证据:announcement_risk)")
    if fin_signals:
        triggers.append("下一份财报如维持正利润增速则提高仓位（证据:financials)")
    if len(triggers) < 3:
        triggers.append("insufficient evidence：需要更多事件触发条件")

    disconfirming = ["公告出现退市/重大诉讼", "下一期财报利润转负", "120日趋势转为下行"]

    position_pct = 0
    if verdict == "BUY":
        position_pct = int(20 + composite * 0.5)
    elif verdict == "WATCH":
        position_pct = int(5 + composite * 0.2)
    else:
        position_pct = 0
    position_pct = max(0, min(100, position_pct))

    decision_card = {
        "verdict": verdict,
        "horizon": horizon,
        "thesis": thesis,
        "risks": risks,
        "triggers": triggers,
        "disconfirming_checklist": disconfirming,
        "position_sizing_pct": position_pct,
        "position_rationale": "基于趋势/财务分与数据质量的规则输出",
        "data_quality_score": data_quality_score,
        "missing_notes": missing_notes,
        "evidence_map": evidence_map,
    }

    scored_factors = {
        "trend_score": trend_score,
        "financial_score": fin_score,
        "announcement_penalty": ann_penalty,
        "composite": composite,
    }

    return {
        "decision_card": decision_card,
        "scored_factors": scored_factors,
        "evidence_map": evidence_map,
    }
