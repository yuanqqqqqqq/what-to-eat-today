# -*- coding: utf-8 -*-
"""
营养分析（粗略版）：MVP 只给热量总量 + 荤素比例，不精确到蛋白质/脂肪克数。
用户目标"减脂/增肌/均衡"只做提示，健身版后续接中国食物成分表 CSV。
"""


def analyze(menu: list, people: int = 1, goal: str = None) -> dict:
    total_kcal = sum(r.get("calories_kcal") or 0 for r in menu)
    meat = [r for r in menu if r.get("dish_type") == "荤"]
    veg = [r for r in menu if r.get("dish_type") == "素"]
    soup = [r for r in menu if r.get("dish_type") == "汤"]

    # 经验比例（粗估）：蛋白质20% / 脂肪30% / 碳水50%
    protein_kcal = round(total_kcal * 0.20)
    fat_kcal = round(total_kcal * 0.30)
    carb_kcal = round(total_kcal * 0.50)

    per_person = round(total_kcal / max(1, people))

    # 荤素比
    meat_kcal = sum(r.get("calories_kcal") or 0 for r in meat)
    veg_kcal = sum(r.get("calories_kcal") or 0 for r in veg)

    tips = []
    if goal == "减脂":
        if per_person > 600:
            tips.append("人均热量偏高，减脂期建议人均 500-600 大卡，可把一道荤菜换成清蒸或白灼做法。")
        elif veg_kcal < meat_kcal:
            tips.append("蔬菜比例偏低，建议增加一道绿叶菜，增加饱腹感。")
    elif goal == "增肌":
        if protein_kcal < total_kcal * 0.25:
            tips.append("蛋白质偏少，增肌期建议增加蛋、瘦肉或鱼虾。")
    elif goal == "均衡":
        if not veg:
            tips.append("缺少蔬菜，建议加一道绿叶菜或瓜果类。")
        if not meat and not any(r.get("dish_type") == "荤" for r in menu):
            tips.append("缺少优质蛋白，建议加蛋、豆制品或肉类。")

    return {
        "total_kcal": total_kcal,
        "per_person_kcal": per_person,
        "protein_kcal": protein_kcal,
        "fat_kcal": fat_kcal,
        "carb_kcal": carb_kcal,
        "meat_count": len(meat),
        "veg_count": len(veg),
        "soup_count": len(soup),
        "tips": tips,
        "goal": goal,
    }


def assess(menu: list, nutrition: dict, goal: str = None) -> list:
    """
    营养达标评估：返回未达标的问题列表（空 = 达标）。
    供多 Agent 编排里的"营养师"节点用：有问题则回退给规划师重新出菜单。
    """
    issues = []
    total = nutrition.get("total_kcal") or 0
    if goal == "减脂":
        if nutrition.get("per_person_kcal", 0) > 600:
            issues.append("热量偏高")
        if nutrition.get("veg_count", 0) == 0:
            issues.append("缺蔬菜")
    elif goal == "增肌":
        if nutrition.get("protein_kcal", 0) < total * 0.25:
            issues.append("蛋白质偏少")
    elif goal == "均衡":
        if nutrition.get("veg_count", 0) == 0:
            issues.append("缺蔬菜")
        if nutrition.get("meat_count", 0) == 0:
            issues.append("缺优质蛋白")
    # 通用：有荤却完全没蔬菜，始终提醒（除非本来就没点菜/汤之外的）
    has_meat = any(r.get("dish_type") == "荤" for r in menu)
    if has_meat and nutrition.get("veg_count", 0) == 0 and "缺蔬菜" not in issues:
        issues.append("缺蔬菜")
    return issues
