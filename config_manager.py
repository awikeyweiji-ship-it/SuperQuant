# -*- coding: utf-8 -*-
"""
config_manager.py
=================
统一配置中心（商用必备）：
- 统一读取/保存 DeepSeek / Tavily / 通知等配置
- 优先级：环境变量 > 本地配置文件
- 提供连通性测试（用于 Streamlit “确定/测试”按钮）

⚠️ 设计目标：不在代码里硬编码任何密钥/隐私信息。
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, asdict
from typing import Any, Dict, Optional, Tuple

import requests

DEFAULT_CONFIG_PATH = os.getenv("W5BRAIN_CONFIG_PATH", os.path.join(os.path.dirname(__file__), ".w5brain_config.json"))

DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
TAVILY_BASE_URL = os.getenv("TAVILY_BASE_URL", "https://api.tavily.com")

# ------------------------------ Model ------------------------------

@dataclass
class AppConfig:
    deepseek_api_key: str = ""
    tavily_api_key: str = ""

    # notifier (optional)
    target_email: str = ""
    target_phone: str = ""

    # smtp (optional)
    smtp_server: str = ""
    smtp_port: int = 465
    sender_email: str = ""
    sender_pass: str = ""  # SMTP 授权码（不要写邮箱登录密码）

    # extra
    updated_at: float = 0.0

# ------------------------------ IO ------------------------------

def _safe_read_json(path: str) -> Dict[str, Any]:
    try:
        if not os.path.exists(path):
            return {}
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}

def _safe_write_json(path: str, data: Dict[str, Any]) -> None:
    try:
        data = dict(data)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        # 配置写失败不应崩溃主程序
        pass

def load_config(path: str = DEFAULT_CONFIG_PATH) -> AppConfig:
    raw = _safe_read_json(path)
    cfg = AppConfig()
    for k, v in raw.items():
        if hasattr(cfg, k):
            setattr(cfg, k, v)
    return cfg

def save_config(cfg: AppConfig, path: str = DEFAULT_CONFIG_PATH) -> None:
    cfg.updated_at = time.time()
    _safe_write_json(path, asdict(cfg))

def get_config(path: str = DEFAULT_CONFIG_PATH) -> AppConfig:
    """
    读取“最终生效配置”（env 优先，配置文件兜底）
    """
    cfg = load_config(path)
    # env override
    cfg.deepseek_api_key = os.getenv("DEEPSEEK_API_KEY", "") or cfg.deepseek_api_key
    cfg.tavily_api_key = os.getenv("TAVILY_API_KEY", "") or cfg.tavily_api_key

    cfg.target_email = os.getenv("W5_TARGET_EMAIL", "") or cfg.target_email
    cfg.target_phone = os.getenv("W5_TARGET_PHONE", "") or cfg.target_phone

    cfg.smtp_server = os.getenv("W5_SMTP_SERVER", "") or cfg.smtp_server
    try:
        cfg.smtp_port = int(os.getenv("W5_SMTP_PORT", str(cfg.smtp_port)) or cfg.smtp_port)
    except Exception:
        pass
    cfg.sender_email = os.getenv("W5_SENDER_EMAIL", "") or cfg.sender_email
    cfg.sender_pass = os.getenv("W5_SENDER_PASS", "") or cfg.sender_pass

    return cfg

def update_keys(deepseek_api_key: str = "", tavily_api_key: str = "", path: str = DEFAULT_CONFIG_PATH) -> AppConfig:
    cfg = load_config(path)
    if deepseek_api_key is not None:
        cfg.deepseek_api_key = deepseek_api_key.strip()
    if tavily_api_key is not None:
        cfg.tavily_api_key = tavily_api_key.strip()
    save_config(cfg, path)
    return cfg

# ------------------------------ Connectivity Tests ------------------------------

def test_deepseek(api_key: str, timeout: int = 12) -> Tuple[bool, str]:
    """
    轻量测试 DeepSeek 连通性：
    GET /models （无需消耗太多 token）
    """
    api_key = (api_key or "").strip()
    if not api_key:
        return False, "未提供 DEEPSEEK_API_KEY"

    url = f"{DEEPSEEK_BASE_URL}/models"
    headers = {"Authorization": f"Bearer {api_key}"}
    try:
        r = requests.get(url, headers=headers, timeout=timeout)
        if r.status_code == 200:
            return True, "DeepSeek 连接正常"
        # 常见错误提示
        if r.status_code in (401, 403):
            return False, f"鉴权失败 ({r.status_code})：请检查 Key 是否正确/是否有权限"
        return False, f"DeepSeek 返回异常 ({r.status_code})：{r.text[:120]}"
    except Exception as e:
        return False, f"DeepSeek 连接失败：{e}"

def test_tavily(api_key: str, timeout: int = 12) -> Tuple[bool, str]:
    """
    Tavily 搜索测试（会发生一次最小查询）
    """
    api_key = (api_key or "").strip()
    if not api_key:
        return False, "未提供 TAVILY_API_KEY"

    url = f"{TAVILY_BASE_URL}/search"
    payload = {
        "api_key": api_key,
        "query": "China macro policy latest test",
        "search_depth": "basic",
        "include_answer": False,
        "max_results": 1,
    }
    try:
        r = requests.post(url, json=payload, timeout=timeout)
        if r.status_code == 200:
            return True, "Tavily 连接正常"
        if r.status_code in (401, 403):
            return False, f"鉴权失败 ({r.status_code})：请检查 Key 是否正确/是否有权限"
        return False, f"Tavily 返回异常 ({r.status_code})：{r.text[:120]}"
    except Exception as e:
        return False, f"Tavily 连接失败：{e}"
