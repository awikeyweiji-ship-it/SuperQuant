import re
from typing import Any, Dict, List

import requests


def _to_em_code(code_std: str) -> str:
    plain, market = code_std.split(".")
    prefix = "SZ"
    if market == "SH":
        prefix = "SH"
    elif market == "BJ":
        prefix = "BJ"
    return f"{prefix}{plain}"


def _split_concepts(raw: Any) -> List[str]:
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(x).strip() for x in raw if str(x).strip()]
    txt = str(raw)
    parts = re.split(r"[、，,\s]+", txt)
    return [p for p in (x.strip() for x in parts) if p]


def fetch_identity_em(code_std: str, timeout: int = 10) -> Dict[str, Any]:
    """使用东财 F10 公司概况接口获取行业/概念信息。"""

    code_em = _to_em_code(code_std)
    url = "https://emweb.securities.eastmoney.com/PC_HSF10/CompanySurvey/PageAjax"
    try:
        resp = requests.get(url, params={"code": code_em}, timeout=timeout)
        payload = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
    except Exception:
        return {}

    survey = payload.get("jbzl") if isinstance(payload, dict) else {}
    sector = ""
    concept_txt = ""
    if isinstance(survey, dict):
        sector = str(
            survey.get("sszjhhy")
            or survey.get("sshy")
            or survey.get("zjhhy")
            or survey.get("hy")
            or ""
        ).strip()
        concept_txt = survey.get("hxtc") or survey.get("ssbk") or ""

    concepts = _split_concepts(concept_txt)
    return {"sector": sector, "concepts": concepts, "source": "eastmoney_f10"} if (sector or concepts) else {}
