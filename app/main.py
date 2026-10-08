# -*- coding: utf-8 -*-
"""三餐 Agent 后端入口（FastAPI）"""
import json
import logging
import re
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .agents.planner import generate_plan, generate_weekly, get_engine, reuse_plan, simplify_recipe
from .config import get_llm_config, is_masked, public_llm_config, save_llm_config
from .core.profile import TasteProfile
from .core.rules import strip_quantity
from .llm.client import LLMClient
from .paths import resource, data_file

logger = logging.getLogger(__name__)

app = FastAPI(title="今天吃什么 · 家庭餐桌助手", version="1.0.0")

MAX_PEOPLE = 50
MAX_DISHES = 20
MAX_SOUPS = 10


def _setup_logging() -> None:
    """配置根日志。只打一次，避免 uvicorn --reload 下重复挂 handler。"""
    root = logging.getLogger()
    if any(isinstance(h, logging.StreamHandler) for h in root.handlers):
        return
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )


_setup_logging()


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """兜底异常处理：堆栈只进服务端日志，不返回给客户端。

    以前是 `HTTPException(500, detail=str(e))`，会把文件路径等内部细节透给前端。
    """
    logger.exception("未处理异常 %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"ok": False, "error": "服务器内部错误，请查看服务端日志"},
    )


class RecommendRequest(BaseModel):
    people: int = Field(default=3, ge=1, le=MAX_PEOPLE)
    dishes: int = Field(default=2, ge=0, le=MAX_DISHES)
    soups: int = Field(default=1, ge=0, le=MAX_SOUPS)
    taboos: list = []
    allergies: list = []
    taste_prefs: list = []
    budget: Optional[float] = Field(default=None, ge=0)
    time_budget: Optional[int] = Field(default=None, ge=1)
    devices: list = []
    max_difficulty: Optional[int] = Field(default=None, ge=1, le=5)
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
    clear_api_key: bool = False


@app.get("/")
def index():
    return FileResponse(resource("frontend/index.html"))


@app.get("/api/health")
def health():
    """健康检查：进程活着 + 菜谱库加载正常。"""
    try:
        engine = get_engine()
        return {"ok": True, "recipes": len(engine.recipes)}
    except Exception:
        logger.exception("健康检查失败：菜谱库加载异常")
        return JSONResponse(status_code=503, content={"ok": False, "error": "菜谱库加载失败"})


def _graph_available() -> bool:
    """LangGraph 是否可用。

    PyInstaller 打包（build.bat）会把 langgraph 排除掉以缩小体积，
    所以 EXE 里这个功能是关的 —— 前端据此禁用多 Agent 开关，
    而不是让用户点了之后收到一个 500。
    """
    import importlib.util
    return importlib.util.find_spec("langgraph") is not None


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
        "graph_available": _graph_available(),
        "version": app.version,
    }


def _check_slots(req) -> None:
    """至少要有 1 个菜位，否则调用方拿不到任何有意义的结果。"""
    if (req.dishes or 0) + (req.soups or 0) <= 0 and not req.locked_ids:
        raise HTTPException(status_code=400, detail="请至少选择 1 道菜或 1 道汤")


@app.post("/api/recommend")
def recommend(req: RecommendRequest):
    """单餐推荐（规则流水线）。所有硬约束由规则引擎保证，LLM 只负责搭配说明。"""
    _check_slots(req)
    return generate_plan(req.model_dump())


@app.post("/api/plan/graph")
def plan_graph(req: RecommendRequest):
    """多 Agent 编排（LangGraph）：规划师 → 营养师(可回退) → 采购员 → 搭配师。"""
    if not _graph_available():
        raise HTTPException(status_code=503,
                            detail="当前运行环境未安装 LangGraph（打包版已裁剪），请用 /api/recommend")
    from .agents.orchestrator import orchestrate
    _check_slots(req)
    return orchestrate(req.model_dump(), seed=req.seed)


@app.get("/api/settings")
def settings_get():
    """LLM 配置（API Key 已脱敏，明文不出服务端）。"""
    return public_llm_config()


@app.post("/api/settings")
def settings_save(req: SettingsRequest):
    cfg = save_llm_config(req.model_dump(), clear_api_key=req.clear_api_key)
    return {"ok": True, "config": cfg}


@app.post("/api/llm/test")
def llm_test(req: SettingsRequest):
    """测试 LLM 连接：发一条简单消息。

    前端回传脱敏 Key（或留空）时，用服务端已保存的 Key 补齐。
    """
    saved = get_llm_config()
    base_url = (req.base_url or saved["base_url"]).strip()
    model = (req.model or saved["model"]).strip()
    api_key = saved["api_key"] if (not req.api_key or is_masked(req.api_key)) else req.api_key.strip()

    llm = LLMClient(base_url=base_url, api_key=api_key, model=model, timeout=15)
    if not llm.available:
        return {"ok": False, "message": "请先填写 base_url / api_key / model"}
    try:
        reply = llm.chat([{"role": "user", "content": "回复'连接成功'四个字"}], temperature=0, max_tokens=20)
        return {"ok": True, "message": reply.strip()}
    except Exception as e:
        logger.info("LLM 连接测试失败：%s", e)
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


class WeeklyRequest(RecommendRequest):
    days: int = Field(default=7, ge=1, le=14)


class FeedbackRequest(BaseModel):
    recipe_id: str
    feedback: int  # 1 喜欢 / -1 不喜欢


class ReuseRequest(BaseModel):
    recipe_name: str
    n: int = Field(default=3, ge=1, le=10)


@app.post("/api/weekly")
def weekly(req: WeeklyRequest):
    """周计划：N 天尽量不重样 + 整周合并采购清单。"""
    constraints = req.model_dump()
    days = constraints.pop("days", 7)
    _check_slots(req)
    return generate_weekly(constraints, days=days, seed=req.seed)


@app.post("/api/feedback")
def feedback(req: FeedbackRequest):
    """👍/👎 反馈：写入本地味觉画像（软约束，不改硬约束）。"""
    engine = get_engine()
    recipe = next((r for r in engine.recipes if r.get("id") == req.recipe_id), None)
    if recipe is None:
        raise HTTPException(status_code=404, detail="菜谱不存在")
    profile = TasteProfile()
    profile.record(recipe, 1 if req.feedback > 0 else -1)
    logger.info("记录反馈：%s -> %+d（累计 %d 条）",
                recipe.get("name"), 1 if req.feedback > 0 else -1, profile.data.get("count", 0))
    return {"ok": True, "profile": profile.summary()}


@app.get("/api/profile")
def profile_get():
    """家庭味觉画像摘要（本地数据，不含个人信息）。"""
    return TasteProfile().summary()


@app.post("/api/leftover")
def leftover(req: ReuseRequest):
    """一菜两吃：给剩菜找二次加工方案。"""
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
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            logger.warning("读取 %s 失败，返回默认值", path.name, exc_info=True)
            return default
    return default


def _save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


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
def search_recipes(q: str = "", limit: int = Query(default=30, ge=1, le=100)):
    """搜索菜谱（全量，含被家常化过滤掉的牛羊肉/名贵菜）。

    菜名优先于食材命中：先把菜名匹配的排前面，再排食材匹配的。
    """
    q = q.strip()[:50]
    if not q:
        return {"results": []}
    engine = get_engine()
    name_hits, ing_hits = [], []
    for r in engine.recipes:
        ings = [i.get("name", "") for i in r.get("ingredients", [])]
        item = {
            "id": r.get("id"), "name": r.get("name"), "dish_type": r.get("dish_type"),
            "ingredients": ings[:10],
            "difficulty": r.get("difficulty"), "estimated_minutes": r.get("estimated_minutes"),
            "source": r.get("source", ""),
        }
        if q in r.get("name", ""):
            name_hits.append(item)
        elif q in " ".join(ings):
            ing_hits.append(item)
        if len(name_hits) + len(ing_hits) >= limit * 3:
            break
    return {"results": (name_hits + ing_hits)[:limit]}


@app.get("/api/recipes/{recipe_id}")
def get_recipe(recipe_id: str):
    engine = get_engine()
    for r in engine.recipes:
        if r.get("id") == recipe_id:
            return r
    raise HTTPException(status_code=404, detail="菜谱不存在")


@app.post("/api/recipes")
def add_recipe(req: AddRecipeRequest):
    """添加自定义菜谱（存 data/user_recipes.json，纯本地）。"""
    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="菜名不能为空")

    existing = _load_json(USER_RECIPES_FILE, [])
    # 同名菜直接覆盖，避免用户反复添加越攒越多
    existing = [r for r in existing if r.get("name") != name]
    nums = []
    for r in existing:
        rid = r.get("id", "")
        if rid.startswith("u"):
            try:
                nums.append(int(rid[1:]))
            except ValueError:
                pass
    new_id = f"u{max(nums, default=0) + 1:04d}"

    # 分隔符兼容中英文逗号/顿号；顺手剥掉用户填的数量
    raw_ings = [x for x in re.split(r"[,，、;；]", req.ingredients or "") if x.strip()]
    ingredients = [{"name": strip_quantity(x), "optional": False} for x in raw_ings if strip_quantity(x)]
    steps = [{"group": None, "steps": [{"text": s.strip()} for s in (req.steps or "").split("\n") if s.strip()]}]

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
        logger.warning("自定义菜热量估算失败，用兜底值：%s", name, exc_info=True)
        recipe["calories_kcal"] = 300

    existing.append(recipe)
    _save_json(USER_RECIPES_FILE, existing)
    engine = get_engine(reload=True)
    logger.info("新增自定义菜「%s」（%s），菜谱库共 %d 道", name, new_id, len(engine.recipes))
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
    """保存食材价格表（同名以最后一条为准）。"""
    items = []
    seen = {}
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
        entry = {"name": name, "price": price, "unit": unit}
        if name in seen:
            items[seen[name]] = entry
        else:
            seen[name] = len(items)
            items.append(entry)
    _save_json(PRICES_FILE, items)
    return {"ok": True, "items": items}


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    """没有图标文件，返回 204，省掉浏览器控制台里的 404 噪音。"""
    return Response(status_code=204)


# 静态资源（如有额外 js/css 可放 frontend 下）。目录缺失时跳过，不让整个服务起不来。
_frontend_dir = resource("frontend")
if _frontend_dir.is_dir():
    app.mount("/static", StaticFiles(directory=_frontend_dir), name="static")
else:  # pragma: no cover - 只会在打包异常时触发
    logger.warning("frontend 目录不存在，跳过 /static 挂载：%s", _frontend_dir)
