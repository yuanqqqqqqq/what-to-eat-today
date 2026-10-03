# -*- coding: utf-8 -*-
"""
采购清单生成：按菜市场分区组织 + 合并同类项。
对应 PRD 输出侧 ③ 合并采购清单。
"""
from collections import OrderedDict

# 分区 -> 食材关键词（按顺序匹配，先命中先归类）
ZONE_KEYWORDS = [
    ("肉禽", ["肉", "猪", "牛", "羊", "鸡", "鸭", "鹅", "排骨", "里脊", "五花", "培根", "腊肉", "火腿", "牛腩", "鸡翅", "鸡腿", "鸡胸", "鸭肉"]),
    ("水产", ["鱼", "虾", "蟹", "贝", "蛤", "鱿鱼", "海参", "扇贝", "蚝", "螺", "鳕鱼", "鲈鱼", "带鱼", "黄鱼", "生蚝"]),
    ("蛋奶", ["蛋", "牛奶", "奶酪", "黄油", "奶油", "芝士", "炼乳"]),
    ("蔬菜", ["菜", "瓜", "茄", "豆", "萝卜", "土豆", "葱", "姜", "蒜", "洋葱", "辣椒", "青椒", "红椒", "西兰花", "菠菜", "白菜", "生菜", "韭菜", "芹菜", "莴笋", "莲藕", "山药", "玉米", "南瓜", "冬瓜", "黄瓜", "丝瓜", "苦瓜", "西红柿", "番茄", "蘑菇", "香菇", "金针菇", "木耳", "笋", "香菜", "娃娃菜", "空心菜", "花菜", "油麦菜", "苋菜", "豆芽", "毛豆", "豌豆"]),
    ("菌菇", ["香菇", "蘑菇", "金针菇", "杏鲍菇", "木耳", "银耳"]),
    ("调料", ["盐", "糖", "油", "酱油", "醋", "料酒", "生抽", "老抽", "蚝油", "豆瓣", "花椒", "胡椒", "淀粉", "味精", "鸡精", "五香", "孜然", "辣椒粉", "干辣椒", "八角", "桂皮", "香叶", "草果", "芝麻", "芥末", "番茄酱", "沙拉", "蜂蜜"]),
    ("主食", ["米", "面", "粉", "馒头", "饺子", "面包", "饼", "吐司", "年糕", "粉丝", "面条", "米饭"]),
    ("其他", []),
]


def classify(name: str) -> str:
    for zone, kws in ZONE_KEYWORDS:
        for kw in kws:
            if kw in name:
                return zone
    return "其他"


def build_shopping_list(menu: list, people: int = 1) -> dict:
    """
    合并菜单中所有菜的必备原料，按分区归类，同类项合并。
    返回 {zones: [{zone, items: [{name, used_by: [菜名], amount, optional}]}]}
    """
    # 食材名 -> 聚合信息
    agg = OrderedDict()
    for r in menu:
        for ing in r.get("ingredients", []):
            name = ing["name"].strip()
            if not name:
                continue
            key = name
            if key not in agg:
                agg[key] = {"name": name, "used_by": [], "amount": "", "optional": ing.get("optional", False)}
            if r["name"] not in agg[key]["used_by"]:
                agg[key]["used_by"].append(r["name"])
            # 从计算项里补用量
            for c in r.get("calculations", []):
                if c["name"].strip() == name and c.get("amount"):
                    if not agg[key]["amount"]:
                        agg[key]["amount"] = c["amount"]
                    break

    zones = OrderedDict()
    for item in agg.values():
        zone = classify(item["name"])
        zones.setdefault(zone, []).append(item)

    result = []
    for zone, items in zones.items():
        result.append({"zone": zone, "items": items})

    # 总量估算（粗）：卡路里总和 × 人数系数
    total_kcal = sum(r.get("calories_kcal") or 0 for r in menu)
    est_cost = round(total_kcal * 0.03 * max(1, people), 1)
    return {"zones": result, "total_kcal": total_kcal, "est_cost_yuan": est_cost, "people": people}
