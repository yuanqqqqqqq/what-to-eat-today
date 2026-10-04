# -*- coding: utf-8 -*-
"""三餐 Agent 后端入口（FastAPI）"""
import json
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .agents.planner import generate_plan, generate_weekly, get_engine, reuse_plan, simplify_recipe
from .config import get_llm_config, save_llm_config
from .core.profile import TasteProfile
from .llm.client import LLMClient
from .paths import resource, data_file
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
    homely: bool = True
    locked_ids: list = []
    dislikes: list = []
    favorite_ids: list = []


class SettingsRequest(BaseModel):
    base_url: str = ""
    api_key: str = ""
    model: str = ""


@app.get("/")
def index():
    return FileResponse(resource("frontend/index.html"))


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
    from .agents.orchestrator import orchestrate
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
    homely: bool = True
    locked_ids: list = []
    dislikes: list = []
    favorite_ids: list = []


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


# ---------- 菜市场：自定义菜谱 / 搜索 / 常备食材 ----------
USER_RECIPES_FILE = data_file("user_recipes.json")
PANTRY_FILE = data_file("pantry.json")
PRICES_FILE = data_file("prices.json")


def _load_json(path, default):
    if path.exists():
        try:
            return json.load(open(path, encoding="utf-8"))
        except Exception:
            return default
    return default


def _save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    json.dump(data, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)


class AddRecipeRequest(BaseModel):
    name: str
    dish_type: str = "荤"
    ingredients: str = ""   # 逗号分隔
    steps: str = ""          # 每行一步
    difficulty: int = 2
    estimated_minutes: int = 20


class PantryRequest(BaseModel):
    items: list = []


class PriceRequest(BaseModel):
    items: list = []   # [{name, price, unit}]


@app.get("/api/recipes/search")
def search_recipes(q: str = ""):
    """搜索菜谱（全量，含被家常化过滤掉的牛羊肉/名贵菜）。"""
    q = q.strip()
    if not q:
        return {"results": []}
    engine = get_engine()
    results = []
    for r in engine.recipes:
        text = r.get("name", "") + " " + " ".join(i.get("name", "") for i in r.get("ingredients", []))
        if q in text:
            results.append({
                "id": r.get("id"), "name": r.get("name"), "dish_type": r.get("dish_type"),
                "ingredients": [i.get("name", "") for i in r.get("ingredients", [])][:10],
                "difficulty": r.get("difficulty"), "estimated_minutes": r.get("estimated_minutes"),
                "source": r.get("source", ""),
            })
        if len(results) >= 30:
            break
    return {"results": results}


@app.get("/api/recipes/{recipe_id}")
def get_recipe(recipe_id: str):
    engine = get_engine()
    for r in engine.recipes:
        if r.get("id") == recipe_id:
            return r
    raise HTTPException(status_code=404, detail="菜谱不存在")


@app.post("/api/recipes")
def add_recipe(req: AddRecipeRequest):
    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="菜名不能为空")
    existing = _load_json(USER_RECIPES_FILE, [])
    nums = []
    for r in existing:
        rid = r.get("id", "")
        if rid.startswith("u"):
            try:
                nums.append(int(rid[1:]))
            except ValueError:
                pass
    new_id = f"u{max(nums, default=0) + 1:04d}"

    ingredients = [{"name": x.strip(), "optional": False} for x in req.ingredients.split(",") if x.strip()]
    steps = [{"group": None, "steps": [{"text": s.strip()} for s in req.steps.split("\n") if s.strip()]}]

    recipe = {
        "id": new_id, "name": name, "dish_type": req.dish_type,
        "ingredients": ingredients, "steps": steps,
        "calculations": [], "tools": [], "tips": [], "video_links": [],
        "difficulty": max(1, min(5, req.difficulty or 2)),
        "estimated_minutes": max(5, req.estimated_minutes or 20),
        "spiciness": "不辣", "taste": [], "season": "四季",
        "category": "user", "category_cn": "我的菜", "source": "user", "description": "",
    }
    try:
        from .core.food_db import FoodDB
        recipe["calories_kcal"] = FoodDB.estimate_kcal(recipe)
    except Exception:
        recipe["calories_kcal"] = 300

    existing.append(recipe)
    _save_json(USER_RECIPES_FILE, existing)
    get_engine(reload=True)
    return {"ok": True, "recipe": recipe}


@app.get("/api/pantry")
def pantry_get():
    return {"items": _load_json(PANTRY_FILE, [])}


@app.post("/api/pantry")
def pantry_save(req: PantryRequest):
    items = []
    for x in req.items:
        x = str(x).strip()
        if x and x not in items:
            items.append(x)
    _save_json(PANTRY_FILE, items)
    return {"ok": True, "items": items}


@app.get("/api/prices")
def prices_get():
    return {"items": _load_json(PRICES_FILE, [])}


@app.post("/api/prices")
def prices_save(req: PriceRequest):
    items = []
    for it in req.items:
        if isinstance(it, dict):
            name = str(it.get("name", "")).strip()
            price = it.get("price")
            unit = str(it.get("unit", "元/斤")).strip() or "元/斤"
        else:
            name = str(it).strip()
            price = None
            unit = "元/斤"
        if not name:
            continue
        try:
            price = round(float(price), 2) if price not in (None, "") else None
        except (TypeError, ValueError):
            price = None
        items.append({"name": name, "price": price, "unit": unit})
    _save_json(PRICES_FILE, items)
    return {"ok": True, "items": items}


# 静态资源（如有额外 js/css 可放 frontend 下）
app.mount("/static", StaticFiles(directory=resource("frontend")), name="static")
