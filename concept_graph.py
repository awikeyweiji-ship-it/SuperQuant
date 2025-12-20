# -*- coding: utf-8 -*-
"""concept_graph.py
===================
概念图谱（Step-1：轻量可扩展版）

目的：把 Radiation 输出的 target_concepts，从“字符串匹配”升级为“图谱映射”能力：
- 同义词/别名扩展
- 概念->股票列表（可手工补全，也可 Step-2 自动补全）

文件：默认读取/写入 .superquant_cache/concept_graph.json

结构示例：
{
  "version": 1,
  "concepts": {
    "低空经济": {
      "synonyms": ["通航", "无人机", "空管", "eVTOL"],
      "codes": ["000801"],
      "notes": "可手动补充板块龙头"
    }
  }
}
"""

from __future__ import annotations

import json
import os
from typing import Dict, List, Set, Tuple, Any, Optional


_DEFAULT_SEED = {
    "version": 1,
    "concepts": {
        "低空经济": {
            "synonyms": ["通航", "无人机", "空管", "eVTOL", "飞行汽车"],
            "codes": [],
            "notes": "可手动补充：龙头/弹性票/核心环节"
        },
        "AI/算力": {
            "synonyms": ["算力", "数据中心", "智算", "光模块", "CPO"],
            "codes": [],
            "notes": "可手动补充：光模块/CPO/电网设备/IDC"
        }
    }
}


class ConceptGraph:
    def __init__(self, cache_dir: str = ".superquant_cache", path: Optional[str] = None):
        self.cache_dir = os.path.abspath(cache_dir)
        os.makedirs(self.cache_dir, exist_ok=True)
        self.path = path or os.path.join(self.cache_dir, "concept_graph.json")
        self._data: Dict[str, Any] = {}
        self.reload()

    def reload(self) -> None:
        if not os.path.exists(self.path):
            self._safe_write(_DEFAULT_SEED)
        self._data = self._safe_read() or _DEFAULT_SEED

    def _safe_read(self) -> Dict[str, Any]:
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                return json.load(f) or {}
        except Exception:
            return {}

    def _safe_write(self, data: Dict[str, Any]) -> None:
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    @property
    def concepts(self) -> Dict[str, Dict[str, Any]]:
        return (self._data or {}).get("concepts", {}) or {}

    def expand(self, target_concepts: List[str]) -> List[str]:
        """把目标概念扩展为：原概念 + 同义词（去重）。"""
        out: List[str] = []
        seen: Set[str] = set()
        for c in (target_concepts or []):
            c = (c or "").strip()
            if not c:
                continue
            if c not in seen:
                out.append(c)
                seen.add(c)
            meta = self.concepts.get(c)
            if not meta:
                continue
            for s in (meta.get("synonyms") or []):
                s = (s or "").strip()
                if s and s not in seen:
                    out.append(s)
                    seen.add(s)
        return out

    def codes_for(self, concept: str) -> Set[str]:
        meta = self.concepts.get(concept or "") or {}
        codes = meta.get("codes") or []
        return set([str(x).zfill(6) for x in codes if str(x).strip()])

    def hit(self, code: str, name: str = "", sector: str = "", target_concepts: List[str] = None) -> Tuple[bool, str]:
        """判断某股票是否命中 target_concepts。

        Returns:
            (is_hit, hit_reason)
        """
        code = str(code or "").zfill(6)
        name = str(name or "")
        sector = str(sector or "")
        targets = target_concepts or []

        # 1) codes 显式命中
        for c in targets:
            if code in self.codes_for(c):
                return True, f"code_in:{c}"

        # 2) 字符串命中（概念/同义词）
        expanded = self.expand(targets)
        for t in expanded:
            if not t:
                continue
            if t in name or t in sector:
                return True, f"text_hit:{t}"

        return False, ""
