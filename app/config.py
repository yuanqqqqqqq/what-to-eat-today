# -*- coding: utf-8 -*-
"""配置管理：.env 作为默认，data/settings.json 作为运行时覆盖（BYOK）"""
import json
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

SETTINGS_FILE = BASE_DIR / "data" / "settings.json"


def get_llm_config() -> dict:
    """返回 LLM 配置。运行时设置优先，其次 .env。"""
    settings = {}
    if SETTINGS_FILE.exists():
        try:
            settings = json.load(open(SETTINGS_FILE, encoding="utf-8"))
        except Exception:
            settings = {}
    return {
        "base_url": (settings.get("base_url") or os.getenv("LLM_BASE_URL", "")).strip(),
        "api_key": (settings.get("api_key") or os.getenv("LLM_API_KEY", "")).strip(),
        "model": (settings.get("model") or os.getenv("LLM_MODEL", "")).strip(),
    }


def save_llm_config(cfg: dict):
    """保存运行时 LLM 配置（前端设置面板提交）"""
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    clean = {k: (cfg.get(k) or "").strip() for k in ("base_url", "api_key", "model")}
    json.dump(clean, open(SETTINGS_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return clean
