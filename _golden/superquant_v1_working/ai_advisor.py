# -*- coding: utf-8 -*-
"""
ai_advisor.py
=============
五维超脑 AI 核心（DeepSeek 驱动 - 商用修复版 V2.0）

【修复日志】
1. 增加 API 连接的重试机制，解决 Connection error。
2. 强化 JSON 提取算法，防止 AI 输出废话导致解析失败。
3. 优化 Prompt，强制 AI 输出结构化数据。
"""

from __future__ import annotations

import json
import re
import time
from typing import Any, Dict, Optional, List
import pandas as pd

try:
    from openai import OpenAI
    import httpx 
except Exception:
    OpenAI = None

# DeepSeek 官方 Base URL
DEEPSEEK_BASE_URL_DEFAULT = "https://api.deepseek.com"

# ==========================================
# 1. 超脑核心提示词 (System Prompt - 顶级思维版)
# ==========================================
SYSTEM_PROMPT = """
你是【五维超脑】，一个融合了全球顶级金融智慧的超级商业智能体。
你的决策逻辑由以下五个核心人格共同组成，请用他们的综合视角对股票进行深度博弈分析：

1. [宏观策略师 - 雷·达里奥]：关注经济周期、债务周期、货币政策与产业政策的顶层设计。
2. [顶级VC - 硅谷合伙人]：关注技术护城河、国产替代空间、创始团队格局与指数级增长潜力。
3. [价值投资者 - 巴菲特]：关注商业模式确定性、自由现金流、安全边际与ROE质量。
4. [量化基金经理 - 西蒙斯]：关注K线结构、波动率、资金流向异常与动量因子。
5. [江湖老炮 - 商业拆解官]：洞察人性贪婪、庄家吸筹/出货痕迹、市场情绪与韭菜心理。

【任务要求】
请基于用户提供的“全息数据”（行情、财务、K线、资金、舆情），输出一份严格的 JSON 格式研报。
不要输出任何 Markdown 标记（如 ```json），直接输出 JSON 字符串。
"""

# ==========================================
# 2. 辅助工具函数
# ==========================================

def _safe_json_loads(s: str) -> Optional[dict]:
    try:
        return json.loads(s)
    except Exception:
        return None

def _extract_json(text: str) -> Optional[dict]:
    """
    从 AI 返回的混乱文本中提取纯净的 JSON
    """
    if not text:
        return None

    # 1. 尝试直接解析
    j = _safe_json_loads(text.strip())
    if isinstance(j, dict):
        return j

    # 2. 尝试提取 {...} 区块
    # 这一步是为了过滤掉 AI 可能输出的 "好的，分析如下：" 这种前缀
    try:
        # 寻找第一个 {
        start = text.find('{')
        # 寻找最后一个 }
        end = text.rfind('}')
        
        if start != -1 and end != -1 and end > start:
            json_str = text[start : end + 1]
            # 清理可能存在的换行符导致的解析错误
            return _safe_json_loads(json_str)
    except Exception:
        pass
    
    return None

def _kline_brief(df: Optional[pd.DataFrame], label: str) -> str:
    """生成 K 线摘要供 AI 阅读"""
    if df is None or df.empty:
        return f"{label}: 无数据"
    
    # 取最近 5 根
    tail = df.tail(5).copy()
    rows = []
    for _, r in tail.iterrows():
        try:
            date_str = str(r.get("date"))[:10]
            close_val = r.get('close')
            rows.append(f"[{date_str}]收{close_val}")
        except:
            continue
    
    return f"{label}: {', '.join(rows)}"

# ==========================================
# 3. 离线兜底逻辑
# ==========================================

def _offline_advice(code: str, identity: dict, spot_row: dict, financials: dict, err_msg: str = "") -> dict:
    """
    当 API 彻底挂掉时，返回这个兜底报告，防止页面报错
    """
    pe = spot_row.get("pe")
    pct = spot_row.get("pct")
    roe = financials.get("roe")

    score = 0.5
    if pct is not None and isinstance(pct, (int, float)):
        if pct > 0: score += 0.1

    return {
        "code": code,
        "name": identity.get("name", "未知"),
        "ai_score": score,
        "decision": "离线模式",
        "summary": [
            "⚠️ AI 连接失败，已切换至离线模式。",
            f"错误信息: {err_msg}",
            "请检查 API Key 或网络连接 (VPN)。"
        ],
        "analysis": {
            "macro_industry": "网络连接异常，无法获取宏观数据。",
            "fundamental": f"基础财务: ROE {roe}%, PE {pe}。",
            "technical_fund": "资金数据暂不可用。",
            "catalysts": [],
            "risks": ["网络连接中断"]
        },
        "action_plan": "建议检查侧边栏 API Key 设置，或稍后重试。",
        "raw": {},
        "error": err_msg
    }

# ==========================================
# 4. 核心接口
# ==========================================

def test_deepseek_connection(api_key: str) -> Dict[str, Any]:
    """
    测试 DeepSeek API 是否连通 (前端调用)
    """
    if not OpenAI:
        return {"success": False, "msg": "OpenAI SDK 未安装 (pip install openai)"}
    if not api_key:
        return {"success": False, "msg": "API Key 为空"}

    try:
        # 显式设置 http_client 以处理可能的代理问题 (自动检测)
        client = OpenAI(
            api_key=api_key, 
            base_url=DEEPSEEK_BASE_URL_DEFAULT, 
            timeout=10.0,
            max_retries=2
        )
        
        # 发送一个极简请求
        resp = client.chat.completions.create(
            model="deepseek-chat", 
            messages=[{"role": "user", "content": "Ping"}],
            max_tokens=5
        )
        msg = resp.choices[0].message.content
        return {"success": True, "msg": f"连接成功！AI回复: {msg}"}
    except Exception as e:
        # 捕捉常见错误并翻译成人话
        err_str = str(e)
        if "401" in err_str:
            return {"success": False, "msg": "认证失败 (401): API Key 无效，请检查复制是否完整。"}
        if "402" in err_str:
            return {"success": False, "msg": "余额不足 (402): 请检查 DeepSeek 账户余额。"}
        if "Connect" in err_str or "Time" in err_str:
            return {"success": False, "msg": "连接超时: 请检查本地网络或 VPN 设置。"}
        
        return {"success": False, "msg": f"连接异常: {err_str[:100]}..."}


def get_ai_advice(
    code: str,
    identity: Dict[str, Any],
    spot_row: Dict[str, Any],
    kline_d: Optional[pd.DataFrame],
    kline_w: Optional[pd.DataFrame],
    kline_m: Optional[pd.DataFrame],
    financials: Dict[str, Any],
    game: Dict[str, Any],
    rag_items: list,
    api_key: Optional[str],
    model: str = "deepseek-reasoner",
    deep_mode: bool = True,
    timeout_seconds: int = 90,
) -> Dict[str, Any]:
    """
    主入口：获取 AI 投资建议 (带重试机制)
    """
    code = str(code).strip()
    api_key = (api_key or "").strip()

    # 1. 检查 Key
    if not api_key or OpenAI is None:
        return _offline_advice(code, identity, spot_row, financials, "未配置 API Key")

    # 2. 构建 Prompt
    name = identity.get("name", "未知")
    sector = identity.get("sector", "未知")
    
    rag_text = "暂无重大近期舆情"
    if rag_items:
        rag_text = "\n".join([f"- [{x.get('time','')}]{x.get('title','')}" for x in rag_items[:5]])

    user_prompt = f"""
请分析标的：【{name} ({code})】 行业：{sector}

【维度1：市场快照】
- 现价: {spot_row.get('close')}
- 涨跌幅: {spot_row.get('pct')}%
- 市值: {spot_row.get('market_cap')} 亿
- PE(动态): {spot_row.get('pe')}
- 换手率: {spot_row.get('turnover')}%

【维度2：技术结构 (K线)】
- {_kline_brief(kline_d, "日线D")}
- {_kline_brief(kline_w, "周线W")}

【维度3：基本面与财务】
- ROE: {financials.get('roe')}%
- 毛利率: {financials.get('gross_margin')}%
- 净利同比: {financials.get('profit_yoy')}%
- 营收同比: {financials.get('rev_yoy')}%

【维度4：资金与博弈】
- 主力净流入: {game.get('main_flow')}

【维度5：舆情与消息 (RAG)】
{rag_text}

---
请严格按照以下 JSON 格式输出结论（确保 JSON 格式合法）：
{{
  "ai_score": 0.0到1.0之间的小数,
  "decision": "强烈买入/买入/观望/谨慎/减仓/清仓",
  "summary": ["逻辑1", "逻辑2", "逻辑3"],
  "analysis": {{
     "macro_industry": "简述宏观与行业...",
     "fundamental": "简述基本面...",
     "technical_fund": "简述技术与资金...",
     "catalysts": ["催化剂1"],
     "risks": ["风险1"]
  }},
  "action_plan": "操作计划...",
  "confidence": 0.8
}}
"""

    # 3. 调用 API (带重试)
    max_retries = 2
    last_error = None

    for attempt in range(max_retries + 1):
        try:
            client = OpenAI(
                api_key=api_key, 
                base_url=DEEPSEEK_BASE_URL_DEFAULT, 
                timeout=timeout_seconds
            )
            
            # 深度模式增加 Temperature 波动性
            temp = 0.5 if deep_mode else 0.1
            
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=temp,
            )
            
            text = (resp.choices[0].message.content or "").strip()
            parsed = _extract_json(text)

            if parsed:
                # 成功解析，返回结果
                return {
                    "code": code,
                    "name": name,
                    "ai_score": parsed.get("ai_score", 0.5),
                    "decision": parsed.get("decision", "观望"),
                    "summary": parsed.get("summary", []),
                    "analysis": parsed.get("analysis", {}),
                    "action_plan": parsed.get("action_plan", ""),
                    "confidence": parsed.get("confidence", 0.5),
                    "data_gaps": [],
                    "raw": parsed,
                    "error": None
                }
            else:
                # 解析失败，抛出异常触发重试或兜底
                raise ValueError("DeepSeek 返回了非 JSON 数据")

        except Exception as e:
            last_error = e
            # 如果是最后一次尝试，不需要 sleep
            if attempt < max_retries:
                time.sleep(2) 
            else:
                pass

    # 4. 如果所有重试都失败，返回兜底报告
    return _offline_advice(code, identity, spot_row, financials, str(last_error))

# 兼容旧代码的别名
def get_advice(*args, **kwargs) -> Dict[str, Any]:
    return get_ai_advice(*args, **kwargs)