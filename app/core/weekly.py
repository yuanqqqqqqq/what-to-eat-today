# -*- coding: utf-8 -*-
"""
周计划生成器：连续多天去重 + 跨天荤素均衡 + 周合并采购清单。

核心：把单餐约束引擎跑 N 天，每天把已用过的菜 id 传给引擎做硬排除（一周不重样）；
同时把"前几天的食材"作为软信号传下去，让整周不至于反复同一批主料——
但力度很轻，因为食材复用本来就是采购清单的优势（买一次用几天）。
"""
import random

from .rules import substantive_ingredients
from .shopping import build_shopping_list
from .nutrition import analyze


def _merge_week_shopping(days: list, people: int) -> dict:
    """把整周所有菜的原料合并成一份周采购清单（分区 + 同类项合并）。"""
    all_menu = []
    for d in days:
        all_menu.extend(d["menu"])
    return build_shopping_list(all_menu, people=people)


def _clamp_days(days) -> int:
    """天数取值：缺省 7，范围 1~14。

    注意别写成 `days or 7`：那会把 0 当成"没传"而给出 7 天。
    """
    if days is None or days == "":
        return 7
    try:
        return max(1, min(int(days), 14))
    except (TypeError, ValueError):
        return 7


def generate_weekly_plan(engine, constraints: dict, days: int = 7, seed: int = None) -> dict:
    """
    返回 {days: [{day, menu, shopping, nutrition, info}], week_shopping, summary}
    """
    rng = random.Random(seed) if seed is not None else random.Random()
    days_n = _clamp_days(days)
    people = max(1, int(constraints.get("people", 1) or 1))

    used_ids = set()
    recent_ingredients = set()
    out_days = []
    repeated_days = []   # 这些天因为候选不够，放宽了"不重样"

    for i in range(days_n):
        day_constraints = dict(constraints)
        day_constraints["exclude_ids"] = used_ids
        day_constraints["recent_ingredients"] = recent_ingredients
        menu, info = engine.recommend(day_constraints, rng=rng)

        # 兜底：约束太紧（候选被前几天吃光）时放宽去重，保证每天都出餐
        if not menu and used_ids:
            day_constraints["exclude_ids"] = set()
            menu, info = engine.recommend(day_constraints, rng=rng)
            if menu:
                repeated_days.append(i + 1)
                info = dict(info, dedupe_relaxed=True)

        if not menu:
            out_days.append({"day": i + 1, "menu": [],
                             "error": info.get("error", "无符合条件的菜"), "info": info})
            continue

        used_ids.update(r["id"] for r in menu)
        recent_ingredients.update(
            ing for r in menu
            for ing in substantive_ingredients([x.get("name", "") for x in r.get("ingredients", [])])
        )
        out_days.append({
            "day": i + 1,
            "menu": menu,
            "shopping": build_shopping_list(menu, people=people),
            "nutrition": analyze(menu, people=people, goal=constraints.get("nutrition_goal")),
            "info": info,
        })

    days_with_menu = [d for d in out_days if d.get("menu")]
    week_shopping = _merge_week_shopping(days_with_menu, people)
    all_menu = [r for d in days_with_menu for r in d["menu"]]
    meat = sum(1 for r in all_menu if r.get("dish_type") == "荤")
    veg = sum(1 for r in all_menu if r.get("dish_type") == "素")
    soup = sum(1 for r in all_menu if r.get("dish_type") == "汤")

    return {
        "days": out_days,
        "week_shopping": week_shopping,
        "summary": {
            "days": days_n,
            "days_with_menu": len(days_with_menu),
            "total_dishes": len(all_menu),
            "unique_dishes": len({r["id"] for r in all_menu}),
            "meat": meat, "veg": veg, "soup": soup,
            "balanced_days": sum(1 for d in days_with_menu if d.get("info", {}).get("balanced")),
            "fallback_days": sum(1 for d in days_with_menu if d.get("info", {}).get("fallback")),
            "repeated_days": repeated_days,
            "est_cost_yuan": week_shopping.get("est_cost_yuan"),
            "total_kcal": week_shopping.get("total_kcal"),
        },
    }
