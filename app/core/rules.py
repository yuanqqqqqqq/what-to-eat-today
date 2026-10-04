# -*- coding: utf-8 -*-
"""
约束规则表：忌口/过敏 -> 食材关键词、设备 -> 工具关键词、口味 -> 关键词。
这是"约束内随机"的硬约束数据，独立成文件便于维护。
"""

# 忌口/过敏 -> 匹配的食材关键词（命中即排除）
TABOO_RULES = {
    "辣": ["辣椒", "小米辣", "小米椒", "花椒", "豆瓣", "辣椒粉", "干辣椒", "剁椒", "泡椒", "辣酱", "麻辣", "香辣", "辣子", "水煮", "青椒", "红椒"],
    "海鲜": ["虾", "蟹", "鱼", "贝", "蛤", "鱿鱼", "海参", "扇贝", "蚝", "螺", "蛏", "海带", "紫菜", "鳕鱼", "鲈鱼", "带鱼", "黄鱼"],
    "猪肉": ["猪", "五花", "排骨", "里脊", "培根", "腊肉", "火腿", "肘子", "猪蹄"],
    "牛肉": ["牛肉", "牛腩", "牛排", "牛柳"],
    "羊肉": ["羊肉", "羊排", "羊"],
    "禽肉": ["鸡", "鸭", "鹅", "鸽子"],
    "蛋": ["鸡蛋", "鸭蛋", "蛋"],
    "奶制品": ["牛奶", "奶酪", "黄油", "奶油", "芝士", "炼乳", "酸奶"],
    "花生": ["花生"],
    "豆制品": ["豆腐", "豆干", "腐竹", "豆浆", "豆皮", "豆芽"],
    "菌菇": ["蘑菇", "香菇", "金针菇", "杏鲍菇", "木耳", "银耳", "菌"],
    "香菜": ["香菜"],
    "葱": ["葱"],
    "蒜": ["蒜"],
    "姜": ["姜"],
    "酒精": ["啤酒", "料酒", "白酒", "红酒", "黄酒", "米酒", "朗姆酒", "威士忌"],
}

# 过敏常用映射（可与忌口共用关键词）
ALLERGY_RULES = {
    "花生": ["花生"],
    "海鲜": TABOO_RULES["海鲜"],
    "蛋": TABOO_RULES["蛋"],
    "奶": TABOO_RULES["奶制品"],
    "大豆": ["豆腐", "豆干", "腐竹", "豆浆", "豆皮", "黄豆", "毛豆"],
    "麸质": ["面粉", "面条", "面包", "饼", "饺子", "馒头", "馄饨"],
}

# 设备 -> 工具关键词（菜的 tools 命中即"需要该设备"）
DEVICE_RULES = {
    "烤箱": ["烤箱"],
    "空气炸锅": ["空气炸锅"],
    "微波炉": ["微波炉"],
    "高压锅": ["高压锅", "压力锅"],
    "破壁机": ["破壁机", "料理机", "榨汁机", "搅拌机"],
    "面包机": ["面包机"],
    "蒸锅": ["蒸锅", "蒸笼"],
    "电饭煲": ["电饭煲"],
}

# 口味偏好 -> 关键词（打分阶段软约束）
TASTE_RULES = {
    "清淡": ["清蒸", "白灼", "水煮", "清炒", "炖", "汤"],
    "川辣": ["辣", "麻辣", "豆瓣", "泡椒", "剁椒", "水煮"],
    "酸甜": ["糖醋", "番茄", "酸甜", "糖", "醋"],
    "咸鲜": ["酱", "卤", "红烧", "蒜蓉", "蚝油"],
    "重口": ["红烧", "香辣", "孜然", "烧烤", "干锅"],
}


def ingredient_hit(recipe, taboo_keywords):
    """检查一道菜（菜名 + 原料）是否命中忌口关键词"""
    text = recipe.get("name", "") + " "
    text += " ".join(ing["name"] for ing in recipe.get("ingredients", []))
    text += " " + " ".join(c["name"] for c in recipe.get("calculations", []))
    return any(kw in text for kw in taboo_keywords)


def recipe_needs_devices(recipe):
    """返回一道菜需要的设备集合（如 {'烤箱'}）"""
    needed = set()
    for tool in recipe.get("tools", []):
        for dev, kws in DEVICE_RULES.items():
            if any(kw in tool for kw in kws):
                needed.add(dev)
    return needed


def taste_keywords(prefs):
    """把口味偏好列表展开成关键词集合"""
    kws = set()
    for p in prefs:
        kws.update(TASTE_RULES.get(p, []))
    return kws


# ---------- 调料/葱姜蒜过滤（供画像、一菜两吃复用）----------
# 含这些词根的食材属于调料/香料，不作为"实质主料"参与偏好沉淀或复用匹配
SEASONING_ROOTS = (
    "盐", "糖", "油", "酱油", "醋", "酒", "蚝油", "豆瓣", "花椒", "胡椒",
    "辣椒", "辣", "淀粉", "生粉", "味精", "鸡精", "五香", "孜然", "芝麻",
    "葱", "洋葱", "姜", "蒜", "香菜", "蜂蜜", "番茄酱", "沙拉", "芥末",
    "八角", "桂皮", "香叶", "草果", "酱", "汁", "露", "水", "抽", "豉",
)
# 含"粉"但属于主食/可复用（非调料粉）
STARCH_NOUNS = ("粉丝", "米粉", "河粉", "凉粉", "粉条", "粉皮", "通心粉")


def is_substantive_ingredient(name: str) -> bool:
    """是否为实质主料（非调料/葱姜蒜）。"""
    if name in STARCH_NOUNS:
        return True
    return not any(root in name for root in SEASONING_ROOTS)


def substantive_ingredients(names: list) -> list:
    """过滤调料/葱姜蒜，返回实质主料列表（保持原顺序、去重）。"""
    out = []
    for n in names:
        if n and n not in out and is_substantive_ingredient(n):
            out.append(n)
    return out


# ---------- 家常化：默认随机时过滤（数据保留在库中，可通过搜索查到） ----------
# 名贵食材：彻底不家常，默认不随机
PREMIUM_INGREDIENTS = (
    "鲍鱼", "龙虾", "鱼翅", "海参", "三文鱼", "鳕鱼", "松茸", "甲鱼", "鹅肝",
    "鱼子酱", "大闸蟹", "扇贝", "生蚝", "海螺", "牛蛙", "燕窝",
)
# 偏贵肉类：默认不随机，但数据保留可搜索（用户确认：牛羊肉不进随机）
PREMIUM_RED_MEAT = ("牛肉", "牛腩", "牛排", "牛柳", "牛腱", "肥牛", "牛尾", "羊肉", "羊排", "羊腿")

# 西式/异国菜（咖喱、奶油汤、意式等）：默认不随机，但数据保留可搜索
NON_HOMELY_KWS = (
    "咖喱", "椰浆", "椰奶", "香茅", "冬阴功", "罗宋", "意式", "意大利",
    "披萨", "意面", "通心粉", "帕马森", "味噌", "北非", "苏格兰", "奶油汤", "黄油鸡",
)


def is_homely(recipe) -> bool:
    """是否家常（不含名贵/偏贵食材、西式/异国菜）。小龙虾、虾、普通螃蟹视为家常。"""
    text = recipe.get("name", "") + " " + " ".join(
        i.get("name", "") for i in recipe.get("ingredients", []))
    for kw in PREMIUM_INGREDIENTS:
        if kw in text:
            # "龙虾"会误伤"小龙虾"，小龙虾是家常夜宵
            if kw == "龙虾" and "小龙虾" in text:
                continue
            return False
    for kw in PREMIUM_RED_MEAT:
        if kw in text:
            return False
    for kw in NON_HOMELY_KWS:
        if kw in text:
            return False
    return True
