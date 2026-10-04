# -*- coding: utf-8 -*-
"""
采购清单生成：按「主菜 / 配菜 / 小料 / 调料」四类组织 + 合并同类项。
主菜/配菜显示采购量；小料/调料只显示做菜用量（不显示要买多少）。
"""
import re
from collections import OrderedDict

# 调料：只列名 + 做菜用量，不显示"要买多少"
CONDIMENT_KWS = (
    "盐", "糖", "油", "酱油", "生抽", "老抽", "蚝油", "醋", "料酒", "黄酒", "白酒", "米酒",
    "淀粉", "生粉", "味精", "鸡精", "豆瓣", "番茄酱", "沙拉", "芥末", "五香", "十三香",
    "孜然", "胡椒", "花椒", "八角", "桂皮", "香叶", "草果", "白芷", "芝麻", "蜂蜜",
    "豆豉", "甜面酱", "黄豆酱", "咖喱", "姜黄", "黄油", "奶油", "炼乳", "芝士", "奶酪",
    "香油", "麻油", "猪油", "菜籽油", "花生油", "橄榄油", "植物油", "鱼露", "啤酒", "雪碧", "可乐",
)

# 小料：新鲜炝锅料（葱姜蒜辣椒香菜洋葱），显示做菜用量
AROMATIC_KWS = (
    "葱", "姜", "蒜", "辣椒", "小米辣", "小米椒", "干辣椒", "青椒", "红椒", "尖椒",
    "泡椒", "剁椒", "野山椒", "香菜", "洋葱", "蒜苗",
)

# 主菜：肉 / 水产 / 蛋 / 豆制品 / 主食
MAIN_KWS = (
    "肉", "猪", "牛", "羊", "鸡", "鸭", "鹅", "鸽", "鱼", "虾", "蟹", "贝", "蛤", "鱿",
    "蛋", "豆腐", "豆干", "腐竹", "豆皮", "米", "面", "粉", "馒头", "饺子", "面包", "饼",
    "年糕", "火腿", "培根", "腊肉", "香肠", "排骨", "里脊", "五花", "蹄", "肘",
)

# 配菜：蔬菜 / 菌菇 / 根茎（兜底也归配菜）
SIDE_KWS = (
    "菜", "瓜", "茄", "萝卜", "土豆", "莲藕", "山药", "笋", "菇", "木耳", "海带", "紫菜",
    "玉米", "南瓜", "冬瓜", "黄瓜", "丝瓜", "苦瓜", "西兰花", "菠菜", "白菜", "生菜",
    "莴笋", "西红柿", "番茄", "金针菇", "杏鲍菇", "银耳", "苋菜", "空心菜", "娃娃菜",
    "花菜", "豆芽", "毛豆", "豌豆", "豆角", "芹菜", "韭菜",
)

# 含"油"但并非油类调料的食材，避免被"油"误判
NOT_OIL = ("油麦菜", "油豆腐", "油面筋", "油条")

# 纯水 / 误入的工具，不进采购清单
IGNORE_EXACT = {"水", "清水", "开水", "凉水", "热水", "温水", "冷水", "冰块", "冰水", "饮用水"}
IGNORE_KWS = ("工具", "擀面杖", "压汁器", "打蛋器", "刷子", "密封袋", "量杯", "厨房秤", "砧板",
              "手套", "厨房纸", "盘子", "盘夹", "夹子", "筷子", "牙签", "定时器", "保鲜膜", "锡纸",
              "油纸", "蒸笼", "杯子", "锅铲", "勺子", "铲子")


def _is_ignore(name):
    if name in IGNORE_EXACT:
        return True
    return any(k in name for k in IGNORE_KWS)


def classify(name: str) -> str:
    n = name.strip()
    # 精确排除：含"油"但并非油类调料
    if any(k in n for k in NOT_OIL):
        return "主菜" if any(k in n for k in ("豆腐", "面筋", "油条")) else "配菜"
    for kw in CONDIMENT_KWS:
        if kw in n:
            return "调料"
    for kw in AROMATIC_KWS:
        if kw in n:
            return "小料"
    for kw in MAIN_KWS:
        if kw in n:
            return "主菜"
    for kw in SIDE_KWS:
        if kw in n:
            return "配菜"
    return "配菜"


def scale_amount(amount, factor):
    """按份量系数缩放用量数字，并去掉"*份数"占位。"""
    if not amount:
        return amount
    amount = re.sub(r"\s*\*\s*份数", "", amount)
    if factor == 1:
        return amount

    def repl(m):
        v = float(m.group(1)) * factor
        return str(int(v)) if v == int(v) else f"{v:.1f}".rstrip("0").rstrip(".")

    return re.sub(r"(\d+(?:\.\d+)?)", repl, amount)


def _load_prices() -> dict:
    """加载用户食材价格表 -> {食材名: 单价}，用于成本估算。"""
    import json
    from ..paths import data_file
    p = data_file("prices.json")
    if not p.exists():
        return {}
    try:
        items = json.load(open(p, encoding="utf-8"))
    except Exception:
        return {}
    out = {}
    for it in items:
        name = str(it.get("name", "")).strip()
        price = it.get("price")
        if name and price not in (None, ""):
            try:
                out[name] = float(price)
            except (TypeError, ValueError):
                pass
    return out


def build_shopping_list(menu: list, people: int = 1) -> dict:
    """
    合并菜单中所有菜的原料，按「主菜/配菜/小料/调料」归类，同类项合并。
    用量按人数自动缩放（1 人 1 倍，每多 1 人 +0.5 倍，3 人约 2 倍）。
    返回 {zones: [{zone, items: [{name, used_by: [菜名], amount, optional}]}]}
    """
    factor = 1 + (max(1, people) - 1) * 0.5
    agg = OrderedDict()
    for r in menu:
        for ing in r.get("ingredients", []):
            name = ing["name"].strip()
            optional = ing.get("optional", False)
            # 剥离旧数据里的"主料：/必备：/可选："前缀
            for p in ("主料：", "必备：", "主料:", "必备:"):
                if name.startswith(p):
                    name = name[len(p):].strip()
                    break
            if name.startswith(("可选：", "可选:")):
                name = name[3:].strip()
                optional = True
            if not name or _is_ignore(name):
                continue
            key = name
            if key not in agg:
                agg[key] = {"name": name, "used_by": [], "amount": "", "optional": optional}
            else:
                # 任一菜必备，则整体必备
                agg[key]["optional"] = agg[key]["optional"] and optional
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
        item["amount"] = scale_amount(item["amount"], factor)
        # 调料/小料取不到用量时，给个"适量"默认（比空着好用）
        if not item["amount"] and zone in ("调料", "小料"):
            item["amount"] = "适量"
        zones.setdefault(zone, []).append(item)

    # 固定顺序：主菜 → 配菜 → 小料 → 调料
    order = ["主菜", "配菜", "小料", "调料"]
    result = []
    for zone in order:
        if zone in zones:
            result.append({"zone": zone, "items": zones[zone]})

    from .food_db import estimate_meal_cost
    total_kcal = sum(r.get("calories_kcal") or 0 for r in menu)
    est_cost = estimate_meal_cost(menu, people, _load_prices())
    return {"zones": result, "total_kcal": total_kcal, "est_cost_yuan": est_cost, "people": people}
