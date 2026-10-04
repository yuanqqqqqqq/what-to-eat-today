# -*- coding: utf-8 -*-
"""
方案编排器：约束引擎出菜单 -> 采购清单 -> 营养分析 -> 搭配说明 -> 做法整理。
对应 PRD 5.2 协作流程的"规则版"实现；LLM 节点在配置了 Key 后启用。
"""
import random
from datetime import datetime

from ..config import get_llm_config
from ..core.constraint_engine import ConstraintEngine
from ..core.shopping import build_shopping_list
from ..core.nutrition import analyze
from ..core.profile import TasteProfile
from ..core.weekly import generate_weekly_plan
from ..core.leftover import suggest_reuse
from ..llm.client import LLMClient

# 模块级缓存：菜谱只加载一次
_ENGINE = None


def get_engine(reload: bool = False) -> ConstraintEngine:
    global _ENGINE
    if _ENGINE is None or reload:
        import json
        from ..paths import resource, data_file
        recipes = json.load(open(resource("data/recipes.json"), encoding="utf-8"))
        user_file = data_file("user_recipes.json")
        if user_file.exists():
            recipes = recipes + json.load(open(user_file, encoding="utf-8"))
        _ENGINE = ConstraintEngine(recipes)
    return _ENGINE


def _template_pairing_note(menu, constraints):
    """无 LLM 时的模板搭配说明"""
    names = "、".join(r["name"] for r in menu)
    types = [r.get("dish_type") for r in menu]
    meat = types.count("荤")
    veg = types.count("素")
    notes = []
    if meat and veg:
        notes.append(f"{meat} 荤 {veg} 素，荤素搭配")
    elif not veg:
        notes.append("缺少蔬菜，建议搭配一道绿叶菜")
    if any(r.get("estimated_minutes", 0) and r["estimated_minutes"] <= 20 for r in menu):
        notes.append("含快手套餐，适合工作日")
    return f"本餐组合：{names}。{'；'.join(notes)}。" if notes else f"本餐组合：{names}。"


def _llm_pairing_note(menu, constraints, llm):
    """LLM 生成搭配说明（解释为什么这么搭：颜色/口感/营养）"""
    brief = [
        {"name": r["name"], "type": r.get("dish_type"), "difficulty": r.get("difficulty"),
         "minutes": r.get("estimated_minutes"), "kcal": r.get("calories_kcal")}
        for r in menu
    ]
    prompt = (
        "你是家庭餐桌搭配师。根据以下菜单，用 2-3 句话说明这份搭配好在哪"
        "（颜色、口感、营养、耗时配合），语气亲切，不要客套。\n"
        f"菜单：{brief}\n"
        f"约束：{ {k: constraints.get(k) for k in ('people','taboos','taste_prefs','budget','time_budget')} }"
    )
    try:
        return llm.chat([{"role": "user", "content": prompt}], temperature=0.7, max_tokens=300).strip()
    except Exception as e:
        return _template_pairing_note(menu, constraints)


def current_season() -> str:
    """按当前月份自动判断季节"""
    m = datetime.now().month
    if m in (3, 4, 5):
        return "春"
    if m in (6, 7, 8):
        return "夏"
    if m in (9, 10, 11):
        return "秋"
    return "冬"


def generate_plan(constraints: dict, seed: int = None) -> dict:
    """
    主入口：返回完整"今日餐桌方案"。
    constraints: {people, dishes, soups, taboos, allergies, taste_prefs,
                  budget, time_budget, devices, max_difficulty, must_include,
                  pantry, nutrition_goal}
    """
    # seed 优先用参数，否则读 constraints（前端透传）
    if seed is None:
        seed = constraints.get("seed")
    engine = get_engine()
    rng = random.Random(seed) if seed is not None else random.Random()

    # 时令：未显式指定则按当前月份
    if not constraints.get("season"):
        constraints["season"] = current_season()

    # 家庭味觉画像（软约束打分用，有反馈才生效）
    profile = TasteProfile()
    if profile.data.get("count"):
        constraints["profile"] = profile

    menu, info = engine.recommend(constraints, rng=rng)
    if not menu:
        return {"ok": False, "error": info.get("error", "无符合条件的菜"), "info": info}

    shopping = build_shopping_list(menu, people=constraints.get("people", 1))
    nutrition = analyze(menu, people=constraints.get("people", 1), goal=constraints.get("nutrition_goal"))

    # LLM 节点（可选，BYOK）
    llm_cfg = get_llm_config()
    llm = LLMClient(**llm_cfg)
    pairing_note = _llm_pairing_note(menu, constraints, llm) if llm.available else _template_pairing_note(menu, constraints)

    return {
        "ok": True,
        "menu": menu,
        "pairing_note": pairing_note,
        "shopping": shopping,
        "nutrition": nutrition,
        "info": info,
        "llm_used": llm.available,
        "seed": seed,
    }


def generate_weekly(constraints: dict, days: int = 7, seed: int = None) -> dict:
    """周计划入口：N 天不重样 + 周合并采购清单。"""
    engine = get_engine()
    if not constraints.get("season"):
        constraints["season"] = current_season()
    profile = TasteProfile()
    if profile.data.get("count"):
        constraints["profile"] = profile
    return generate_weekly_plan(engine, constraints, days=days, seed=seed)


def reuse_plan(recipe_name: str, n: int = 3) -> dict:
    """一菜两吃入口：给剩菜找二次加工方案。"""
    engine = get_engine()
    return suggest_reuse(engine, recipe_name, n=n)


def simplify_recipe(recipe_name: str) -> dict:
    """家常简化版做法：用常见调料替代复杂调料（LLM，BYOK）。"""
    from ..core.leftover import find_recipe
    engine = get_engine()
    recipe = find_recipe(engine, recipe_name)
    if recipe is None:
        return {"ok": False, "error": f"没找到菜「{recipe_name}」，请换个菜名试试"}

    llm = LLMClient(**get_llm_config())
    if not llm.available:
        return {"ok": False, "error": "需要先配置 LLM（前端「高级配置 → LLM」或本地 Ollama）才能生成简化做法", "recipe": recipe}

    ingredients = "、".join(i.get("name", "") for i in recipe.get("ingredients", []))
    steps_text = ""
    for g in recipe.get("steps", []):
        if g.get("group"):
            steps_text += f"\n【{g['group']}】"
        for st in g.get("steps", []):
            steps_text += f"\n{st['text']}"
            for sub in st.get("sub", []):
                steps_text += f"（{sub}）"

    prompt = (
        "你是家常菜老师傅。把下面这道菜改写成『家常简化版』做法。\n"
        "要求：\n"
        "1. 只用家里常备调料：盐、生抽、老抽、料酒、白糖、醋、葱、姜、蒜（能不用就不放，缺一样也能做）\n"
        "2. 去掉豆瓣酱、蚝油、十三香、八角桂皮香叶草果、咖喱、黄油奶油、各种酱料等复杂调料；\n"
        "   实在需要风味的，用常见调料替代并说明怎么替\n"
        "3. 步骤精简到 4-7 步，每步一句大白话，保留原菜的核心口感和做法\n"
        "4. 输出纯文本，格式如下（不要 markdown 标题符号）：\n"
        "家常版·{菜名}\n"
        "调料：……\n"
        "做法：\n"
        "1. ……\n"
        "2. ……\n"
        "替代说明：……\n\n"
        f"原菜名：{recipe['name']}\n"
        f"原原料：{ingredients}\n"
        f"原做法：{steps_text}\n"
    )
    try:
        reply = llm.chat([{"role": "user", "content": prompt}], temperature=0.5, max_tokens=900)
        return {"ok": True, "recipe": recipe, "simplified": reply.strip(), "llm_used": True}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200], "recipe": recipe}
