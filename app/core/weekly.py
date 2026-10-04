# -*- coding: utf-8 -*-
"""
周计划生成器：连续多天去重 + 跨天荤素均衡 + 周合并采购清单。

对应路线图 v0.2 的"周计划"。核心：把单餐约束引擎跑 N 天，
每天把已用过的菜 id 传给引擎做硬排除，实现一周不重样。
"""
import random

from .shopping import build_shopping_list
from .nutrition import analyze


def _merge_week_shopping(days: list, people: int) -> dict:
    """把整周所有菜的原料合并成一份周采购清单（分区 + 同类项合并）。"""
    all_menu = []
    for d in days:
        all_menu.extend(d["menu"])
    return build_shopping_list(all_menu, people=people)


def generate_weekly_plan(engine, constraints: dict, days: int = 7, seed: int = None) -> dict:
    """
    返回 {days: [{day, menu, shopping, nutrition, info}], week_shopping, summary}
    """
    rng = random.Random(seed) if seed is not None else random.Random()
    days_n = max(1, min(int(days or 7), 14))
    people = constraints.get("people", 1)

    used_ids = set()
    out_days = []
    for i in range(days_n):
        day_constraints = dict(constraints)
        day_constraints["exclude_ids"] = used_ids
        menu, info = engine.recommend(day_constraints, rng=rng)

        # 兜底：约束太紧凑不出全新菜单时，允许重复（保证每天都出餐）
        if not menu and used_ids:
            day_constraints["exclude_ids"] = set()
            menu, info = engine.recommend(day_constraints, rng=rng)

        if not menu:
            out_days.append({"day": i + 1, "menu": [], "error": info.get("error", "无符合条件的菜"), "info": info})
            continue

        used_ids.update(r["id"] for r in menu)
        out_days.append({
            "day": i + 1,
            "menu": menu,
            "shopping": build_shopping_list(menu, people=people),
            "nutrition": analyze(menu, people=people, goal=constraints.get("nutrition_goal")),
            "info": info,
        })

    week_shopping = _merge_week_shopping([d for d in out_days if d.get("menu")], people)
    # 简单荤素统计
    all_menu = [r for d in out_days for r in d.get("menu", [])]
    meat = sum(1 for r in all_menu if r.get("dish_type") == "荤")
    veg = sum(1 for r in all_menu if r.get("dish_type") == "素")
    soup = sum(1 for r in all_menu if r.get("dish_type") == "汤")

    return {
        "days": out_days,
        "week_shopping": week_shopping,
        "summary": {
            "days": days_n,
            "total_dishes": len(all_menu),
            "unique_dishes": len(used_ids),
            "meat": meat, "veg": veg, "soup": soup,
            "est_cost_yuan": week_shopping.get("est_cost_yuan"),
            "total_kcal": week_shopping.get("total_kcal"),
        },
    }
