# -*- coding: utf-8 -*-
"""三餐 Agent 后端入口（FastAPI）"""
from pathlib import Path

from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .agents.planner import generate_plan, get_engine
from .config import get_llm_config, save_llm_config
from .llm.client import LLMClient

BASE_DIR = Path(__file__).resolve().parent.parent
app = FastAPI(title="三餐 Agent", version="0.1.0")


class RecommendRequest(BaseModel):
    people: int = 3
    dishes: int = 2
    soups: int = 1
    taboos: list = []
    allergies: list = []
    taste_prefs: list = []
    budget: Optional[float] = None
    time_budget: Optional[int] = None
    devices: list = []
    max_difficulty: Optional[int] = None
    must_include: list = []
    pantry: list = []
    nutrition_goal: Optional[str] = None
    seed: Optional[int] = None


class SettingsRequest(BaseModel):
    base_url: str = ""
    api_key: str = ""
    model: str = ""


@app.get("/")
def index():
    return FileResponse(BASE_DIR / "frontend" / "index.html")


@app.get("/api/meta")
def meta():
    """返回前端需要的选项列表（忌口/口味/设备）+ 菜谱统计"""
    from .core.rules import TABOO_RULES, ALLERGY_RULES, DEVICE_RULES, TASTE_RULES
    engine = get_engine()
    return {
        "recipe_count": len(engine.recipes),
        "taboos": list(TABOO_RULES.keys()),
        "allergies": list(ALLERGY_RULES.keys()),
        "devices": list(DEVICE_RULES.keys()),
        "tastes": list(TASTE_RULES.keys()),
        "goals": ["均衡", "减脂", "增肌", "控糖"],
        "llm_configured": LLMClient(**get_llm_config()).available,
    }


@app.post("/api/recommend")
def recommend(req: RecommendRequest):
    constraints = req.model_dump()
    try:
        plan = generate_plan(constraints)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return plan


@app.get("/api/settings")
def settings_get():
    return get_llm_config()


@app.post("/api/settings")
def settings_save(req: SettingsRequest):
    cfg = save_llm_config(req.model_dump())
    return {"ok": True, "config": cfg}


@app.post("/api/llm/test")
def llm_test(req: SettingsRequest):
    """测试 LLM 连接：发一条简单消息"""
    cfg = req.model_dump()
    # 若前端只传了部分字段，用已保存的补齐
    saved = get_llm_config()
    for k in ("base_url", "api_key", "model"):
        if not cfg.get(k):
            cfg[k] = saved.get(k, "")
    llm = LLMClient(**cfg)
    if not llm.available:
        return {"ok": False, "message": "请先填写 base_url / api_key / model"}
    try:
        reply = llm.chat([{"role": "user", "content": "回复'连接成功'四个字"}], temperature=0, max_tokens=20)
        return {"ok": True, "message": reply.strip()}
    except Exception as e:
        return {"ok": False, "message": str(e)}


# 静态资源（如有额外 js/css 可放 frontend 下）
app.mount("/static", StaticFiles(directory=BASE_DIR / "frontend"), name="static")
