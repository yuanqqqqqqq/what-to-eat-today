# -*- coding: utf-8 -*-
"""三餐 Agent 后端入口（FastAPI）"""
from pathlib import Path

from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .agents.planner import generate_plan, generate_weekly, get_engine, reuse_plan, simplify_recipe
from .agents.orchestrator import orchestrate
from .config import get_llm_config, save_llm_config
from .core.profile import TasteProfile
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
    scene_id: Optional[str] = None
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
    """返回前端需要的选项列表（忌口/口味/设备/场景）+ 菜谱统计"""
    from .core.rules import TABOO_RULES, ALLERGY_RULES, DEVICE_RULES, TASTE_RULES
    from .core.scenes import SCENES
    engine = get_engine()
    return {
        "recipe_count": len(engine.recipes),
        "taboos": list(TABOO_RULES.keys()),
        "allergies": list(ALLERGY_RULES.keys()),
        "devices": list(DEVICE_RULES.keys()),
        "tastes": list(TASTE_RULES.keys()),
        "goals": ["均衡", "减脂", "增肌", "控糖"],
        "scenes": SCENES,
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


@app.post("/api/plan/graph")
def plan_graph(req: RecommendRequest):
    """多 Agent 编排（LangGraph）：规划师 → 营养师(可回退) → 采购员 → 搭配师。"""
    constraints = req.model_dump()
    try:
        return orchestrate(constraints, seed=req.seed)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


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


class ModelsRequest(BaseModel):
    base_url: str = ""


@app.post("/api/llm/models")
def llm_models(req: ModelsRequest):
    """列出可用模型（仅本地 Ollama 支持 /api/tags），供前端下拉选择。"""
    cfg = get_llm_config()
    base_url = req.base_url or cfg.get("base_url", "")
    llm = LLMClient(base_url=base_url, api_key="", model="")
    if not llm.is_ollama():
        return {"ok": True, "ollama": False, "models": [], "message": "当前非本地 Ollama 地址，请手动填写模型名"}
    models = llm.list_models()
    return {"ok": True, "ollama": True, "models": models, "message": f"找到 {len(models)} 个本地模型" if models else "未找到模型（Ollama 是否已启动？）"}


class WeeklyRequest(BaseModel):
    days: int = 7
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
    scene_id: Optional[str] = None
    seed: Optional[int] = None


class FeedbackRequest(BaseModel):
    recipe_id: str
    feedback: int  # 1 喜欢 / -1 不喜欢


class ReuseRequest(BaseModel):
    recipe_name: str
    n: int = 3


@app.post("/api/weekly")
def weekly(req: WeeklyRequest):
    constraints = req.model_dump()
    days = constraints.pop("days", 7)
    try:
        plan = generate_weekly(constraints, days=days, seed=req.seed)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return plan


@app.post("/api/feedback")
def feedback(req: FeedbackRequest):
    engine = get_engine()
    recipe = next((r for r in engine.recipes if r.get("id") == req.recipe_id), None)
    if recipe is None:
        raise HTTPException(status_code=404, detail="菜谱不存在")
    profile = TasteProfile()
    profile.record(recipe, 1 if req.feedback > 0 else -1)
    return {"ok": True, "profile": profile.summary()}


@app.get("/api/profile")
def profile_get():
    return TasteProfile().summary()


@app.post("/api/leftover")
def leftover(req: ReuseRequest):
    return reuse_plan(req.recipe_name, n=req.n)


class SimplifyRequest(BaseModel):
    recipe_name: str


@app.post("/api/simplify")
def simplify(req: SimplifyRequest):
    """家常简化版做法：用常见调料替代复杂调料（LLM）。"""
    return simplify_recipe(req.recipe_name)


# 静态资源（如有额外 js/css 可放 frontend 下）
app.mount("/static", StaticFiles(directory=BASE_DIR / "frontend"), name="static")
