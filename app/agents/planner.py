# -*- coding: utf-8 -*-
"""
方案编排器：约束引擎出菜单 -> 采购清单 -> 营养分析 -> 搭配说明 -> 做法整理。
对应 PRD 5.2 协作流程的"规则版"实现；LLM 节点在配置了 Key 后启用。
"""
import random
from datetime import datetime

import logging

from ..config import get_llm_config
from ..core.constraint_engine import ConstraintEngine
from ..core.food_db import dish_costs
from ..core.shopping import build_shopping_list
from ..core.nutrition import analyze
from ..core.profile import TasteProfile
from ..core.weekly import generate_weekly_plan
from ..core.leftover import suggest_reuse
from ..llm.client import LLMClient

logger = logging.getLogger(__name__)

# 模块级缓存：菜谱只加载一次
_ENGINE = None


def get_engine(reload: bool = False) -> ConstraintEngine:
    global _ENGINE
    if _ENGINE is None or reload:
        import json
        from ..paths import resource, data_file
        with open(resource("data/recipes.json"), encoding="utf-8") as f:
            recipes = json.load(f)
        user_file = data_file("user_recipes.json")
        if user_file.exists():
            with open(user_file, encoding="utf-8") as f:
                recipes = recipes + json.load(f)
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


def _pairing_note(menu, constraints, llm) -> tuple:
    """搭配说明。返回 (文案, 是否真的用了 LLM)。

    没有 Key、超时、报错、返回空 → 一律退回模板。返回值里的 used_llm 必须如实反映
    实际用了哪条路径，不能因为"配置了 Key"就宣称是 LLM 生成的。
    """
    if not llm.available:
        return _template_pairing_note(menu, constraints), False
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
        note = llm.chat([{"role": "user", "content": prompt}], temperature=0.7, max_tokens=300).strip()
        if note:
            return note, True
        logger.warning("搭配说明：LLM 返回空内容，改用模板")
    except Exception as e:
        logger.warning("搭配说明改用模板（LLM 不可用）：%s", e)
    return _template_pairing_note(menu, constraints), False


def _llm_pairing_note(menu, constraints, llm) -> str:
    """兼容旧调用：只要文案。内部逻辑见 _pairing_note。"""
    return _pairing_note(menu, constraints, llm)[0]


# ---------- 推荐理由 / 视觉标记（规则生成，不依赖 LLM）----------
def dish_reasons(recipe: dict, constraints: dict, max_reasons: int = 3) -> list:
    """用规则解释"为什么推荐这道菜"。确定性、可复现，无 LLM 也能给理由。

    保证至少返回一条：说不清"特别在哪"时，也要说明它为什么能出现在这张桌子上
    （符合你的约束），而不是留空让前端显示一个空白的理由区。
    """
    out = []
    if recipe.get("id") in set(constraints.get("locked_ids") or []):
        out.append("🔒 你锁定的")
    if recipe.get("id") in set(constraints.get("favorite_ids") or []):
        out.append("⭐ 你收藏过")

    pantry = [p.strip() for p in (constraints.get("pantry") or []) if p.strip()]
    if pantry:
        text = " ".join(i.get("name", "") for i in recipe.get("ingredients", []))
        hit = [p for p in pantry if p in text][:2]
        if hit:
            out.append("用上家里现有的「" + "、".join(hit) + "」")

    prefs = constraints.get("taste_prefs") or []
    tastes = set(recipe.get("taste") or [])
    matched = [p for p in prefs if p in tastes]
    if matched:
        out.append("合口味：" + "、".join(matched))

    # 先说"区别性"强的（快手/好上手），再说"放之四海皆准"的（四季皆宜），
    # 否则每道菜的第一条理由都是"四季皆宜"，信息量等于零
    est = recipe.get("estimated_minutes")
    if est and est <= 20:
        out.append(f"{est} 分钟快手")
    elif (recipe.get("difficulty") or 5) <= 2:
        out.append("新手友好")

    season = constraints.get("season")
    if season and recipe.get("season") == season:
        out.append("当季")
    elif recipe.get("season") == "四季":
        out.append("四季皆宜")

    if not out:
        # 兜底理由必须是真话：它确实通过了你的忌口/预算/时间等筛选
        out.append("符合你的忌口与预算约束")
    return out[:max_reasons]


_VISUAL = {"荤": "🍖", "素": "🥬", "汤": "🍲", "主食": "🍚",
           "甜点": "🍰", "饮品": "🥤", "半成品": "🥟", "其他": "🍽️"}
_SEAFOOD = ("鱼", "虾", "蟹", "贝", "蛤", "鱿", "螺", "蚝")


def dish_visual(recipe: dict) -> str:
    """给菜品一个视觉标记。用 emoji 而不是图片：不依赖网络、不会加载失败、也没有假图。"""
    if recipe.get("category_cn") == "水产" or any(
            k in recipe.get("name", "") for k in _SEAFOOD):
        return "🐟"
    return _VISUAL.get(recipe.get("dish_type") or "其他", "🍽️")


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

    # LLM 节点（可选，BYOK）：没有配置 / 超时 / 报错都退回模板，核心推荐不受影响
    llm_cfg = get_llm_config()
    llm = LLMClient(**llm_cfg)
    pairing_note, used_llm = _pairing_note(menu, constraints, llm)

    return {
        "ok": True,
        "menu": menu,
        "pairing_note": pairing_note,
        "shopping": shopping,
        "nutrition": nutrition,
        "info": info,
        "llm_used": used_llm,
        "seed": seed,
        "mode": "pipeline",
        # 前端展示用：推荐理由 / 单菜成本 / 视觉标记（id -> 值）
        "reasons": {r.get("id"): dish_reasons(r, constraints) for r in menu},
        "costs": dish_costs(menu, people=constraints.get("people", 1)),
        "visuals": {r.get("id"): dish_visual(r) for r in menu},
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
        logger.warning("简化做法生成失败：%s", e)
        return {"ok": False, "error": str(e)[:200], "recipe": recipe}
