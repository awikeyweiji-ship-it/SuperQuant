# -*- coding: utf-8 -*-
"""
radiation_engine.py
===================
五维超脑·辐射推演引擎 (Commercial Pro V11.0 - 逻辑中枢)

【核心职能】
系统的“逻辑处理器”。
它解决核心痛点：新闻是中文文本，而交易系统需要的是股票代码。
本模块利用 AI 的产业链知识库，将“宏观事件”转化为“可交易的行业/概念标签”。

【V11.0 工作流】
1. Input: 接收 DeepSearch 搜集到的【宏观情报】或【市场热点】。
2. Process: 
   - 激活 Chain-of-Thought (思维链)，推演受益环节。
   - 映射 A股 具体的概念板块 (Concept Map)。
3. Output: 
   - 输出结构化的JSON数据，包含 target_sectors (金手指) 和 logic_trace (逻辑链)。
"""

from __future__ import annotations
import json
import logging
from typing import Dict, Any, List, Optional

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

# ==========================================
# 辐射推演专用 Prompt
# ==========================================
RADIATION_SYSTEM_PROMPT = """
# Role: 五维超脑·首席产业链架构师 (The Industrial Architect)

# Mission:
你是一个精通中国A股产业链传导机制的专家。我将给你输入一组【市场情报/宏观叙事】，
你需要进行**多级辐射推演**，找到真正受益的细分领域和代表个股。

# Thinking Logic (The Radiation):
1. **Direct Impact (直接影响)**: 新闻字面提到的行业。
2. **Upstream/Downstream (上下游)**: 该行业爆发，谁供货？谁应用？(如：算力爆发 -> 此时电网设备是隐形瓶颈 -> 变压器/铜缆)。
3. **Concept Mapping (概念映射)**: 必须将逻辑映射为中国A股通用的【概念板块名称】(如: CPO概念, 低空经济, 固态电池)。

# Output Format (JSON Only):
{
  "core_theme": "低空经济 & AI硬件",
  "strategy_rationale": "政策密集出台叠加海外映射，低空与光模块是当前阻力最小方向。",
  "radiation_chain": [
    {
      "logic": "发改委设立专司 -> 基础设施先行 -> 空管系统是核心",
      "target_sector": "空管系统", // 必须是具体的板块名
      "beneficiary_tags": ["四川九洲", "莱斯信息"] // 代表个股或标签
    },
    {
      "logic": "英伟达GB200量产 -> 铜缆连接需求激增",
      "target_sector": "高速铜缆",
      "beneficiary_tags": ["沃尔核材", "神宇股份"]
    }
  ],
  "target_concepts": ["低空经济", "空管系统", "高速铜缆", "CPO概念"] // 最终输出给Scanner的扫描清单
}
"""

class RadiationEngine:
    def __init__(self, api_key: str = "", base_url: str = "https://api.deepseek.com"):
        self.api_key = api_key
        self.base_url = base_url
        self.client = None
        
        if self.api_key and OpenAI:
            self.client = OpenAI(api_key=self.api_key, base_url=self.base_url)
        
        print(f"☢️ [Radiation V11.0] 辐射引擎已就位 (Model: DeepSeek-V3)")

    def _clean_json(self, text: str) -> Optional[Dict]:
        """增强型 JSON 清洗器，防止 AI 输出 Markdown 包裹"""
        if not text: return None
        text = text.strip()
        # 去除 markdown 代码块标记
        if text.startswith("```"):
            import re
            match = re.search(r"```(?:json)?(.*?)```", text, re.DOTALL)
            if match:
                text = match.group(1).strip()
        
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            logging.error(f"JSON Parse Failed. Raw text: {text[:50]}...")
            return None

    def infer_opportunities(self, news_text: str) -> Dict[str, Any]:
        """
        核心方法：输入新闻文本，输出投资机会结构体
        """
        # 1. 检查连接
        if not self.client:
            return {
                "core_theme": "离线模式",
                "strategy_rationale": "未配置 API Key，无法进行逻辑推演。",
                "target_concepts": []
            }

        if not news_text or len(news_text) < 5:
            return {
                "core_theme": "无有效情报",
                "target_concepts": []
            }

        # 2. 调用 AI
        try:
            # print("🧠 [Radiation] 正在构建产业链图谱...")
            response = self.client.chat.completions.create(
                model="deepseek-chat", # V3 模型处理这种逻辑推理性价比最高
                messages=[
                    {"role": "system", "content": RADIATION_SYSTEM_PROMPT},
                    {"role": "user", "content": f"【今日情报池】\n{news_text}"}
                ],
                temperature=0.7, # 稍微增加一点创造力，以便联想隐形逻辑
                max_tokens=1500
            )
            
            result = self._clean_json(response.choices[0].message.content)
            
            if not result:
                return {"core_theme": "解析失败", "target_concepts": []}
                
            # 3. 后处理
            # 确保 target_concepts 是列表，防止 Scanner 报错
            if "target_concepts" not in result:
                result["target_concepts"] = []
            
            return result

        except Exception as e:
            logging.error(f"Radiation Inference Error: {e}")
            return {
                "core_theme": "系统错误",
                "strategy_rationale": str(e),
                "target_concepts": []
            }

# ==========================================
# 单元测试
# ==========================================
if __name__ == "__main__":
    # 模拟测试
    # key = "sk-xxxxxxxx" 
    # engine = RadiationEngine(api_key=key)
    # news = "1. 发改委：加快低空经济基础设施建设。 2. 华为发布全液冷超充技术。"
    # res = engine.infer_opportunities(news)
    # print(json.dumps(res, indent=2, ensure_ascii=False))
    pass