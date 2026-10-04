# -*- coding: utf-8 -*-
"""
场景模板（路线图 v0.4）：便当 / 家宴 / 控糖 / 减脂轻食。

每个场景 = 预设约束(defaults) + 硬排除(exclude) + 软约束加分(score)，
一键应用后由约束引擎正常跑，用户仍可在此基础上微调。
"""
from .rules import substantive_ingredients

SCENES = [
    {
        "id": "bento",
        "name": "便当",
        "icon": "🍱",
        "desc": "适合带饭：快手、少汤、耐放",
        "defaults": {"dishes": 2, "soups": 0, "time_budget": 30, "max_difficulty": 3},
    },
    {
        "id": "feast",
        "name": "家宴",
        "icon": "🥂",
        "desc": "请客吃饭：硬菜多、有荤有素有汤",
        "defaults": {"dishes": 4, "soups": 1, "max_difficulty": None},
    },
    {
        "id": "sugar_control",
        "name": "控糖",
        "icon": "🩸",
        "desc": "控糖人群：避开甜食精制碳水，多蔬菜",
        "defaults": {"dishes": 2, "soups": 1},
    },
    {
        "id": "light",
        "name": "减脂轻食",
        "icon": "🥗",
        "desc": "低热量、多蔬菜，目标减脂",
        "defaults": {"dishes": 2, "soups": 1, "max_difficulty": 3, "nutrition_goal": "减脂"},
    },
    {
        "id": "home",
        "name": "家常",
        "icon": "🍳",
        "desc": "常见调料、做法简单，妈妈的味道",
        "defaults": {"dishes": 2, "soups": 1, "max_difficulty": 3},
    },
]

# 非家常调料：家里通常不常备、需专门购买的（命中即排除在家常场景之外）
COMPLEX_SEASONINGS = (
    "豆瓣", "蚝油", "十三香", "五香粉", "孜然", "八角", "桂皮", "香叶", "草果",
    "咖喱", "番茄酱", "沙拉", "芥末", "芝麻酱", "甜面酱", "柱候酱", "海鲜酱",
    "沙茶", "腐乳", "豆豉", "泡椒", "剁椒", "郫县", "黄油", "奶油", "炼乳",
    "椰浆", "鱼露", "虾酱", "味噌", "味淋", "照烧", "蒲烧", "芝士", "罗勒",
    "迷迭香", "百里香", "黑胡椒", "香草", "南姜", "柠檬叶", "XO", "烧烤酱",
    "沙拉酱", "甜辣酱", "蒜蓉辣酱", "老干妈",
)

# 名贵/不家常食材（家常场景排除，追求乡土气）
LUXURY_INGREDIENTS = (
    "海参", "鲍鱼", "鱼翅", "燕窝", "松茸", "和牛", "龙虾", "帝王蟹",
    "鹅肝", "藏红花", "雪蛤", "花胶", "鱼子酱", "黑松露",
)

# 各场景需硬排除的类别（category_cn）
SCENE_EXCLUDE_CATEGORIES = {
    "bento": {"汤", "饮品", "甜点"},
    "sugar_control": {"甜点", "饮品"},
    "light": {"甜点", "饮品"},
}

# 控糖需硬排除的高糖/高 GI 食材（命中即排除）
SUGAR_INGREDIENTS = (
    "蜂蜜", "炼乳", "可乐", "巧克力", "冰糖", "红糖", "白糖", "砂糖", "糖浆",
    "糯米", "糍粑", "醪糟", "麦芽糖", "果酱", "糖粉", "焦糖", "炼奶", "雪碧",
)

# 粗粮/低 GI 主食（控糖场景加分）
LOW_GI_STAPLES = ("玉米", "燕麦", "荞麦", "糙米", "杂粮", "藜麦", "全麦", "小米")


def get_scene(scene_id):
    return next((s for s in SCENES if s["id"] == scene_id), None)


def apply_scene_defaults(scene_id, constraints: dict) -> dict:
    """把场景预设合并进 constraints（用户已填的字段优先）。"""
    scene = get_scene(scene_id)
    if not scene:
        return constraints
    out = dict(constraints)
    for k, v in scene["defaults"].items():
        # 用户未设置（None/0/空）时才用场景预设
        if out.get(k) in (None, "", [], 0):
            out[k] = v
    out["scene_id"] = scene_id
    return out


def scene_hard_exclude(scene_id, recipe: dict) -> bool:
    """返回 True 表示该菜在场景下应被排除。"""
    if not scene_id:
        return False
    cat = recipe.get("category_cn")
    if cat in SCENE_EXCLUDE_CATEGORIES.get(scene_id, set()):
        return True
    # 便当：汤类不便携带（按 dish_type 排除，覆盖 category 为肉菜/素菜的羹汤）
    if scene_id == "bento" and recipe.get("dish_type") == "汤":
        return True
    if scene_id == "sugar_control":
        text = " ".join(i.get("name", "") for i in recipe.get("ingredients", []))
        if any(s in text for s in SUGAR_INGREDIENTS):
            return True
    if scene_id == "light":
        # 减脂轻食：超过 800 大卡的单菜直接排除（兼防热量数据异常）
        if (recipe.get("calories_kcal") or 0) > 800:
            return True
    if scene_id == "home":
        # 家常：排除需专门购买的非家常调料，及名贵食材
        text = " ".join(i.get("name", "") for i in recipe.get("ingredients", []))
        if any(s in text for s in COMPLEX_SEASONINGS):
            return True
        if any(s in text for s in LUXURY_INGREDIENTS):
            return True
    return False


def scene_score(scene_id, recipe: dict) -> float:
    """场景软约束加分（用于约束引擎的打分阶段）。"""
    if not scene_id:
        return 0.0
    s = 0.0
    d_type = recipe.get("dish_type")
    cat = recipe.get("category_cn")
    name = recipe.get("name", "")
    kcal = recipe.get("calories_kcal") or 0
    ings = substantive_ingredients([i.get("name", "") for i in recipe.get("ingredients", [])])

    if scene_id == "bento":
        # 耐放、好携带：素菜 / 凉拌 / 炖卤烧焖加分
        if d_type == "素":
            s += 1.0
        if any(k in name for k in ("凉拌", "炖", "卤", "烧", "焖", "炒")):
            s += 0.5
    elif scene_id == "feast":
        # 硬菜：高难度 + 水产 + 荤菜 + 炖菜（仪式感）
        if (recipe.get("difficulty") or 0) >= 4:
            s += 1.5
        if cat == "水产":
            s += 1.5
        if d_type == "荤":
            s += 0.5
        if any(k in name for k in ("炖", "蒸", "煲")):
            s += 0.5
    elif scene_id == "sugar_control":
        # 多蔬菜/菌菇/豆制品，优质蛋白加分，精制主食减分
        if d_type == "素":
            s += 1.5
        if any(k in ings for k in ("豆腐", "豆干", "腐竹", "豆皮")):
            s += 1.0
        if any(k in name for k in ("鱼", "虾", "鸡", "蛋", "豆腐", "菌", "菇")):
            s += 0.5
        if cat == "主食":
            if any(k in name for k in LOW_GI_STAPLES):
                s += 1.0
            else:
                s -= 1.0
    elif scene_id == "light":
        # 低热量 + 蔬菜加分，高热量减分
        if 0 < kcal <= 200:
            s += 1.5
        elif kcal >= 600:
            s -= 1.5
        if d_type == "素":
            s += 1.0
    elif scene_id == "home":
        # 越简单越家常：难度低、耗时短加分
        diff = recipe.get("difficulty") or 3
        s += max(0.0, (3 - diff)) * 0.5
        est = recipe.get("estimated_minutes") or 30
        if est <= 20:
            s += 0.8
    return s
