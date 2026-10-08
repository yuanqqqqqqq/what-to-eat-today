# -*- coding: utf-8 -*-
"""
营养分析（估算版）。

口径说明（重要）：
- 热量：直接取菜谱库里的 calories_kcal（由 scripts/recalc_calories.py 按主料密度模型算好）。
- 蛋白质 / 脂肪 / 碳水 / 纤维：现算，来自中国食物成分表（FoodDB.estimate_macros）。
- 两条数据源独立，所以现算的营养素会和整菜热量对不上时就说明这条数据不可信：
  用 4P+9F+4C 与 calories_kcal 做量级交叉校验，偏差过大的菜不计入营养素合计，
  并在 coverage / skipped 里如实告知"有几道菜没算进去"，而不是硬凑一个数。

这里所有数字都是估算，不是称重实测，更不是医学结论。
"""

# 交叉校验区间：成分表推出的能量 / 菜谱热量，落在这个区间内才认为这条营养素估算可信
ENERGY_RATIO_MIN = 0.5
ENERGY_RATIO_MAX = 2.0

DISCLAIMER = "热量与营养素均为按食材成分表推算的估算值，不是称重实测，也不构成营养或医疗建议。"

# 三大营养素供能系数（kcal/g）
KCAL_PER_G = {"protein": 4.0, "fat": 9.0, "carb": 4.0}


def _macro_energy(protein_g: float, fat_g: float, carb_g: float) -> float:
    return protein_g * KCAL_PER_G["protein"] + fat_g * KCAL_PER_G["fat"] + carb_g * KCAL_PER_G["carb"]


def _analyze_macros(menu: list) -> dict:
    """逐菜估算三大营养素，用整菜热量做量级交叉校验，剔除明显不可信的条目。"""
    from .food_db import FoodDB

    totals = {"protein_g": 0.0, "fat_g": 0.0, "carb_g": 0.0, "fiber_g": 0.0}
    counted, skipped = 0, []
    for r in menu:
        m = FoodDB.estimate_macros(r)
        energy = _macro_energy(m["protein_g"], m["fat_g"], m["carb_g"])
        kcal = r.get("calories_kcal") or 0
        if energy <= 0 or kcal <= 0:
            skipped.append(r.get("name", ""))
            continue
        if not (ENERGY_RATIO_MIN <= energy / kcal <= ENERGY_RATIO_MAX):
            skipped.append(r.get("name", ""))
            continue
        for k in totals:
            totals[k] += m[k]
        counted += 1

    return {
        "macros": {k: round(v, 1) for k, v in totals.items()},
        "macro_counted": counted,
        "macro_total": len(menu),
        "macro_skipped": skipped,
        "macro_coverage": round(counted / len(menu), 2) if menu else 0.0,
    }


def analyze(menu: list, people: int = 1, goal: str = None) -> dict:
    """返回一餐的营养估算。所有字段都是估算值，见 DISCLAIMER。"""
    people = max(1, int(people or 1))
    menu = menu or []

    total_kcal = sum(r.get("calories_kcal") or 0 for r in menu)
    per_person = round(total_kcal / people)

    meat = [r for r in menu if r.get("dish_type") == "荤"]
    veg = [r for r in menu if r.get("dish_type") == "素"]
    soup = [r for r in menu if r.get("dish_type") == "汤"]
    meat_kcal = sum(r.get("calories_kcal") or 0 for r in meat)
    veg_kcal = sum(r.get("calories_kcal") or 0 for r in veg)

    mac = _analyze_macros(menu)
    mp = mac["macros"]
    counted = mac["macro_counted"]

    # 一条都没算出来时，营养素给 None（"未知"），绝不能给 0（"没有"）
    if counted:
        reported = {k: round(v, 1) for k, v in mp.items()}
        per_person_macros = {k: round(v / people, 1) for k, v in mp.items()}
    else:
        reported = {k: None for k in mp}
        per_person_macros = {k: None for k in mp}

    # 供能比：由克数直接换算，不用固定的 20/30/50% 经验比例硬套
    macro_energy = _macro_energy(mp["protein_g"], mp["fat_g"], mp["carb_g"])
    if counted and macro_energy > 0:
        shares = {
            "protein_pct": round(mp["protein_g"] * KCAL_PER_G["protein"] / macro_energy * 100),
            "fat_pct": round(mp["fat_g"] * KCAL_PER_G["fat"] / macro_energy * 100),
            "carb_pct": round(mp["carb_g"] * KCAL_PER_G["carb"] / macro_energy * 100),
        }
    else:
        shares = {"protein_pct": None, "fat_pct": None, "carb_pct": None}

    return {
        # ---- 热量（口径 = 菜谱库数据，始终可信）----
        "total_kcal": total_kcal,
        "per_person_kcal": per_person,
        # ---- 三大营养素（估算，克；不可信时为 None）----
        "protein_g": reported["protein_g"],
        "fat_g": reported["fat_g"],
        "carb_g": reported["carb_g"],
        "fiber_g": reported["fiber_g"],
        "per_person_macros": per_person_macros,
        # 供能比（%）
        **shares,
        # ---- 荤素结构 ----
        "meat_count": len(meat),
        "veg_count": len(veg),
        "soup_count": len(soup),
        "meat_kcal": meat_kcal,
        "veg_kcal": veg_kcal,
        # 荤素比（按热量）：没有素菜算不出比值 → None；没有荤菜 → 0.0
        "meat_veg_ratio": round(meat_kcal / veg_kcal, 1) if veg_kcal else None,
        # ---- 数据可信度：有几道菜的营养素被交叉校验剔除了 ----
        "macro_counted": counted,
        "macro_total": mac["macro_total"],
        "macro_coverage": mac["macro_coverage"],
        "macro_skipped": mac["macro_skipped"],
        "macro_note": _macro_note(counted, mac["macro_total"], mac["macro_skipped"]),
        # ---- 提示与免责声明 ----
        "tips": _tips(menu, meat, veg, per_person, shares, total_kcal, goal),
        "goal": goal,
        "disclaimer": DISCLAIMER,
        "estimated": True,
    }


def _macro_note(counted: int, total: int, skipped: list) -> str:
    """如实说明营养素估算覆盖了多少道菜。"""
    if total == 0:
        return ""
    if counted == total:
        return ""
    if counted == 0:
        return "这份菜单的食材在成分表里没有匹配，暂不给出三大营养素估算。"
    names = "、".join(skipped[:3])
    more = f" 等 {len(skipped)} 道" if len(skipped) > 3 else ""
    return f"其中「{names}」{more}的成分表匹配不足，未计入营养素合计（{counted}/{total} 道有数据）。"


def _tips(menu, meat, veg, per_person, shares, total_kcal, goal) -> list:
    """按目标给建议。只用真实算出来的指标，不给没有依据的结论。"""
    tips = []

    if goal == "减脂":
        if per_person > 600:
            tips.append(f"人均约 {per_person} 大卡，减脂期建议 500-600 大卡，可把一道荤菜换成清蒸或白灼。")
        if not veg:
            tips.append("这一餐没有素菜，加一道绿叶菜更扛饿。")
    elif goal == "增肌":
        if shares["protein_pct"] is not None and shares["protein_pct"] < 20:
            tips.append(f"蛋白质供能约 {shares['protein_pct']}%，增肌期建议提到 20-30%，可加蛋、瘦肉或鱼虾。")
        if not meat and not any(r.get("dish_type") == "汤" for r in menu):
            tips.append("缺少优质蛋白来源，建议加一道荤菜或豆制品。")
    elif goal == "控糖":
        if shares["carb_pct"] is not None and shares["carb_pct"] > 60:
            tips.append(f"碳水供能约 {shares['carb_pct']}%，控糖期建议用杂粮/薯类替换部分精制主食。")
        if any(r.get("category_cn") in ("甜点", "饮品") for r in menu):
            tips.append("含甜点或含糖饮品，控糖期建议减少。")
    elif goal == "均衡":
        if not veg:
            tips.append("缺少蔬菜，建议加一道绿叶菜或瓜果类。")
        if not meat:
            tips.append("缺少优质蛋白，建议加蛋、豆制品或肉类。")
    else:
        if not veg and meat:
            tips.append("这餐偏荤，搭配一道素菜会更均衡。")

    if veg and meat and not tips:
        tips.append("有荤有素，结构不错。")
    return tips


def assess(menu: list, nutrition: dict, goal: str = None) -> list:
    """
    营养达标评估：返回未达标的问题列表（空 = 达标）。
    供多 Agent 编排里的"营养师"节点用：有问题则回退给规划师重新出菜单。

    只在"确实有问题"时返回问题，避免回退空转（例如 1 道菜的菜单不要求荤素齐全）。
    """
    issues = []
    if not menu:
        return ["菜单为空"]

    per_person = nutrition.get("per_person_kcal", 0)
    veg_count = nutrition.get("veg_count", 0)
    meat_count = nutrition.get("meat_count", 0)
    dish_slots = sum(1 for r in menu if r.get("dish_type") in ("荤", "素"))

    if goal == "减脂":
        if per_person > 650:
            issues.append("热量偏高")
        if dish_slots >= 2 and veg_count == 0:
            issues.append("缺蔬菜")
    elif goal == "增肌":
        if nutrition.get("protein_pct") is not None and nutrition["protein_pct"] < 20:
            issues.append("蛋白质偏少")
    elif goal == "控糖":
        if dish_slots >= 2 and veg_count == 0:
            issues.append("缺蔬菜")
        if nutrition.get("carb_pct") is not None and nutrition["carb_pct"] > 65:
            issues.append("碳水偏高")
    elif goal == "均衡":
        if dish_slots >= 2 and veg_count == 0:
            issues.append("缺蔬菜")
        if meat_count == 0 and dish_slots >= 2:
            issues.append("缺优质蛋白")
    else:
        # 未指定目标：只在"整桌都是荤菜"时提醒（有荤无素）
        if dish_slots >= 2 and meat_count == dish_slots and veg_count == 0:
            issues.append("缺蔬菜")

    return issues
