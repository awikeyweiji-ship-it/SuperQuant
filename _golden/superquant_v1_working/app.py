# -*- coding: utf-8 -*-
"""
app.py
======
五维超脑控制台 (Commercial Pro V4.0)

【修复与升级日志】
1. 修复 ImportError: 增加对 matplotlib 的兼容性检查，防止因缺少库导致页面崩溃。
2. 实装 [全市场上帝视角]: 
   - 先用量化算法毫秒级遍历 5000+ 只股票。
   - 筛选出高分 Top N 给 AI 深度审计。
   - 最后生成 [买卖机会汇总报告]。
"""

import os
import time
import pandas as pd
import streamlit as st
import plotly.graph_objects as go

# 引入核心模块
from universe_cache import UniverseCache
from data_engine import DataEngine, normalize_code
from market_scanner import MarketScanner, ScanConfig
import ai_advisor

# ==========================================
# 1. 页面初始化配置
# ==========================================
st.set_page_config(
    page_title="五维超脑 | 顶级博弈控制台",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 自定义 CSS
st.markdown("""
<style>
    .stMetric {
        background-color: #f8f9fa;
        padding: 10px;
        border-radius: 5px;
        border-left: 5px solid #ff4b4b;
        box-shadow: 1px 1px 3px rgba(0,0,0,0.1);
    }
    .strategy-box {
        padding: 15px;
        background-color: #e6f3ff;
        border-radius: 5px;
        margin-bottom: 20px;
        border: 1px solid #b3d7ff;
    }
    .report-box {
        padding: 20px;
        background-color: #f0fff4;
        border: 1px solid #c6f6d5;
        border-radius: 8px;
        margin-top: 20px;
    }
</style>
""", unsafe_allow_html=True)

# ==========================================
# 2. 核心引擎加载
# ==========================================
if "cache" not in st.session_state:
    st.session_state["cache"] = UniverseCache()
if "engine" not in st.session_state:
    st.session_state["engine"] = DataEngine(cache=st.session_state["cache"])
if "scanner" not in st.session_state:
    st.session_state["scanner"] = MarketScanner(engine=st.session_state["engine"], cache=st.session_state["cache"])

CACHE: UniverseCache = st.session_state["cache"]
ENGINE: DataEngine = st.session_state["engine"]
SCANNER: MarketScanner = st.session_state["scanner"]

# ==========================================
# 3. 辅助显示函数 (防崩版)
# ==========================================
def fmt_val(val, suffix=""):
    if val is None or val == "NULL" or pd.isna(val):
        return "--"
    try:
        if isinstance(val, str) and any(c in val for c in "亿万元"): return val
        f = float(val)
        return f"{f:.2f}{suffix}"
    except: return str(val)

def safe_dataframe(df):
    """
    安全渲染 DataFrame，如果没有 matplotlib 则只渲染普通表格
    """
    try:
        import matplotlib
        st.dataframe(
            df.style.background_gradient(subset=["AI评分"], cmap="RdYlGn", vmin=0, vmax=1),
            use_container_width=True
        )
    except ImportError:
        # 降级处理
        st.dataframe(df, use_container_width=True)
    except Exception:
        st.dataframe(df, use_container_width=True)

def render_kline(df: pd.DataFrame, title: str):
    if df is None or df.empty:
        st.caption(f"⚠️ {title}: 暂无数据")
        return
    
    df['MA5'] = df['close'].rolling(5).mean()
    df['MA20'] = df['close'].rolling(20).mean()

    fig = go.Figure()
    fig.add_trace(go.Candlestick(
        x=df['date'], open=df['open'], high=df['high'], low=df['low'], close=df['close'],
        name='K线'
    ))
    fig.add_trace(go.Scatter(x=df['date'], y=df['MA5'], mode='lines', name='MA5', line=dict(color='orange', width=1)))
    fig.add_trace(go.Scatter(x=df['date'], y=df['MA20'], mode='lines', name='MA20', line=dict(color='blue', width=1)))

    fig.update_layout(
        title=dict(text=title, font=dict(size=14)),
        yaxis_title="价格",
        height=400,
        margin=dict(l=5, r=5, t=30, b=5),
        xaxis_rangeslider_visible=False,
        template="plotly_white"
    )
    st.plotly_chart(fig, use_container_width=True)

# ==========================================
# 4. 侧边栏
# ==========================================
st.sidebar.markdown("## 🧠 五维超脑控制台")
st.sidebar.caption("DataEngine V3 | AI Advisor V2")

with st.sidebar.expander("🔑 DeepSeek 神经连接", expanded=True):
    if "api_key" not in st.session_state:
        st.session_state["api_key"] = os.getenv("DEEPSEEK_API_KEY", "")
    
    api_key_input = st.text_input("API Key", value=st.session_state["api_key"], type="password")
    st.session_state["api_key"] = api_key_input

    col_t, col_s = st.columns([1, 2])
    if col_t.button("测试"):
        if not api_key_input:
            st.error("Key 为空")
        else:
            with st.spinner("连通性测试中..."):
                res = ai_advisor.test_deepseek_connection(api_key_input)
                if res["success"]:
                    st.success("已连接")
                    st.toast("✅ 神经中枢连接正常")
                else:
                    st.error("失败")
                    st.error(res["msg"])

    deep_mode = st.toggle("深度思考模式", value=True)

st.sidebar.markdown("---")
mode = st.sidebar.radio(
    "作战模式",
    options=["🔎 单股深度博弈", "🚀 智能机会雷达 (Auto)", "🌐 全市场扫描 (Pro)", "📊 策略回测"],
    index=1, # 默认选中雷达
)

# ==========================================
# 5. 主界面逻辑
# ==========================================

# --- A. 单股分析 ---
if mode == "🔎 单股深度博弈":
    st.title("🔎 单股全息深度博弈")
    
    c1, c2 = st.columns([3, 1])
    code_input = c1.text_input("输入代码", "600519")
    do_run = c2.button("🚀 启动分析", type="primary", use_container_width=True)
    
    code = normalize_code(code_input)

    if do_run:
        with st.status("📡 全息数据链路建立中...", expanded=True) as status:
            st.write("正在接入交易所实时行情...")
            spot = ENGINE.get_spot_row(code, ttl_seconds=0)
            
            st.write("正在穿透 F10 财务摘要...")
            identity = ENGINE.get_stock_identity(code)
            fin = ENGINE.get_deep_financials(code)
            game = ENGINE.get_game_data(code)
            
            st.write("正在构建技术形态...")
            k_d = ENGINE.get_kline(code, "D", limit=150)
            k_w = ENGINE.get_kline(code, "W", limit=150)
            rag = ENGINE.get_report_rag(code, limit=3)

            status.update(label="✅ 数据采集完毕，五维超脑正在推理...", state="running")
            
            advice = ai_advisor.get_ai_advice(
                code=code, identity=identity, spot_row=spot,
                kline_d=k_d, kline_w=k_w, kline_m=None,
                financials=fin, game=game, rag_items=rag.get("items", []),
                api_key=st.session_state["api_key"], deep_mode=deep_mode
            )
            status.update(label="✅ 分析完成", state="complete", expanded=False)

        # 结果展示
        st.subheader(f"{identity.get('name')} ({code}) | {identity.get('sector')}")
        cols = st.columns(5)
        cols[0].metric("现价", fmt_val(spot.get("close")), f"{fmt_val(spot.get('pct'))}%")
        cols[1].metric("市值", f"{fmt_val(spot.get('market_cap'))} 亿")
        cols[2].metric("PE(动)", fmt_val(spot.get("pe")))
        cols[3].metric("AI 评分", advice.get("ai_score", 0))
        cols[4].metric("决策", advice.get("decision", "观望"))

        st.divider()

        if advice.get("summary"):
            for s in advice["summary"]:
                st.info(f"📌 {s}")
        
        t1, t2, t3 = st.tabs(["📊 深度逻辑", "📈 财务/资金", "🗞️ 舆情"])
        
        with t1:
            anl = advice.get("analysis", {})
            c_left, c_right = st.columns(2)
            with c_left:
                st.markdown("#### 🌍 宏观与基本面")
                st.write(anl.get("macro_industry", "--"))
                st.write(anl.get("fundamental", "--"))
            with c_right:
                st.markdown("#### 💰 资金与博弈")
                st.write(anl.get("technical_fund", "--"))
                if anl.get("risks"): st.error(f"⚠️ 风险: {'; '.join(anl['risks'])}")
                if anl.get("catalysts"): st.success(f"🚀 催化: {'; '.join(anl['catalysts'])}")
            st.warning(f"💡 **行动计划**: {advice.get('action_plan')}")

        with t2:
            st.markdown("#### 关键财务指标 (F10)")
            f_cols = st.columns(4)
            f_cols[0].metric("ROE", fmt_val(fin.get("roe"), "%"))
            f_cols[1].metric("净利同比", fmt_val(fin.get("profit_yoy"), "%"))
            f_cols[2].metric("营收同比", fmt_val(fin.get("rev_yoy"), "%"))
            f_cols[3].metric("主力净流", fmt_val(game.get("main_flow")))
            
            c_k1, c_k2 = st.columns(2)
            with c_k1: render_kline(k_d, "日线")
            with c_k2: render_kline(k_w, "周线")

        with t3:
            items = rag.get("items", [])
            if not items: st.caption("暂无近期重大资讯")
            for i in items:
                with st.expander(f"{i['time']} | {i['title']}"):
                    st.write(i.get('summary'))

# --- B. 智能雷达 (上帝视角版) ---
elif mode == "🚀 智能机会雷达 (Auto)":
    st.title("🚀 全市场 AI 机会扫描系统")
    
    STRATEGY_MAP = {
        "🌍 全 A 股市场 (机会总览)": "all_a_shares",
        "👑 核心资产 (市值 Top 100)": "core_assets_top100",
        "🏢 机构重仓 (市值 Top 300)": "institutional_top300",
        "🚀 创业板特攻 (30开头)": "growth_gem",
        "🏛️ 主板蓝筹 (60开头)": "main_board_bluechip",
        "❄️ 极致冷门/小市值 (博弈)": "small_cap_contrarian"
    }

    DESC_MAP = {
        "all_a_shares": "遍历全市场 5000+ 只股票，通过多因子量化模型筛选出综合得分最高的潜力股，再由 AI 逐一面试。",
        "core_assets_top100": "聚焦全市场市值最大的100只龙头股，适合稳健型配置。",
        "institutional_top300": "覆盖基金与机构重仓标的，流动性好，适合趋势交易。",
        "growth_gem": "专攻创业板 (300xxx) 高弹性标的，波动大，适合激进型策略。",
        "main_board_bluechip": "仅扫描沪市主板 (60xxxx)，寻找低估值蓝筹机会。",
        "small_cap_contrarian": "寻找市值最小的200只非ST标的，博弈壳资源或重组预期 (高风险)。"
    }

    c1, c2 = st.columns([2, 1])
    selected_name = c1.selectbox("选择选股策略", list(STRATEGY_MAP.keys()))
    pool_id = STRATEGY_MAP[selected_name]
    
    # 允许用户选择要让AI看多少只，太多了慢
    top_n = c2.slider("AI 深度审计数量 (Top N)", 1, 20, 5, help="量化初筛后，取前多少名交给 AI 进行深度分析")

    st.markdown(f"<div class='strategy-box'>📝 <b>策略逻辑：</b>{DESC_MAP[pool_id]}</div>", unsafe_allow_html=True)

    if st.button("🚀 启动上帝视角扫描", type="primary"):
        with st.status("🛸 正在遍历全市场...", expanded=True) as status:
            # 1. 量化扫描
            cfg = ScanConfig()
            if pool_id == "small_cap_contrarian":
                cfg.prefer_large_cap = -0.5
                cfg.max_market_cap_yi = 50

            # 这里的 scan_cached 已经在 market_scanner.py 里实现了对 all_a_shares 的支持
            df_scan, _ = SCANNER.scan_cached(pool_id, cfg, cache_ttl=300)
            
            if df_scan.empty:
                status.update(label="❌ 未找到符合条件的标的", state="error")
                st.stop()
            
            st.session_state["scan_results"] = df_scan
            status.update(label=f"✅ 遍历完成！锁定 {len(df_scan)} 只标的，正在派遣 AI 审计 Top {top_n}...", state="running")

            # 2. AI 审计
            picks = df_scan.head(top_n).copy()
            results = []
            
            prog = st.progress(0)
            for i, row in enumerate(picks.itertuples()):
                code = row.code
                st.write(f"正在审计 ({i+1}/{top_n}): {row.name} ({code})...")
                
                # 获取数据
                spot = ENGINE.get_spot_row(code)
                identity = ENGINE.get_stock_identity(code)
                fin = ENGINE.get_deep_financials(code)
                game = ENGINE.get_game_data(code)
                k_d = ENGINE.get_kline(code, "D", limit=100)
                rag = ENGINE.get_report_rag(code, limit=2)
                
                # AI 分析
                adv = ai_advisor.get_ai_advice(
                    code=code, identity=identity, spot_row=spot,
                    kline_d=k_d, kline_w=None, kline_m=None,
                    financials=fin, game=game, rag_items=rag.get("items", []),
                    api_key=st.session_state["api_key"], deep_mode=False
                )
                
                results.append({
                    "代码": code,
                    "名称": row.name,
                    "现价": spot.get("close"),
                    "AI评分": adv.get("ai_score"),
                    "决策": adv.get("decision"),
                    "核心逻辑": "; ".join(adv.get("summary", [])[:2])
                })
                prog.progress((i + 1) / top_n)
            
            final_df = pd.DataFrame(results)
            st.session_state["ai_picks"] = final_df
            status.update(label="✅ 扫描任务完成", state="complete")

    # --- 结果显示区 ---
    if "ai_picks" in st.session_state:
        df_res = st.session_state["ai_picks"]
        
        # 1. AI 审计报告
        st.subheader("🏆 AI 优选报告")
        safe_dataframe(df_res) # 使用安全渲染函数

        # 2. 自动生成买卖汇总
        st.markdown("### 📝 市场机会总评")
        
        buy_list = df_res[df_res["决策"].str.contains("买入")]["名称"].tolist()
        sell_list = df_res[df_res["决策"].str.contains("减仓|清仓|谨慎")]["名称"].tolist()
        
        with st.container():
            st.markdown(f"""
            <div class='report-box'>
                <h4>📊 扫描总结</h4>
                <p>本次共深度审计 <b>{len(df_res)}</b> 只头部标的。</p>
                <ul>
                    <li>💰 <b>建议重点关注 ({len(buy_list)}):</b> {', '.join(buy_list) if buy_list else '无'}</li>
                    <li>⚠️ <b>建议规避/减仓 ({len(sell_list)}):</b> {', '.join(sell_list) if sell_list else '无'}</li>
                </ul>
                <p><i>*以上建议基于五维超脑 AI 模型分析，不构成绝对投资建议。</i></p>
            </div>
            """, unsafe_allow_html=True)

    if "scan_results" in st.session_state:
        with st.expander(f"查看 {selected_name} 完整初筛列表 (量化评分 Top 500)"):
            st.dataframe(st.session_state["scan_results"], use_container_width=True)

# --- 其他模式 ---
elif mode == "🌐 全市场扫描 (Pro)":
    st.title("🌐 全市场深度扫描")
    st.info("此模式展示原始量化数据，不进行 AI 深度分析。")
    if st.button("拉取全市场快照"):
        with st.spinner("正在下载全市场数据..."):
            df, _ = SCANNER.scan_cached("all_a_shares", ScanConfig())
            st.success(f"已获取 {len(df)} 只标的数据")
            st.dataframe(df, use_container_width=True)

else:
    st.title("📊 策略回测")
    st.info("请运行本地 backtrader 脚本查看回测结果。")