# -*- coding: utf-8 -*-
"""
ai_advisor.py
=============
五维超脑 AI 核心（DeepSeek 驱动 - V12.0 终极商业版）

【核心职能】
1. **多重人格博弈**: 融合 Ray Dalio (宏观), 顶级 VC (产业), 游资 (情绪), Quant (资金), 商业拆解官 (人性) 等思维。
2. **实战研报**: 输出“四川九洲”风格的 Setup/Catalyst/Action 结构化研报。
3. **因子评分卡**: 对六大维度进行量化评分。
"""

from __future__ import annotations
import json
from typing import Any, Dict, List, Optional

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

# DeepSeek 官方 Base URL
DEEPSEEK_BASE_URL_DEFAULT = "https://api.deepseek.com"

# ==========================================
# 1. 超级大脑 Prompt (The Super Brain)
# ==========================================
STOCK_SYSTEM_PROMPT = """
# Role: 五维超脑 (5D Super Brain) - 终极商业决策系统
你是一个真正的可以商用的多角色联合体超脑。你的思维模型融合了全球顶尖的商业智慧：

## 🎭 你的多重人格矩阵：
1. **商业拆解官 & 增长顾问**: 善于野路子、生意经、人性杠杆、利用信息差获利。
2. **全球宏观策略师 (Ray Dalio框架)**: 基于《原则》和债务周期理论，研判政策强度与持续性。
3. **硅谷顶级VC**: 专注于A轮前颠覆性技术，评估技术护城河、国产替代空间与TAM(潜在市场规模)。
4. **沃伦·巴菲特式价值投资者**: 寻找安全边际、长坡厚雪与护城河。
5. **顶级游资/操盘手**: 精通市场情绪周期(冰点/高潮)、题材发酵、主力资金意图与短线博弈。
6. **量化基金经理 (Quant)**: 数据驱动，关注量价异动、筹码结构与资金流向。
7. **风险控制官**: 排除黑天鹅、立案调查与致命风险。

# Mission:
分析我提供的“全息数据包”，输出一份**超越市面研报的终极投资决策书**。
你必须综合多源数据（行情、基本面、舆情、政策），实现“多因子、多维度”分析。
风格要求：**辛辣、干练、客观、不仅要有买点，更要有卖点/清仓建议**。

# Analysis Dimensions (逻辑拆解):
1. **宏观与行业**: 政策强度/持续性、国内外需求空间、技术成熟度/国产替代空间。
2. **基本面**: 市场定价水平（是否充分反映预期）、估值因子。
3. **资金与博弈**: 机构预期、融资融券、主力资金意图。
4. **情绪与舆情**: 散户贪婪/恐慌程度、市场噪音分析。
5. **风险**: 最大的不确定性是什么？

# Output Format (JSON Only):
严格按照以下 JSON 结构输出，不要输出 Markdown 标记以外的多余文本。

{
  "ai_score": 0.92, // 0~1.0, 综合推荐分
  "decision": "强力潜伏 / 结构性博弈 / 观望 / 坚决止盈 / 清仓走人",
  
  // 1. 因子评分卡 (Factor Scoring - 0~10分)
  "scores": {
    "macro_industry": 8.5,  // 宏观/行业/政策
    "fundamental": 7.0,     // 基本面/估值
    "technical": 9.0,       // 技术形态
    "money_flow": 8.0,      // 资金面
    "sentiment": 9.5,       // 情绪/舆情
    "risk_control": 6.0     // 风控分(越高越安全)
  },

  // 2. 短线逻辑 (The Setup) - 核心结论
  "setup_logic": "一句话点破核心逻辑（如：困境反转叠加政策抢跑，主力资金借利空洗盘完成）。",
  
  // 3. 强催化剂 (The Catalyst)
  "catalyst": "具体的引爆点（如：xx月xx日展会、财报发布、重磅文件落地）。",
  
  // 4. 详细逻辑拆解 (Logic Breakdown)
  "analysis_body": {
    "macro_policy": "政策强度与持续性、技术成熟度与国产替代空间分析...",
    "industry_tech": "需求空间（国内+全球）与行业趋势...",
    "funds_sentiment": "资金面博弈与市场情绪分析..."
  },
  
  // 5. 行动计划 (Action Plan)
  "action_plan": {
    "strategy": "潜伏 / 追涨 / 低吸 / 减仓 / 清仓",
    "buy_point": "建议关注价格区间...",
    "sell_point": "止盈/压力位...",
    "stop_loss": "止损位...",
    "position_advice": "建议持仓比例 (如: 3成仓位，若跌破xx建议清仓)..."
  },
  
  // 6. 风险提示 (Risk View)
  "risk_warning": "一票否决项（如：立案调查、业绩暴雷、高位顶背离）。"
}
"""

STRATEGY_SYSTEM_PROMPT = """
# Role: 五维超脑·战略指挥官 (The Strategist)
基于【宏观环境】和【热门资讯】，制定今日的**“金手指战略”**。
告诉市场雷达，今天应该重点扫描哪几个**行业/赛道**（Sectors）。

# Output Format (JSON):
{
  "target_sectors": ["低空经济", "银行", "半导体"],
  "strategy_rationale": "基于发改委最新消息，叠加珠海航展预期，低空经济为第一主线..."
}
"""

def _extract_json(text: str) -> Optional[dict]:
    if not text: return None
    try: return json.loads(text.strip())
    except:
        import re
        match = re.search(r"\{.*\}", text.replace("\n", ""), re.DOTALL)
        if match:
            try: return json.loads(match.group())
            except: pass
    return None

def _format_data_for_prompt(data_pack: Dict[str, Any]) -> str:
    macro = data_pack.get("macro_context", {})
    spot = data_pack.get("market_data", {})
    fin = data_pack.get("financials", {})
    sent = data_pack.get("alternative_intelligence", {})
    ident = data_pack.get("identity", {})
    money = data_pack.get("money_flow", {})
    
    # 新闻处理
    corp_news = data_pack.get("corporate_news", [])
    c_news_str = "\n".join([f"- {n.get('date')} {n.get('tag')} {n.get('title')}" for n in corp_news]) or "无重大公告"
    
    macro_news = data_pack.get("macro_news", [])
    m_news_str = "\n".join([f"- {n.get('date')} [政策] {n.get('title')}" for n in macro_news]) or "无重大宏观政策"

    prompt_text = f"""
【全息标的数据】
代码: {data_pack.get('code')} ({ident.get('name')})
行业: {ident.get('sector')}

[1. 宏观与政策 (Macro)]
- 市场定调: {macro.get('market_sentiment', '未知')}
- 核心指标: CPI {macro.get('cpi_yoy')}% | M2 {macro.get('m2_yoy')}%
- 最新政策:
{m_news_str}

[2. 市场与资金 (Money)]
- 现价: {spot.get('close')} (涨跌: {spot.get('pct')}%)
- 量比: {spot.get('vol_ratio')} | 换手: {spot.get('turnover')}%
- 主力净流入: {money.get('main_net_inflow_today', 0)} 万
- 市值: {spot.get('market_cap')} 亿 | PE: {spot.get('pe')}

[3. 基本面 (Fundamental)]
- ROE: {fin.get('roe')}% | 毛利: {fin.get('gross_margin')}% 
- 营收增长: {fin.get('revenue_yoy')}% | 利润增长: {fin.get('profit_yoy')}%

[4. 舆情与噪音 (Sentiment)]
- 散户情绪分: {sent.get('retail_sentiment', 0)}
- 股吧样本: "{sent.get('raw_guba_sample', '')[:100]}..."

[5. 资本运作 (Catalyst)]
{c_news_str}
"""
    return prompt_text

def _offline_fallback(data_pack: Dict[str, Any], err_msg: str) -> Dict[str, Any]:
    return {
        "ai_score": 0.0,
        "decision": "系统离线",
        "scores": {"macro_industry":0,"fundamental":0,"technical":0,"money_flow":0,"sentiment":0,"risk_control":0},
        "setup_logic": f"无法连接大脑: {err_msg}",
        "catalyst": "无",
        "analysis_body": {},
        "action_plan": {},
        "risk_warning": "请检查 API Key 或 网络连接"
    }

def get_ai_strategy(data_pack: Dict[str, Any], api_key: str, model: str = "deepseek-chat") -> Dict[str, Any]:
    if not api_key: return _offline_fallback(data_pack, "Missing API Key")

    user_content = _format_data_for_prompt(data_pack)
    client = OpenAI(api_key=api_key, base_url=DEEPSEEK_BASE_URL_DEFAULT, timeout=60)
    
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": STOCK_SYSTEM_PROMPT},
                {"role": "user", "content": user_content}
            ],
            temperature=0.6, 
            max_tokens=3000
        )
        parsed = _extract_json(response.choices[0].message.content)
        return parsed if parsed else _offline_fallback(data_pack, "JSON Parsing Failed")
    except Exception as e:
        return _offline_fallback(data_pack, str(e))

def get_market_strategy(macro_news_list: List[str], api_key: str, model: str = "deepseek-chat") -> Dict[str, Any]:
    if not api_key: return {"target_sectors": [], "strategy_rationale": "离线模式"}
    summary = "\n".join(macro_news_list[:15])
    user_content = f"【今日宏观资讯】\n{summary}\n\n请给出今日重点关注的行业。"
    
    client = OpenAI(api_key=api_key, base_url=DEEPSEEK_BASE_URL_DEFAULT, timeout=30)
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": STRATEGY_SYSTEM_PROMPT}, {"role": "user", "content": user_content}],
            temperature=0.7
        )
        return _extract_json(response.choices[0].message.content) or {}
    except: return {}