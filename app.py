# -*- coding: utf-8 -*-
"""
app.py
======
五维超脑·天网指挥台 (Commercial Pro V12.0 - 终极全能版)

【版本特性】
1. **全能视图**: K线(日/周/月)、因子雷达、深度研报、财务数据一站式展示。
2. **多重人格**: 完美渲染 AI 的“商业拆解+宏观策略+游资博弈”多维分析。
3. **全域覆盖**: 支持全A股及各大细分板块扫描。
"""

import os
import re
from datetime import datetime, date
from typing import Any, Dict, List, Optional

import numpy as np
from config_manager import get_config, update_keys, test_deepseek, test_tavily
import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# 引入核心组件
from universe_cache import UniverseCache
from data_engine import DataEngine, normalize_code, normalize_single_stock_payload, standardize_code
from tools.connectivity_doctor_v2 import probe_endpoints
from market_scanner import MarketScanner, ScanConfig
from deep_search_agent import DeepSearchAgent
from radiation_engine import RadiationEngine
from signal_fuser import SignalFuser
from slow_factor_engine import SlowFactorEngine
from paper_portfolio import simulate_paper_portfolio
from research.decision_engine import build_decision
import ai_advisor
from logging_utils import FetchResult, build_error, make_result

# Step4: backtest + weight learning (optional)
try:
    from weight_learner import learn_weights, save_weights, load_weights
    from step4_backtest import run_factor_backtest
except Exception:
    learn_weights = None
    save_weights = None
    load_weights = None
    run_factor_backtest = None


# Optional pandas import to avoid pyarrow MemoryError on constrained hosts
_PD_REF: Optional[Any] = None
_PD_ERROR: Optional[str] = None


def _get_pandas():
    global _PD_REF, _PD_ERROR
    if _PD_REF is not None or _PD_ERROR is not None:
        return _PD_REF
    try:
        import pandas as pd  # type: ignore

        _PD_REF = pd
    except (ImportError, MemoryError) as exc:  # noqa: PIE786
        _PD_ERROR = f"{exc.__class__.__name__}: {exc}"
        _PD_REF = None
    return _PD_REF


def _pd_available() -> bool:
    return _get_pandas() is not None


def _pd_error_message() -> Optional[str]:
    return _PD_ERROR


def _safe_dataframe(df, **kwargs):
    """Render dataframe defensively to avoid Arrow conversion crashes."""
    pd = _get_pandas()
    def _sanitize(frame):
        if pd is None:
            return frame
        tmp = pd.DataFrame(frame).copy()
        for col in tmp.columns:
            if str(tmp[col].dtype) == "object":
                tmp[col] = tmp[col].replace({"—": None, "--": None, "": None}).astype(str)
            else:
                tmp[col] = pd.to_numeric(tmp[col], errors="ignore")
        return tmp

    try:
        return st.dataframe(_sanitize(df) if pd is not None else df, **kwargs)
    except Exception:
        try:
            return st.dataframe(_sanitize(df) if pd is not None else df, **kwargs)
        except Exception:
            try:
                return st.dataframe(pd.DataFrame(df).astype(str) if pd is not None else [], **kwargs)
            except Exception:
                return st.dataframe([], **kwargs)


# ==========================================
# 1. 页面全局配置
# ==========================================
st.set_page_config(
    page_title="五维超脑 | 终极商业版",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 注入顶级金融终端 CSS
st.markdown("""
<style>
    /* 战备状态颜色 */
    .defcon-attack { background-color: #d4edda; color: #155724; padding: 10px; border-left: 5px solid #28a745; }
    .defcon-defense { background-color: #fff3cd; color: #856404; padding: 10px; border-left: 5px solid #ffc107; }
    .defcon-retreat { background-color: #f8d7da; color: #721c24; padding: 10px; border-left: 5px solid #dc3545; }
    
    /* 决策高亮 */
    .decision-buy { color: #d32f2f; font-weight: 900; font-size: 1.2em; }
    .decision-sell { color: #2e7d32; font-weight: 900; font-size: 1.2em; }
    
    /* 卡片样式 */
    .metric-card { background-color: #ffffff; padding: 15px; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); margin-bottom: 10px; }
    .logic-box { background-color: #f8f9fa; border-left: 4px solid #4e8cff; padding: 15px; margin-bottom: 10px; border-radius: 4px; }
    
    /* 标签 */
    .tag-concept { background-color: #e3f2fd; color: #1565c0; padding: 2px 8px; border-radius: 12px; font-size: 0.85em; margin-right: 5px; }
</style>
""", unsafe_allow_html=True)

# ==========================================
# 2. 初始化与连接
# ==========================================
st.sidebar.title("🧠 五维超脑 V12.0")
st.sidebar.caption("全能商业决策系统")

with st.sidebar.expander("🔑 神经连接 (API Keys)", expanded=True):
    cfg = get_config()
    ds_key = st.text_input("DeepSeek Key", value=(cfg.deepseek_api_key or ""), type="password", help="用于 AI 审计/宏观研判/辐射推演")
    tavily_key = st.text_input("Tavily Key (可选)", value=(cfg.tavily_api_key or ""), type="password", help="用于联网搜索（不填也可离线运行）")

    c1, c2, c3 = st.columns(3)
    if c1.button("💾 保存配置", width="stretch"):
        update_keys(deepseek_api_key=ds_key, tavily_api_key=tavily_key)
        st.success("已保存到本地配置（.w5brain_config.json）。定时指挥塔也会读取同一份配置。")

    if c2.button("🔌 测试DeepSeek", width="stretch"):
        ok, msg = test_deepseek(ds_key)
        (st.success if ok else st.error)(msg)

    if c3.button("🔌 测试Tavily", width="stretch"):
        ok, msg = test_tavily(tavily_key)
        (st.success if ok else st.warning)(msg)

    # 保存到 Session（用于本次会话立即生效）
    st.session_state["api_key"] = ds_key
    st.session_state["tavily_key"] = tavily_key

offline_mode = st.sidebar.checkbox(
    "离线样本模式（允许使用本地样本 fallback）",
    value=os.environ.get("ALLOW_OFFLINE_SAMPLES", "").lower() in {"1", "true", "yes", "on"},
    help="默认关闭。仅在无网场景下手动勾选，才会使用本地样本/占位数据。",
)
os.environ["ALLOW_OFFLINE_SAMPLES"] = "1" if offline_mode else "0"
sample_mode = st.sidebar.checkbox("样本模式(允许 sample_cache)", value=False, help="默认关闭，开启后才允许读取 sample_cache 兜底")
force_refresh = st.sidebar.checkbox("强制刷新", value=False, help="关闭缓存，强制拉取最新数据")
os.environ["ALLOW_SAMPLE_CACHE"] = "1" if sample_mode else "0"
os.environ["FORCE_REFRESH"] = "1" if force_refresh else "0"
st.session_state["offline_mode_flag"] = offline_mode
st.session_state["sample_mode"] = sample_mode
st.session_state["force_refresh"] = force_refresh

with st.sidebar.expander("🔎 连接自检", expanded=False):
    if st.button("运行 Connectivity Doctor v2", use_container_width=True):
        results = probe_endpoints()
        st.json(results)

pd_err_msg = _pd_error_message()
if pd_err_msg:
    st.sidebar.warning(
        "pandas 未加载，已切换为纯 Python 表格展示。错误: {}".format(pd_err_msg)
    )

# 初始化引擎 (单例模式)
if "init_done" not in st.session_state:
    with st.spinner("系统自检中..."):
        cache = UniverseCache()
        engine = DataEngine(cache=cache)
        st.session_state["engine"] = engine
        st.session_state["scanner"] = MarketScanner(engine=engine, cache=cache)
        st.session_state["fuser"] = SignalFuser(engine=engine, cache=cache)
        st.session_state["slow_engine"] = SlowFactorEngine(cache)
        st.session_state["init_done"] = True


# Ensure slow_engine exists even if session was created by old versions
if "slow_engine" not in st.session_state:
    try:
        _cache = getattr(st.session_state.get("engine"), "cache", None)
        st.session_state["slow_engine"] = SlowFactorEngine(_cache or UniverseCache())
    except Exception:
        pass

# 便捷引用
ENGINE: DataEngine = st.session_state["engine"]
SCANNER: MarketScanner = st.session_state["scanner"]
FUSER: SignalFuser = st.session_state["fuser"]
SLOW: SlowFactorEngine = st.session_state.get("slow_engine")
search_agent = DeepSearchAgent(deepseek_key=ds_key, tavily_key=tavily_key)
rad_engine = RadiationEngine(api_key=ds_key)

# 模式选择
mode = st.sidebar.radio("作战模式", 
    ["☢️ 天网机会雷达 (Smart Radar)", "🔎 单股深度博弈 (Deep Game)", "📦 模拟仓 (Paper Portfolio)", "📊 策略回测 (Time Machine)"], 
    index=0
)


# ==========================================
# 2.5 兼容工具函数
# ==========================================

def _fmt_ts(ts_val: float) -> str:
    try:
        return datetime.fromtimestamp(float(ts_val)).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return "-"


def _fmt_val(val, suffix: str = ""):
    if val is None:
        return "—"
    try:
        if isinstance(val, float) and (np.isnan(val) or np.isinf(val)):
            return "—"
    except Exception:
        pass
    if val == "" or val == "--":
        return "—"
    return f"{val}{suffix}" if suffix else str(val)


def _normalize_trade_date(val: Any) -> Optional[str]:
    try:
        if isinstance(val, (datetime, date)):
            return val.strftime("%Y-%m-%d")
        s = str(val).strip()
        if not s:
            return None
        if re.fullmatch(r"\d{8}", s):
            return f"{s[:4]}-{s[4:6]}-{s[6:]}"
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
            return s
        return s.split(" ")[0]
    except Exception:
        return None


def _extract_latest_close(kline_obj) -> tuple[Optional[float], Optional[str]]:
    """Safely extract the latest close and date from flexible kline payloads."""

    def _as_float(val: Any) -> Optional[float]:
        try:
            f = float(val)
            if np.isnan(f) or np.isinf(f):
                return None
            return f
        except Exception:
            return None

    close_candidates = {"close", "closing", "收盘", "收盘价"}
    date_candidates = {"date", "trade_date", "时间", "日期", "day"}
    pd = _get_pandas()

    if kline_obj is None:
        return None, None

    # pandas DataFrame path
    if pd is not None and isinstance(kline_obj, pd.DataFrame):
        df = kline_obj
        if df.empty:
            return None, None
        mapping = {str(col).lower(): col for col in df.columns}
        close_col = next((mapping[c] for c in mapping if c in close_candidates), None)
        if close_col is None:
            return None, None
        date_col = next((mapping[c] for c in mapping if c in date_candidates), None)
        df_work = df.dropna(subset=[close_col]) if close_col in df.columns else df
        if date_col and date_col in df_work.columns:
            try:
                df_work = df_work.sort_values(by=date_col)
            except Exception:
                pass
            latest_row = df_work.iloc[-1]
            return _as_float(latest_row.get(close_col)), _normalize_trade_date(latest_row.get(date_col))
        latest_row = df_work.iloc[-1]
        return _as_float(latest_row.get(close_col)), None

    # list of dicts path
    if isinstance(kline_obj, list):
        for item in reversed(kline_obj):
            if not isinstance(item, dict):
                continue
            item_lower = {str(k).lower(): v for k, v in item.items()}
            close_val = next((item_lower.get(c) for c in close_candidates if c in item_lower), None)
            close_val = _as_float(close_val)
            if close_val is None:
                continue
            date_val = next((item_lower.get(c) for c in date_candidates if c in item_lower), None)
            return close_val, _normalize_trade_date(date_val)

    return None, None


def _render_errors(errors):
    if not errors:
        st.caption("无错误")
        return
    for err in errors:
        src = err.get("source", "?")
        typ = err.get("error_type", "?")
        msg = err.get("message", "")
        st.error(f"来源: {src} | 类型: {typ} | 详情: {msg}")


def _safe_fetch(fn, label: str) -> FetchResult:
    try:
        res = fn()
        if isinstance(res, FetchResult):
            return res
        if hasattr(res, "ok") and hasattr(res, "errors"):
            return res  # type: ignore[return-value]
        return make_result({}, source=label, errors=[build_error(label, "invalid", "返回结构非 FetchResult")])
    except Exception as e:  # noqa: BLE001
        return make_result({}, source=label, fallback_used=True, errors=[build_error(label, "exception", str(e))])


def _safe_holistic(engine, code: str):
    code_std = standardize_code(code)
    try:
        res = engine.single_stock(code_std)
        res = normalize_single_stock_payload(res)
        res["money_flow"] = res.get("money_flow", {})
        return res
    except Exception as e:  # noqa: BLE001
        return {
            "code": code_std,
            "market_data": {},
            "identity": {},
            "financial": {},
            "money_flow": {},
            "news_bundle": {},
            "diagnostics": [],
            "evidence_pack": [],
            "advice": {"action": "观望", "evidence": []},
            "_meta": {"error": str(e)},
        }


def _as_dict(val: dict | None) -> dict:
    return val if isinstance(val, dict) else {}


def _errors_count(errs) -> int:
    if isinstance(errs, list):
        return len(errs)
    return 0


def _filled_from_meta(meta_obj: dict | None):
    base = _as_dict(meta_obj)
    inner = _as_dict(base.get("meta"))
    return base.get("filled_metrics") or base.get("count") or inner.get("filled_metrics") or inner.get("count")


def _render_meta(meta: dict | None):
    meta = _as_dict(meta)
    src = meta.get("source", "-")
    fb = "是" if meta.get("fallback_used") else "否"
    cache = "命中" if meta.get("cache_hit") else "未命中"
    ts_str = _fmt_ts(meta.get("ts"))
    filled = _filled_from_meta(meta)
    st.caption(
        "来源: {} | fallback: {} | 缓存: {} | 时间: {} | 覆盖: {}".format(
            src, fb, cache, ts_str, filled if filled is not None else "—",
        )
    )


def _minmax_norm(s):
    pd = _get_pandas()
    if pd is None:
        try:
            return [0.5] * len(s)
        except Exception:
            return []
    s = pd.to_numeric(s, errors="coerce").fillna(0.0)
    if len(s) == 0:
        return s
    mn, mx = float(s.min()), float(s.max())
    if mx - mn < 1e-9:
        return pd.Series([0.5] * len(s), index=s.index)
    return (s - mn) / (mx - mn)


def compute_entry_scores(df):
    """Compute entry_score for 'build position now' list.

    商用化闭环（Step4）：
    - 先用 Smart Radar 扫描积累慢变量
    - 使用权重学习输出 .w5brain_weights.json
    - 这里自动加载权重，把“慢变量”转成可迭代的建仓评分
    """
    pd = _get_pandas()
    if pd is None or df is None or getattr(df, "empty", True):
        return df
    d = df.copy()
    base_col = "fused_score" if "fused_score" in d.columns else "score"
    base_norm = _minmax_norm(d[base_col])
    slow = pd.to_numeric(d.get("slow_score", 0.5), errors="coerce").fillna(0.5).clip(0, 1)

    learned = None
    try:
        if load_weights:
            model = load_weights(".w5brain_weights.json")
        else:
            model = None
        if isinstance(model, dict) and model.get("ok"):
            w = model.get("weights") or {}
            mu = model.get("mu") or {}
            sd = model.get("sd") or {}
            def row_score(r):
                s = 0.0
                for k, ww in w.items():
                    x = float(pd.to_numeric(r.get(k, 0.5), errors="coerce") or 0.5)
                    m = float(mu.get(k, 0.0) or 0.0)
                    ss = float(sd.get(k, 1.0) or 1.0)
                    z = (x - m) / (ss if ss != 0 else 1.0)
                    s += float(ww) * float(z)
                # sigmoid to 0~1
                return float(1.0 / (1.0 + np.exp(-2.2 * s)))
            learned = d.apply(row_score, axis=1).clip(0, 1)
            d["learned_score"] = learned.round(4)
    except Exception:
        learned = None

    if learned is not None:
        # blend: fast resonance + slow total + learned
        d["entry_score"] = (0.45 * base_norm + 0.35 * slow + 0.20 * learned).clip(0, 1).round(4)
    else:
        d["entry_score"] = (0.6 * base_norm + 0.4 * slow).clip(0, 1).round(4)

    
    # build action + sizing (简化版，可在 Step5+ 再迭代为更精细的风控/仓位算法)
    mp = pd.to_numeric(d.get("market_pricing", 0.5), errors="coerce").fillna(0.5).clip(0,1)
    info = pd.to_numeric(d.get("info_priced_in", 0.5), errors="coerce").fillna(0.5).clip(0,1)
    pct = pd.to_numeric(d.get("pct", 0.0), errors="coerce").fillna(0.0)
    # 追高风险：单日涨幅过大 + 量比过高
    vr = pd.to_numeric(d.get("vol_ratio", 1.0), errors="coerce").fillna(1.0)
    chase_risk = (pct >= 6.0) & (vr >= 1.8)

    def _action(row):
        es = float(row.get("entry_score", 0.0) or 0.0)
        if es >= 0.80 and float(row.get("market_pricing",0.5)) >= 0.50 and float(row.get("info_priced_in",0.5)) <= 0.72:
            return "BUILD_NOW"
        if es >= 0.68 and float(row.get("info_priced_in",0.5)) <= 0.78:
            return "WATCH"
        return "AVOID"

    d["build_action"] = d.apply(_action, axis=1)
    d.loc[chase_risk, "build_action"] = "WATCH"

    # 仓位建议：0~12%（单票），并对拥挤度/估值做折扣
    es = pd.to_numeric(d.get("entry_score", 0.0), errors="coerce").fillna(0.0).clip(0,1)
    pos = (0.02 + es * 0.10) * (0.65 + 0.35 * mp) * (0.85 + 0.15 * (1.0 - info))
    d["position_pct"] = pos.clip(0.01, 0.12).round(4)

    # 简易止损：8%（可在模拟仓里自定义）
    d["stop_loss_pct"] = 0.08

    return d.sort_values("entry_score", ascending=False)
# ==========================================
# 3. 可视化绘图组件
# ==========================================

def plot_kline(code, freq='daily', title="K线图"):
    """绘制专业 K 线图 (日/周/月)"""
    df = ENGINE.get_kline(code, freq=freq, limit=120)
    if df.empty:
        st.warning(f"⚠️ {title}: 暂无数据")
        return
    
    # 计算均线
    df['MA5'] = df['close'].rolling(5).mean()
    df['MA20'] = df['close'].rolling(20).mean()

    # 创建子图 (上图K线，下图成交量)
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, 
                        vertical_spacing=0.03, row_heights=[0.7, 0.3])
    
    # K线主图
    fig.add_trace(go.Candlestick(
        x=df['date'], open=df['open'], high=df['high'], low=df['low'], close=df['close'], 
        name='K线', increasing_line_color='#eb5353', decreasing_line_color='#3bceac'
    ), row=1, col=1)
    
    # 均线
    fig.add_trace(go.Scatter(x=df['date'], y=df['MA5'], line=dict(color='orange', width=1), name='MA5'), row=1, col=1)
    fig.add_trace(go.Scatter(x=df['date'], y=df['MA20'], line=dict(color='#4e8cff', width=1), name='MA20'), row=1, col=1)
    
    # 成交量
    colors = ['#eb5353' if r.close >= r.open else '#3bceac' for i, r in df.iterrows()]
    fig.add_trace(go.Bar(x=df['date'], y=df['volume'], marker_color=colors, name='成交量'), row=2, col=1)
    
    # 布局优化
    fig.update_layout(
        xaxis_rangeslider_visible=False, 
        height=500, 
        margin=dict(l=10, r=10, t=30, b=10), 
        template="plotly_white",
        title=dict(text=title, font=dict(size=14))
    )
    st.plotly_chart(fig, width="stretch")

def plot_radar(scores: dict):
    """绘制因子评分雷达图"""
    if not scores: return
    
    categories = ['宏观/行业', '基本面', '技术面', '资金面', '情绪面', '风险控制']
    values = [
        scores.get('macro_industry', 0), scores.get('fundamental', 0),
        scores.get('technical', 0), scores.get('money_flow', 0),
        scores.get('sentiment', 0), scores.get('risk_control', 0)
    ]
    # 闭合雷达
    values.append(values[0])
    categories.append(categories[0])
    
    fig = go.Figure(data=go.Scatterpolar(
        r=values, theta=categories, fill='toself', 
        line_color='#4e8cff', fillcolor='rgba(78, 140, 255, 0.3)'
    ))
    fig.update_layout(
        polar=dict(radialaxis=dict(visible=True, range=[0, 10])), 
        showlegend=False, height=300, 
        margin=dict(t=20, b=20, l=40, r=40)
    )
    st.plotly_chart(fig, width="stretch")

# ==========================================
# 4. 主功能逻辑
# ==========================================

# ------------------------------------------------------------------
# 模式 A: 天网机会雷达 (Smart Radar) - 全域扫描
# ------------------------------------------------------------------
if mode == "☢️ 天网机会雷达 (Smart Radar)":
    
    # --- 情报与推演 ---
    c_intel, c_logic = st.columns([1, 1])
    with c_intel:
        st.subheader("1. 全网哨兵 (Intelligence)")
        if st.button("📡 启动宏观深搜", type="primary"):
            with st.status("正在扫描全网宏观与舆情...", expanded=True):
                st.write("抓取市场热榜...")
                hot_spots = ENGINE.get_market_hot_spots()
                st.write("分析宏观定调...")
                macro_rep = search_agent.analyze_macro_situation()
                st.session_state["macro_report"] = macro_rep
                st.session_state["raw_intel"] = "\n".join(hot_spots) + "\n" + macro_rep.get("core_logic", "")
                st.success("情报搜集完成")
                st.rerun()

        if "raw_intel" in st.session_state:
            with st.expander("查看原始情报池"): st.text(st.session_state["raw_intel"])

    with c_logic:
        st.subheader("2. 辐射推演 (Radiation)")
        if st.button("🧠 激活辐射引擎", disabled="raw_intel" not in st.session_state):
            with st.spinner("AI 正在构建产业链图谱..."):
                rad_res = rad_engine.infer_opportunities(st.session_state.get("raw_intel", ""))
                st.session_state["rad_res"] = rad_res
    
    if "rad_res" in st.session_state:
        res = st.session_state["rad_res"]
        st.success(f"🎯 核心主线: {res.get('core_theme')} | 战略理由: {res.get('strategy_rationale')}")

    # --- 扫描与共振 ---
    st.markdown("---")
    st.subheader("3. 定向爆破与共振 (Blast & Fuse)")
    
    c_scan1, c_scan2 = st.columns([1, 3])
    with c_scan1:
        # 完整的全域策略池
        pool_options = {
            "🌍 全A股 (机会总览)": "all_a_shares",
            "🏆 核心资产 (Top100)": "core_assets_top100",
            "🏦 机构重仓 (Top300)": "institutional_top300",
            "🚀 创业板特攻 (30开头)": "growth_gem",
            "🐘 主板蓝筹 (60/00/002)": "sh_main_board", 
            "✨ 小市值逆向 (博弈)": "small_cap_contrarian"
        }
        sel_label = st.selectbox("🎯 选择战略底池", list(pool_options.keys()))
        pool_id = pool_options[sel_label]
        
        top_n = st.slider("显示数量", 10, 200, 50)
        
        if st.button("🚀 发射信号熔断器", type="primary"):
            target_concepts = st.session_state.get("rad_res", {}).get("target_concepts", [])
            
            with st.status("执行多维扫描...", expanded=True):
                st.write(f"正在扫描 {sel_label}...")
                config = ScanConfig(target_concepts=target_concepts)
                df_scan, _ = SCANNER.scan_cached(pool_id, config, cache_ttl=0)
                
                st.write("Fuser: 执行时间轴对齐 + 宏观否决...")
                df_final = FUSER.fuse_signals(
                    market_df=df_scan,
                    macro_report=st.session_state.get("macro_report", {}),
                    logic_report=st.session_state.get("rad_res", {}),
                    hot_sentiment_stocks=[]
                )

                st.write("SlowFactors: computing policy/demand/substitution/pricing/info...")
                try:
                    df_final = SLOW.enrich_market_df(
                        df_final,
                        engine=ENGINE,
                        macro_report=st.session_state.get("macro_report", {}),
                        logic_report=st.session_state.get("rad_res", {}),
                        hotlist=[],
                        as_of=None,
                        topk=min(150, len(df_final))
                    )
                except Exception as _e:
                    # do not crash UI
                    pass

                df_final = compute_entry_scores(df_final)
                st.session_state["fused_result"] = df_final
                st.success("扫描完成")

    with c_scan2:
        if "fused_result" in st.session_state:
            df_res = st.session_state["fused_result"]
            st.success(f"🏆 最终入围: {len(df_res)} 只")
            
            # 格式化展示
            # 格式化展示（动态列，避免 length mismatch）
            cols = []
            labels = []
            def add(c, l):
                if c in df_res.columns:
                    cols.append(c)
                    labels.append(l)
            add("code", "代码")
            add("name", "名称")
            add("sector", "行业")
            add("close", "现价")
            add("score", "量化分")
            add("fused_score", "⚡共振分")
            add("slow_score", "🐢慢变量")
            add("learned_score", "🧠权重分")
            add("fundamental_quality", "🏦财报质")
            add("fundamental_growth", "📊财报增")
            add("ops_momentum", "🛰️运营动")
            add("entry_score", "✅建仓分")
            add("slow_evidence", "证据(简)")
            disp = df_res[cols].head(top_n).copy() if cols else df_res.head(top_n).copy()
            if cols:
                disp.columns = labels
            _safe_dataframe(disp, width="stretch")

            
            # 深度审计入口
            st.divider()
            c_audit1, c_audit2 = st.columns([3, 1])
            sel_code = c_audit1.selectbox("🔍 选择标的进行深度博弈", disp["代码"].head(20).tolist())
            if c_audit2.button("呼叫 AI 审计该股"):
                with st.spinner("AI 正在撰写深度研报..."):
                    dp = _safe_holistic(ENGINE, sel_code)
                    dp['radiation_context'] = st.session_state.get("rad_res")
                    report = ai_advisor.get_ai_strategy(dp, ds_key)
                    st.json(report)

# ------------------------------------------------------------------
# 模式 B: 单股深度博弈 (Deep Game) - 核心展示区
# ------------------------------------------------------------------
elif mode == "🔎 单股深度博弈 (Deep Game)":
    st.subheader("🔎 单标的显微镜 (Deep Microscope)")
    
    # 输入区
    c_in1, c_in2 = st.columns([3, 1])
    code_input = c_in1.text_input("输入代码 (如 000801)", "000801")
    
    if c_in2.button("🚀 启动博弈", type="primary"):
        if not ds_key:
            st.error("请先在左侧配置 API Key")
        else:
            with st.spinner("全息数据扫描 + AI 多重人格博弈中..."):
                dp = _safe_holistic(ENGINE, code_input)
                report = ai_advisor.get_ai_strategy(dp, ds_key)
                st.session_state['report'] = report
                st.session_state['dp'] = dp

    # 结果展示区
    if 'report' in st.session_state:
        rep = st.session_state['report']
        dp = st.session_state['dp']
        news_bundle = dp.get("news_bundle") if isinstance(dp, dict) else {}
        meta_map = _as_dict(_as_dict(dp).get("_meta"))
        quote_meta = _as_dict(meta_map.get("quote"))
        identity_meta = _as_dict(meta_map.get("identity"))
        kline_meta = _as_dict(meta_map.get("kline"))
        fin_meta = _as_dict(meta_map.get("financial"))
        money_meta = _as_dict(meta_map.get("money_flow"))
        alt_meta = _as_dict(meta_map.get("alternative"))
        news_meta = _as_dict(meta_map.get("news_bundle"))
        ann_meta = _as_dict(meta_map.get("announcements"))

        # 1. 核心决策头 (Header)
        st.markdown("---")
        id_name = (dp.get('identity') or {}).get('name') or dp.get('code')
        sector = (dp.get('identity') or {}).get('sector', '') or '-'
        st.markdown(f"### {id_name} ({dp.get('code')}) | <span class='tag-concept'>{sector}</span>", unsafe_allow_html=True)

        c_h1, c_h2, c_h3, c_h4 = st.columns(4)
        dp = _as_dict(dp)
        md = _as_dict(dp.get('market_data'))
        raw_close = md.get('price') if md.get('price') not in (None, "", "--") else md.get('close')
        pct_delta = _fmt_val(md.get('pct') or md.get('pct_chg'), suffix="%")

        def _valid_float(val: Any) -> Optional[float]:
            try:
                f = float(val)
                if np.isnan(f) or np.isinf(f):
                    return None
                return f
            except Exception:
                return None

        derived_close, derived_date = (None, None)
        close_for_display = raw_close
        if _valid_float(close_for_display) is None:
            derived_close, derived_date = _extract_latest_close(dp.get('kline_daily') or dp.get('kline'))
            if derived_close is not None:
                close_for_display = derived_close

        c_h1.metric("现价", _fmt_val(close_for_display), pct_delta)
        if derived_close is not None:
            latest_date = derived_date or "未知"
            c_h1.caption(f"非实时：使用最近收盘价 {latest_date}")
        elif quote_meta:
            source_badge = quote_meta.get('source') or '-'
            c_h1.caption(f"行情源: {source_badge}")
        c_h2.metric("AI 综合评分", _fmt_val(rep.get('ai_score')))
        st.caption(
            f"行情源: {quote_meta.get('source') or '-'} | K线源: {kline_meta.get('source') or '-'} | 财报源: {fin_meta.get('source') or '-'} | 公告源: {ann_meta.get('source') or '-'}"
        )

        # deterministic 投研结论卡
        try:
            decision_bundle = build_decision(dp)
        except Exception:
            decision_bundle = {}
        decision_card = decision_bundle.get("decision_card", {}) if isinstance(decision_bundle, dict) else {}
        st.markdown("### 🧭 投研结论卡")
        c_dec1, c_dec2, c_dec3, c_dec4 = st.columns([1.4, 1, 1, 1])
        verdict = decision_card.get("verdict", "WATCH")
        horizon = decision_card.get("horizon", "1m")
        dq_score = decision_card.get("data_quality_score", 0)
        position_pct = decision_card.get("position_sizing_pct", 0)
        c_dec1.metric("结论", verdict)
        c_dec2.metric("持有周期", horizon)
        c_dec3.metric("数据质量", f"{dq_score}/100")
        c_dec4.metric("建议仓位", f"{position_pct}%")

        def _render_bullets(label: str, items):
            st.markdown(f"**{label}**")
            if not items:
                st.caption("insufficient evidence")
                return
            for it in items:
                st.markdown(f"- {it}")

        _render_bullets("核心论据", decision_card.get("thesis", []))
        _render_bullets("关键风险", decision_card.get("risks", []))
        _render_bullets("触发条件", decision_card.get("triggers", []))
        _render_bullets("反证清单", decision_card.get("disconfirming_checklist", []))

        with st.expander("数据质量与缺口"):
            missing_notes = decision_card.get("missing_notes", []) or ["无"]
            for note in missing_notes:
                st.markdown(f"- {note}")
            ev_map = decision_card.get("evidence_map") or {}
            if ev_map:
                st.caption("证据索引")
                for key, val in ev_map.items():
                    st.text(f"{key}: {val.get('summary')}")

        # 决策高亮
        decision = rep.get('decision', '观望')
        color_cls = "decision-buy" if "买" in decision or "潜伏" in decision else "decision-sell" if "卖" in decision or "清" in decision else ""
        c_h3.markdown(f"**决策: <span class='{color_cls}'>{decision}</span>**", unsafe_allow_html=True)
        mc_val = md.get('market_cap')
        mc_display = _fmt_val(mc_val, suffix="亿") if mc_val not in (None, "", 0) else "—"
        c_h4.metric("市值", mc_display)

        advice = _as_dict(dp.get("advice"))
        if advice:
            st.info(f"规则建议：{advice.get('action', '观望')}")
            ev_list = advice.get("evidence") or []
            if isinstance(ev_list, list):
                for ev in ev_list:
                    ref = _as_dict(ev).get("ref") or ""
                    summary = _as_dict(ev).get("summary") or ""
                    url = _as_dict(ev).get("url") or ""
                    prefix = f"[{ref}] " if ref else ""
                    if url:
                        st.markdown(f"- {prefix}[{summary}]({url})")
                    else:
                        st.markdown(f"- {prefix}{summary}")

        with st.expander("🩺 数据链路诊断"):
            diag_rows = []
            for key, label, meta in [
                ("quote", "行情", quote_meta),
                ("identity", "身份", identity_meta),
                ("kline", "K线", kline_meta),
                ("financial", "财务", fin_meta),
                ("money_flow", "资金", money_meta),
                ("alternative", "情报", alt_meta),
                ("news_bundle", "情报流", news_meta),
            ]:
                safe_meta = _as_dict(meta)
                diag_rows.append({
                    "module": label,
                    "source": safe_meta.get("source") or "—",
                    "fallback_used": safe_meta.get("fallback_used") or False,
                    "cache_hit": safe_meta.get("cache_hit") or False,
                    "ttl_sec": safe_meta.get("ttl_sec") or "—",
                    "retrieved_at": _fmt_ts(safe_meta.get("retrieved_at") or safe_meta.get("ts")),
                    "filled": _filled_from_meta(safe_meta) or "—",
                    "errors_count": _errors_count(safe_meta.get("errors")),
                })
            if diag_rows:
                pd = _get_pandas()
                if pd is not None:
                    _safe_dataframe(pd.DataFrame(diag_rows), width="stretch")
                else:
                    st.table(diag_rows)
            for label, meta in [
                ("行情", quote_meta),
                ("身份", identity_meta),
                ("K线", kline_meta),
                ("财务", fin_meta),
                ("资金", money_meta),
                ("情报", alt_meta),
                ("情报流", news_meta),
            ]:
                meta = meta or {}
                if meta.get("errors"):
                    st.markdown(f"**{label}错误详情:**")
                    _render_errors(meta.get("errors"))

        with st.expander("🐞 调试/原始数据", expanded=False):
            st.caption("single_stock payload (normalized)")
            try:
                st.json({k: v for k, v in dp.items() if k != "provider_trace"})
            except Exception:
                st.json(str(dp))
            st.caption("provider_trace")
            try:
                st.json(dp.get("provider_trace"))
            except Exception:
                st.write("provider_trace unavailable")

        # 2. 分页展示 (Tabs)
        tab_dash, tab_kline, tab_logic, tab_fund = st.tabs(["📊 战术看板", "📈 K线图表", "🧠 逻辑拆解", "💰 财务/资金"])

        # --- Tab 1: 战术看板 (Dashboard) ---
        with tab_dash:
            st.markdown("#### 行情/身份概览")
            col_q, col_id = st.columns(2)
            with col_q:
                price = md.get('close') or md.get('price')
                pct = md.get('pct') or md.get('pct_chg')
                if price is None:
                    derived_px, derived_dt = _extract_latest_close(dp.get('kline_daily') or dp.get('kline'))
                    price = derived_px
                    if derived_px is not None:
                        st.caption(f"(非实时：使用最近收盘价 {derived_dt or '未知'})")
                st.metric("现价", price if price is not None else "-", f"{pct}%" if pct is not None else None)
                st.write(f"成交额: {md.get('amount') or '-'} | 量比: {md.get('vol_ratio') or '-'}")
                st.caption(
                    f"行情来源: {quote_meta.get('source') or '-'} | 报价: {'非实时(收盘价)' if quote_meta.get('latest_price_non_realtime') else '实时'} | 推导: {'是' if quote_meta.get('is_derived') else '否'}"
                )
                _render_meta(quote_meta)
                if not quote_meta.get("ok"):
                    _render_errors(quote_meta.get("errors"))
            with col_id:
                st.write(f"行业: {sector or '-'}")
                concepts = (dp.get('identity') or {}).get('concepts') or []
                st.write("概念: " + ("，".join(concepts) if concepts else "-"))
                _render_meta(identity_meta)
                if not identity_meta.get("ok"):
                    _render_errors(identity_meta.get("errors"))

            st.markdown("---")
            # 1. 核心结论 (The Setup)
            st.markdown(f"<div class='logic-box'><b>⚡ 短线逻辑 (The Setup)</b><br>{rep.get('setup_logic')}</div>", unsafe_allow_html=True)
            
            c_d1, c_d2 = st.columns([1, 1])
            with c_d1:
                st.markdown("#### 因子雷达评分")
                plot_radar(rep.get('scores', {}))
                
                # 风险提示
                st.warning(f"🛡️ **风险视角**: {rep.get('risk_warning')}")
                st.success(f"🔥 **强催化剂**: {rep.get('catalyst')}")

            with c_d2:
                # 行动计划
                plan = rep.get('action_plan', {})
                st.markdown("#### 🔫 战术行动计划 (Action)")
                
                st.write(f"**策略**: {plan.get('strategy')}")
                
                c_a1, c_a2 = st.columns(2)
                c_a1.error(f"🔴 卖点/压力: {plan.get('sell_point')}")
                c_a1.error(f"🛑 止损位: {plan.get('stop_loss')}")
                c_a2.success(f"🟢 买点/支撑: {plan.get('buy_point')}")
                c_a2.info(f"⚖️ **持仓建议**: {plan.get('position_advice')}")

        # --- Tab 2: K线图表 (Charts) ---
        with tab_kline:
            st.caption("支持滚轮缩放与拖拽")
            col_k1, col_k2, col_k3 = st.columns(3)
            kline_code = dp.get('code') or code_input
            kline_df = dp.get("kline_daily_df") if _get_pandas() is not None else None
            if kline_df is not None and hasattr(kline_df, "empty") and not kline_df.empty:
                try:
                    df_plot = kline_df.copy().tail(240)
                    for target in [col_k1, col_k2, col_k3]:
                        with target:
                            plot_df = df_plot if target is col_k1 else df_plot
                            fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=[0.7, 0.3])
                            fig.add_trace(go.Candlestick(
                                x=plot_df['date'], open=plot_df['open'], high=plot_df['high'], low=plot_df['low'], close=plot_df['close'],
                                name='K线', increasing_line_color='#eb5353', decreasing_line_color='#3bceac'
                            ), row=1, col=1)
                            ma5 = plot_df['close'].rolling(5).mean()
                            ma20 = plot_df['close'].rolling(20).mean()
                            fig.add_trace(go.Scatter(x=plot_df['date'], y=ma5, line=dict(color='orange', width=1), name='MA5'), row=1, col=1)
                            fig.add_trace(go.Scatter(x=plot_df['date'], y=ma20, line=dict(color='#4e8cff', width=1), name='MA20'), row=1, col=1)
                            colors = ['#eb5353' if r.close >= r.open else '#3bceac' for _, r in plot_df.iterrows()]
                            fig.add_trace(go.Bar(x=plot_df['date'], y=plot_df['volume'], marker_color=colors, name='成交量'), row=2, col=1)
                            fig.update_layout(xaxis_rangeslider_visible=False, height=500, margin=dict(l=10, r=10, t=30, b=10), template="plotly_white")
                            st.plotly_chart(fig, use_container_width=True)
                except Exception:
                    plot_kline(kline_code, 'daily', "日线 (Daily)")
            elif not kline_code:
                st.warning("暂无代码，无法绘制 K 线")
            else:
                with col_k1:
                    plot_kline(kline_code, 'daily', "日线 (Daily)")
                with col_k2:
                    plot_kline(kline_code, 'weekly', "周线 (Weekly)")
                with col_k3:
                    plot_kline(kline_code, 'monthly', "月线 (Monthly)")
            _render_meta(kline_meta)
            if not (kline_meta or {}).get("ok"):
                _render_errors((kline_meta or {}).get("errors"))

        # --- Tab 3: 深度逻辑 (Logic) ---
        with tab_logic:
            body = rep.get('analysis_body', {})

            c_l1, c_l2 = st.columns(2)
            with c_l1:
                st.markdown("#### 🏛️ 宏观与行业 (Macro & Industry)")
                st.info(body.get('macro_policy', '无数据'))

                st.markdown("#### 🏭 基本面与技术 (Fundamental & Tech)")
                st.info(body.get('industry_tech', '无数据'))

            with c_l2:
                st.markdown("#### 💸 资金与博弈 (Money & Game)")
                st.warning(body.get('funds_sentiment', '无数据'))

                st.markdown("#### 🗣️ 舆情与情绪 (Sentiment)")
                sent = dp.get('alternative_intelligence') or {}
                st.write(f"散户情绪分: {_fmt_val(sent.get('retail_sentiment'))}")
                st.text(f"股吧样本: {sent.get('raw_guba_sample')}")
                _render_meta(alt_meta)
                if not (alt_meta or {}).get("ok"):
                    _render_errors((alt_meta or {}).get("errors"))

            st.divider()
            st.markdown("#### 📡 情报流 (公告 / 研报 / 热点 / 论坛)")
            ann_list = dp.get("announcements") or []
            ann_trace = (_as_dict(dp.get("provider_trace")) or {}).get("announcements") or []
            ann_errors = []
            for tr in ann_trace:
                ann_errors.extend(_as_dict(tr).get("errors", []))
            if ann_list:
                st.markdown(f"**公告 ({len(ann_list)})**")
                pd = _get_pandas()
                if pd is not None:
                    df_ann = pd.DataFrame(ann_list)
                    cols = [c for c in ["title", "time", "source", "url"] if c in df_ann.columns]
                    _safe_dataframe(df_ann[cols] if cols else df_ann, width="stretch")
                else:
                    st.table(ann_list)
            else:
                st.info("暂无公告/公告抓取失败")
                if ann_errors:
                    _render_errors(ann_errors)
            nb = news_bundle if isinstance(news_bundle, dict) else {}
            for key, label in [
                ("announcements", "公告"),
                ("reports", "研报"),
                ("hot_events", "热点"),
                ("forums", "股吧"),
                ("opinions", "观点"),
            ]:
                items = nb.get(key) or []
                if not items:
                    continue
                st.markdown(f"**{label} ({len(items)})**")
                pd = _get_pandas()
                if pd is not None:
                    df_temp = pd.DataFrame(items)
                    cols = [c for c in ["title", "time", "source", "url", "summary"] if c in df_temp.columns]
                    _safe_dataframe(df_temp[cols].head(5), width="stretch")
                else:
                    st.table(items[:5])
            _render_meta(news_meta)
            if not (news_meta or {}).get("ok"):
                _render_errors((news_meta or {}).get("errors"))

        # --- Tab 4: 财务与资金 (Fundamentals) ---
        with tab_fund:
            fin = dp.get('financials') or {}
            c_f1, c_f2, c_f3, c_f4 = st.columns(4)
            c_f1.metric("ROE", _fmt_val(fin.get('roe'), suffix="%"))
            c_f2.metric("毛利率", _fmt_val(fin.get('gross_margin'), suffix="%"))
            c_f3.metric("利润增长", _fmt_val(fin.get('profit_yoy'), suffix="%"))
            c_f4.metric("营收增长", _fmt_val(fin.get('revenue_yoy'), suffix="%"))
            st.write(f"报告期: {_fmt_val(fin.get('report_date'))}")
            pd = _get_pandas()
            if pd is not None and fin:
                df_fin = pd.DataFrame([fin]).T.reset_index()
                df_fin.columns = ["字段", "值"]
                _safe_dataframe(df_fin, width="stretch")
            _render_meta(fin_meta)
            if not (fin_meta or {}).get("ok"):
                _render_errors((fin_meta or {}).get("errors"))

            st.markdown("---")
            money = dp.get('money_flow') or {}
            st.metric("今日主力净流入", _fmt_val(money.get('main_net_inflow_today'), suffix=" 万"))
            st.write(f"北向: {_fmt_val(money.get('north_money_net'))} | 两融: {_fmt_val(money.get('margin_balance_delta'))}")
            _render_meta(money_meta)
            if not (money_meta or {}).get("ok"):
                _render_errors((money_meta or {}).get("errors"))
            st.caption("注：财务/资金均展示来源与兜底信息，失败时可据 errors 快速定位。")


# ------------------------------------------------------------------
# 模式 C: 策略回测
# ------------------------------------------------------------------

elif mode == "📦 模拟仓 (Paper Portfolio)":
    st.header("📦 模拟仓｜沙盘跑一圈（不下单）")
    st.caption("用途：把【天网雷达/AI推荐】转成可验证的“沙盘收益曲线”，快速暴露追高/回撤/换手成本问题。")

    source = st.radio("候选池来源", ["使用上一次天网雷达结果", "手动输入代码列表"], horizontal=True)
    cand_codes = []
    if source == "使用上一次天网雷达结果":
        df_last = st.session_state.get("fused_result")
        if df_last is None or getattr(df_last,'empty',True):
            st.warning("还没有天网雷达结果。请先运行一次【天网机会雷达】。")
        else:
            dtmp = df_last.copy()
            # 优先使用 entry_score，否则使用 fused_score/score
            if "entry_score" not in dtmp.columns:
                dtmp = compute_entry_scores(dtmp)
            dtmp = dtmp.sort_values("entry_score", ascending=False)
            topn = st.slider("候选池规模（用于模拟）", 20, 200, 80, step=10)
            cand_codes = [normalize_code(x) for x in dtmp.head(topn)["code"].tolist()]
            st.write(f"候选池：{len(cand_codes)} 只")
    else:
        raw = st.text_area("输入代码（逗号/空格/换行分隔）", value="", height=120)
        cand_codes = [normalize_code(x) for x in re.split(r"[\s,;]+", raw.strip()) if x.strip()]
        st.write(f"候选池：{len(cand_codes)} 只")

    c1, c2, c3 = st.columns(3)
    with c1:
        start = st.date_input("开始日期", value=datetime.fromisoformat("2023-01-01").date())
    with c2:
        end = st.date_input("结束日期", value=datetime.today().date())
    with c3:
        initial_cash = st.number_input("初始资金", min_value=10000, value=1000000, step=10000)

    c4, c5, c6 = st.columns(3)
    with c4:
        top_k = st.slider("持仓数量（Top-K）", 5, 50, 20, step=1)
    with c5:
        rebalance = st.selectbox("调仓频率", ["W", "M"], index=0, help="W=每周，M=每月")
    with c6:
        stop_loss = st.slider("止损（%）", 1, 25, 8, step=1) / 100.0

    take_profit = st.slider("止盈（%）", 5, 80, 25, step=1) / 100.0

    run_btn = st.button("▶️ 开始模拟", type="primary", disabled=(len(cand_codes) < 2))

    if run_btn:
        with st.spinner("模拟仓回放中…（会拉取历史K线）"):
            res = simulate_paper_portfolio(
                engine=ENGINE,
                candidates=cand_codes,
                start=str(start),
                end=str(end),
                top_k=int(top_k),
                rebalance=rebalance,
                initial_cash=float(initial_cash),
                stop_loss=float(stop_loss),
                take_profit=float(take_profit),
            )

        if not res.get("ok"):
            st.error(res.get("msg") or "模拟失败")
        else:
            metrics = res.get("metrics") or {}
            colm = st.columns(4)
            colm[0].metric("总收益", f"{metrics.get('total_return',0)*100:.2f}%")
            colm[1].metric("年化", f"{metrics.get('annual_return',0)*100:.2f}%")
            colm[2].metric("最大回撤", f"{metrics.get('max_drawdown',0)*100:.2f}%")
            colm[3].metric("换手次数", f"{metrics.get('n_trades',0)}")

            curve = res.get("equity_curve")
            if curve is not None and not curve.empty:
                fig = go.Figure()
                fig.add_trace(go.Scatter(x=curve["date"], y=curve["equity"], mode="lines", name="Equity"))
                fig.update_layout(height=360, margin=dict(l=10,r=10,t=30,b=10), xaxis_title="Date", yaxis_title="Equity")
                st.plotly_chart(fig, width="stretch")

            trades = res.get("trades")
            if trades is not None and not getattr(trades, "empty", True):
                st.subheader("交易记录")
                _safe_dataframe(trades, width="stretch", height=320)

            pos = res.get("positions")
            if pos is not None and len(pos):
                st.subheader("期末持仓")
                pd = _get_pandas()
                if pd is not None:
                    _safe_dataframe(pd.DataFrame(pos).sort_values("weight", ascending=False), width="stretch", height=260)
                else:
                    st.table(pos)

elif mode == "📊 策略回测 (Time Machine)":
    st.title("📊 五维超脑·时光机")
    st.caption("把因子体系做成可验证闭环：回测 → 学权重 → 反哺建仓清单。")

    t1, t2, t3 = st.tabs(["单股回测", "权重学习", "因子组合回测"])

    with t1:
        st.subheader("单股回测")
        try:
            from backtest_runner import BacktestRunner
        except Exception as e:
            st.error(f"❌ 未检测到 backtest_runner.py 或导入失败：{e}")
            BacktestRunner = None

        c1, c2, c3, c4 = st.columns(4)
        bt_code = c1.text_input("回测标的", "600519")
        bt_start = c2.date_input("开始日期", value=datetime.fromisoformat("2023-01-01").date())
        bt_end = c3.date_input("结束日期", value=datetime.fromisoformat("2023-12-31").date())
        bt_cash = c4.number_input("初始资金", value=100000)

        if st.button("🔴 启动单股回测", type="primary"):
            if BacktestRunner is None:
                st.stop()
            if not ds_key:
                st.error("请先在左侧配置 DeepSeek Key")
                st.stop()
            runner = BacktestRunner(
                code=bt_code,
                start_date=str(bt_start),
                end_date=str(bt_end),
                initial_cash=bt_cash,
                api_key=ds_key,
            )
            with st.status("时光倒流中...", expanded=True):
                runner.run()
            if getattr(runner, 'history', None):
                pd = _get_pandas()
                history = runner.history
                if pd is not None:
                    df_res = pd.DataFrame(history)
                    _safe_dataframe(df_res, width="stretch")
                    if 'date' in df_res.columns and 'total' in df_res.columns:
                        st.line_chart(df_res.set_index('date')['total'])
                else:
                    st.table(history)

    with t2:
        st.subheader("权重学习 (Ridge Regression)")
        st.caption("从历史因子 + 未来收益里学出权重，用于 Smart Radar 的建仓清单评分。")

        if learn_weights is None:
            st.error("缺少 weight_learner.py / step4_backtest.py：请更新到 Step4 包。")
        else:
            colA, colB, colC, colD = st.columns(4)
            f_start = colA.text_input("样本开始", "2023-01-01")
            f_end = colB.text_input("样本结束", datetime.today().strftime("%Y-%m-%d"))
            horizon = int(colC.number_input("预测周期(天)", value=5, min_value=1, max_value=60))
            l2 = float(colD.number_input("L2强度(Ridge)", value=10.0, min_value=0.0))

            colE, colF = st.columns(2)
            factor_path = colE.text_input("因子库路径", ".w5brain_cache/factors/slow_factors_store.parquet")
            weights_path = colF.text_input("权重输出路径", ".w5brain_weights.json")

            if st.button("🧠 开始训练权重"):
                with st.spinner("训练中...（会拉取历史K线计算未来收益）"):
                    model = learn_weights(
                        engine=ENGINE,
                        factor_db_path=factor_path,
                        start=f_start,
                        end=f_end,
                        horizon=horizon,
                        l2=l2,
                    )
                if not model.get('ok'):
                    st.error(model.get('msg', '训练失败'))
                else:
                    st.success(f"训练完成：样本数 {model.get('n_samples')} | Spearman IC {model.get('ic_spearman'):.3f}")
                    st.json({k: model.get(k) for k in ['horizon','l2','n_samples','ic_spearman','weights']})
                    ok, msg = save_weights(model, path=weights_path)
                    (st.success if ok else st.error)(msg)

            st.markdown("---")
            st.markdown("**当前已加载权重（若存在）**")
            cur = load_weights(weights_path)
            if cur:
                st.json({k: cur.get(k) for k in ['saved_at','horizon','ic_spearman','weights']})
            else:
                st.info("未检测到权重文件，先训练一次即可。")

    with t3:
        st.subheader("因子组合回测（TopK 等权）")
        if run_factor_backtest is None:
            st.error("缺少 step4_backtest.py：请更新到 Step4 包。")
        else:
            c1, c2, c3, c4, c5 = st.columns(5)
            bt_start2 = c1.text_input("开始", "2023-01-01")
            bt_end2 = c2.text_input("结束", datetime.today().strftime("%Y-%m-%d"))
            horizon2 = int(c3.number_input("持有(天)", value=5, min_value=1, max_value=60))
            topk = int(c4.number_input("TopK", value=20, min_value=5, max_value=100))
            reb = c5.selectbox("调仓", ["W", "D", "M"], index=0)

            colE, colF = st.columns(2)
            factor_path2 = colE.text_input("因子库路径(回测)", ".w5brain_cache/factors/slow_factors_store.parquet", key="factor_path_bt")
            weights_path2 = colF.text_input("权重文件(回测)", ".w5brain_weights.json", key="weights_path_bt")

            if st.button("🚀 启动因子回测"):
                with st.spinner("回测中..."):
                    out = run_factor_backtest(
                        engine=ENGINE,
                        factor_db_path=factor_path2,
                        weights_path=weights_path2,
                        start=bt_start2,
                        end=bt_end2,
                        horizon=horizon2,
                        topk=topk,
                        rebalance=reb,
                    )
                if not out.get('ok'):
                    st.error(out.get('msg', '回测失败'))
                else:
                    st.success(f"完成：总收益 {out.get('total_return'):.2%} | CAGR≈ {out.get('cagr_approx'):.2%} | MDD {out.get('max_drawdown'):.2%} | 胜率 {out.get('win_rate'):.2%}")
                    curve = out.get('curve')
                    pd = _get_pandas()
                    if pd is not None and isinstance(curve, pd.DataFrame) and not curve.empty:
                        _safe_dataframe(curve, width="stretch")
                        if 'date' in curve.columns and 'equity' in curve.columns:
                            st.line_chart(curve.set_index('date')['equity'])
                    elif curve:
                        st.table(curve)
