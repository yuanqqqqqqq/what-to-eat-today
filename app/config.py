# -*- coding: utf-8 -*-
"""配置管理：.env 作为默认，data/settings.json 作为运行时覆盖（BYOK）

安全约定：
- API Key 只存在于服务端（.env 或 data/settings.json，都在 .gitignore 里）。
- 对外（GET /api/settings）只回传脱敏后的 Key，绝不回传明文。
- 日志里只打 URL / 模型名 / Key 长度，绝不打 Key 本身。
"""
import json
import logging
import os

from dotenv import load_dotenv

from .paths import resource, data_file

logger = logging.getLogger(__name__)

load_dotenv(resource(".env"))

SETTINGS_FILE = data_file("settings.json")

# 脱敏后的 Key 用这个掩码标记，前端原样回传时视为"不修改"
MASK_MARK = "****"


def mask_key(key: str) -> str:
    """sk-abcdef...1234 -> sk-****1234。空 Key 返回空串。"""
    key = (key or "").strip()
    if not key:
        return ""
    if len(key) <= 8:
        return MASK_MARK
    return f"{key[:3]}{MASK_MARK}{key[-4:]}"


def is_masked(value: str) -> bool:
    """判断前端回传的是不是脱敏串（而不是新 Key）。"""
    return MASK_MARK in (value or "")


def get_llm_config() -> dict:
    """返回 LLM 配置。运行时设置优先，其次 .env。"""
    settings = {}
    if SETTINGS_FILE.exists():
        try:
            with open(SETTINGS_FILE, encoding="utf-8") as f:
                settings = json.load(f)
        except Exception:
            logger.warning("settings.json 读取失败，忽略运行时配置", exc_info=True)
            settings = {}
    return {
        "base_url": (settings.get("base_url") or os.getenv("LLM_BASE_URL", "")).strip(),
        "api_key": (settings.get("api_key") or os.getenv("LLM_API_KEY", "")).strip(),
        "model": (settings.get("model") or os.getenv("LLM_MODEL", "")).strip(),
    }


def public_llm_config() -> dict:
    """给前端看的配置：Key 脱敏，只给"是否已配置"。"""
    cfg = get_llm_config()
    return {
        "base_url": cfg["base_url"],
        "model": cfg["model"],
        "api_key": mask_key(cfg["api_key"]),
        "has_api_key": bool(cfg["api_key"]),
        "configured": bool(cfg["base_url"] and cfg["model"] and cfg["api_key"]),
    }


def save_llm_config(cfg: dict, clear_api_key: bool = False) -> dict:
    """保存运行时 LLM 配置（前端设置面板提交）。

    - api_key 传脱敏串（含 ****）或空串 → 保留已存的 Key，不覆盖（前端"保存"不该清空 Key）
    - api_key 传新值 → 覆盖
    - clear_api_key=True → 显式清空
    """
    current = get_llm_config()
    incoming = (cfg.get("api_key") or "").strip()
    if clear_api_key:
        api_key = ""
    elif not incoming or is_masked(incoming):
        api_key = current["api_key"]
    else:
        api_key = incoming

    clean = {
        "base_url": (cfg.get("base_url") or "").strip(),
        "api_key": api_key,
        "model": (cfg.get("model") or "").strip(),
    }
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(clean, f, ensure_ascii=False, indent=1)
    logger.info("LLM 配置已更新：base_url=%s model=%s key=%s",
                clean["base_url"] or "(空)", clean["model"] or "(空)",
                f"{len(api_key)} 字符" if api_key else "(未设置)")
    return public_llm_config()
