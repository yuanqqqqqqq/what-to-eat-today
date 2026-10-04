# -*- coding: utf-8 -*-
"""
食物数据库（路线图 v0.4 收尾）：
1) 查询中国食物成分表（第 6 版，data/food_composition.json）
2) 估算一道菜的热量（用主料密度 + 类型基准，替换早期 LLM 的离谱值）
3) 估算一道菜的成本（内置食材均价，替换"卡路里×0.03"占位）

成分表数据源：Sanotsu/china-food-composition-data（公共数据）。
糖类/可乐等成分表未收录的常见食材，用 MANUAL_SUPPLEMENT 补齐。
"""
import json
import re
from pathlib import Path

from .rules import substantive_ingredients

BASE_DIR = Path(__file__).resolve().parent.parent.parent
FOOD_FILE = BASE_DIR / "data" / "food_composition.json"

# 成分表未收录 / 口语名直接补营养（kcal, protein, fat, carb 每 100g）
MANUAL_SUPPLEMENT = {
    "白砂糖": (400, 0, 0, 99.9), "白糖": (400, 0, 0, 99.9), "绵白糖": (396, 0, 0, 98.9),
    "冰糖": (397, 0, 0, 99.3), "红糖": (389, 0.7, 0, 96.6), "糖": (400, 0, 0, 99.9),
    "蜂蜜": (321, 0.4, 1.9, 75.6), "糖浆": (300, 0, 0, 75),
    "可乐": (43, 0, 0, 10.6), "啤酒": (32, 0.4, 0, 2.8), "雪碧": (42, 0, 0, 10.5),
    "芝士": (328, 25.7, 23.5, 3.5), "芝士片": (328, 25.7, 23.5, 3.5),
    "淡奶油": (350, 2.5, 36, 4), "炼乳": (332, 8, 8.7, 55.4),
    "排骨": (278, 16.7, 23.1, 0), "肋排": (278, 16.7, 23.1, 0), "猪肋排": (278, 16.7, 23.1, 0),
    "鸭肉": (240, 15.5, 19.7, 0.2), "鸭": (240, 15.5, 19.7, 0.2),
    "羊排": (203, 19, 14.1, 0), "肉末": (395, 13.2, 37, 2.4), "猪肉末": (395, 13.2, 37, 2.4),
    "青椒": (22, 1.4, 0.3, 5.4), "红椒": (22, 1.3, 0.3, 5.4), "甜椒": (19, 1.0, 0.2, 4.5),
    "尖椒": (23, 1.4, 0.3, 5.4), "小米椒": (40, 1.9, 0.4, 8.8), "小米辣": (40, 1.9, 0.4, 8.8),
    "泡椒": (28, 1.0, 0.2, 5.5), "野山椒": (28, 1.0, 0.2, 5.5),
}

# 口语名 -> 成分表里的精确名
MANUAL_ALIAS = {
    "五花肉": "猪肉（奶面）［硬五花］",
    "带皮五花肉": "猪肉（奶面）［硬五花］",
    "西红柿": "番茄［西红柿］",
    "土豆": "马铃薯［土豆、洋芋］",
    "鸡蛋": "鸡蛋（代表值）",
    "新鲜鸡蛋": "鸡蛋（代表值）",
    "牛肉": "牛肉（代表值，fat9g）",
    "牛腩": "牛肉（腹部肉）［牛腩］",
    "牛柳": "牛肉（里脊肉）［牛柳］",
    "鸡肉": "鸡胸脯肉",
    "鸡胸肉": "鸡胸脯肉",
    "鸡胸": "鸡胸脯肉",
    "鸡": "母鸡（一年内）",
    "半只鸡": "母鸡（一年内）",
    "整鸡": "母鸡（一年内）",
    "土鸡": "鸡（土鸡，家养）",
    "鸡腿肉": "鸡腿",
    "冷饭": "米饭（蒸，代表值）",
    "隔夜饭": "米饭（蒸，代表值）",
    "午餐肉": "午餐肉（上海梅林牌）",
    "午餐肉罐头": "午餐肉（上海梅林牌）",
    "猪肉": "猪肉（代表值，fat30g）",
    "瘦肉": "猪肉（里脊）",
    "里脊": "猪肉（里脊）",
    "猪里脊": "猪肉（里脊）",
    "大米": "稻米［大米］",
    "米饭": "米饭（蒸，代表值）",
    "面粉": "小麦粉（标准粉）",
    "中筋面粉": "小麦粉（标准粉）",
    "低筋面粉": "小麦粉（标准粉）",
    "高筋面粉": "小麦粉（标准粉）",
    "鲜面条": "面条（富强粉，煮）",
    "面条": "面条（富强粉，煮）",
    "虾": "对虾",
    "虾仁": "对虾",
    "大虾": "对虾",
    "牛奶": "纯牛奶（代表值，全脂）",
    "全脂牛奶": "纯牛奶（代表值，全脂）",
    "酸奶": "酸奶",
    "原味酸奶": "酸奶",
    "豆腐": "豆腐（代表值）",
    "老豆腐": "豆腐（代表值）",
    "香菇": "香菇（鲜）［香蕈，冬菇］",
    "木耳": "木耳（水发）［黑木耳，云耳］",
    "玉米": "玉米粒（黄、干）",
    "玉米粒": "玉米粒（黄、干）",
    "香菜": "香菜（鲜）［芫荽］",
    "洋葱": "洋葱（鲜）［葱头］",
    "大蒜": "大蒜（白皮，鲜）［蒜头］",
    "蒜头": "大蒜（白皮，鲜）［蒜头］",
    "姜": "姜（鲜）［黄姜］",
    "生姜": "姜（鲜）［黄姜］",
    "黄油": "黄油",
    "糯米": "糯米［江米］",
    "花生": "花生仁（生）",
    "燕麦": "燕麦",
    "海带": "海带（鲜）［江白菜］",
    "紫菜": "紫菜（干）",
    "西兰花": "西兰花［绿菜花］",
    "花菜": "菜花（白色）［花椰菜］",
    "虾皮": "虾皮",
    "芝麻": "芝麻子（白）",
    "红薯": "甘薯（红心）［山芋、红薯］",
    "山药": "山药（鲜）［薯蓣，大薯］",
    "莲藕": "藕［莲藕］",
    "豆芽": "绿豆芽",
    "生菜": "生菜（叶用莴苣）",
    "白菜": "大白菜（代表值）",
    "菠菜": "菠菜（鲜）［赤根菜］",
    "黄瓜": "黄瓜（鲜）［胡瓜］",
    "冬瓜": "冬瓜",
    "南瓜": "南瓜（鲜）",
    "茄子": "茄子（代表值）",
    "芹菜": "芹菜（茎）［旱芹，药芹］",
    "韭菜": "韭菜",
    "莴笋": "莴笋（鲜）［莴苣］",
    "腐竹": "腐竹",
    "粉丝": "粉丝",
    "米粉": "米粉",
}


class FoodDB:
    def __init__(self):
        self.foods = {}
        self.aliases = {}
        self._load()

    def _load(self):
        if FOOD_FILE.exists():
            try:
                data = json.load(open(FOOD_FILE, encoding="utf-8"))
                for it in data:
                    name = it.get("name", "").strip()
                    if not name:
                        continue
                    self.foods[name] = it
                    # 从 ［...］ 提取别名
                    for alias in re.findall(r"［([^］]+)］", name):
                        for a in alias.split("、"):
                            a = a.strip()
                            if a and a not in self.aliases:
                                self.aliases[a] = name
                    # 从 （...） 提取说明词（如"代表值""鲜"等不做别名，避免误匹配）
            except Exception:
                pass
        # 手动补充 + 别名（优先于成分表）
        for k, v in MANUAL_SUPPLEMENT.items():
            self.aliases.setdefault(k, k)
        for k, v in MANUAL_ALIAS.items():
            self.aliases[k] = v

    def lookup(self, query: str) -> dict:
        """返回 {name, kcal, protein, fat, carb, fiber} 或 None。"""
        if not query:
            return None
        q = query.strip()
        # 1. 手动补充（含别名）
        if q in MANUAL_SUPPLEMENT:
            kcal, p, f, c = MANUAL_SUPPLEMENT[q]
            return {"name": q, "kcal": kcal, "protein": p, "fat": f, "carb": c, "fiber": None}
        # 2. 精确
        if q in self.foods:
            return self._norm(self.foods[q])
        # 3. 手动别名
        if q in MANUAL_ALIAS and MANUAL_ALIAS[q] in self.foods:
            return self._norm(self.foods[MANUAL_ALIAS[q]])
        # 4. 成分表别名
        if q in self.aliases and self.aliases[q] in self.foods:
            return self._norm(self.foods[self.aliases[q]])
        # 5. 前缀匹配（"茄子" -> "茄子（代表值）"）
        for name in self.foods:
            if name.startswith(q + "（") or name.startswith(q + "［"):
                return self._norm(self.foods[name])
        # 6. 子串（保守：q 是食物名的前缀词）
        cand = [n for n in self.foods if n.startswith(q) and len(n) <= len(q) + 6]
        if len(cand) == 1:
            return self._norm(self.foods[cand[0]])
        return None

    @staticmethod
    def _norm(it):
        def num(k):
            v = it.get(k)
            try:
                return float(v)
            except (TypeError, ValueError):
                return None
        return {
            "name": it.get("name", ""),
            "kcal": num("kcal"),
            "protein": num("protein"),
            "fat": num("fat"),
            "carb": num("carb"),
            "fiber": num("fiber"),
        }

    # ---------- 热量估算 ----------
    # 每盘菜主料估算用量（克，生/熟重），配合主料密度算出整盘热量
    _PORTION = {"荤": 300, "素": 300, "汤": 150, "主食": 400,
                "甜点": 250, "饮品": 400, "半成品": 300, "其他": 250}

    # 各类型的主料关键词：只在这些主料里取密度，避免炒饭取到火腿、饺子取到油
    _MAIN_HINTS = {
        "主食": ("饭", "大米", "面", "粉", "饼", "馒头", "饺子", "包", "团", "糕", "芋", "薯", "土豆", "粥", "卷"),
        "荤": ("肉", "排", "鸡", "鸭", "鹅", "鸽", "鱼", "虾", "蟹", "贝", "蛤", "鱿",
               "牛", "羊", "猪", "腊", "火腿", "培根", "蛋", "蹄", "肘", "里脊", "鲈", "鲤", "鳕"),
        "素": ("菜", "瓜", "茄", "豆", "萝卜", "菇", "耳", "笋", "藕", "芹", "韭", "菠",
               "白菜", "番茄", "西红柿", "豆腐", "土豆", "芋", "莴", "茭", "芦", "花菜", "西兰"),
        "甜点": ("糖", "奶", "蛋", "面", "粉", "油", "奶油", "芝士", "巧克力", "蜜", "糯米", "芋", "果"),
        "饮品": ("茶", "奶", "果", "汁", "柠", "咖", "梅", "汽"),
        "汤": ("肉", "鱼", "虾", "鸡", "鸭", "骨", "蛋", "菜", "瓜", "豆", "菇", "豆腐", "海带", "紫菜"),
    }

    @staticmethod
    def estimate_kcal(recipe: dict) -> int:
        """估算整盘菜热量（kcal）：主料密度 × 估算用量 + 烹饪油。"""
        d_type = recipe.get("dish_type") or "其他"
        portion = FoodDB._PORTION.get(d_type, 250)

        db = _get_db()
        names = [i.get("name", "") for i in recipe.get("ingredients", [])]
        subs = substantive_ingredients(names)
        hints = FoodDB._MAIN_HINTS.get(d_type, ())

        # 优先取命中主料关键词的食材密度，否则取全体最高
        densities = []
        for s in subs:
            it = db.lookup(s)
            if it and it.get("kcal"):
                densities.append((s, it["kcal"]))
        main = [k for s, k in densities if any(h in s for h in hints)]
        best = max(main) if main else (max((k for _, k in densities), default=0))

        if not best:
            best = {"荤": 180, "素": 30, "汤": 45, "主食": 130,
                    "甜点": 180, "饮品": 25, "半成品": 150, "其他": 60}.get(d_type, 60)

        kcal = best * portion / 100.0

        # 烹饪用油：炒/煎/炸/爆/烧/煸 类做法加一份油（约 80 大卡）
        steps_text = recipe.get("name", "") + " "
        for g in recipe.get("steps", []):
            for st in g.get("steps", []):
                steps_text += st.get("text", "") + " "
        if d_type in ("荤", "素", "主食") and any(k in steps_text for k in ("炒", "煎", "炸", "爆", "烧", "煸")):
            kcal += 80

        return max(60, min(2200, int(round(kcal))))

    # ---------- 价格估算 ----------
    @staticmethod
    def estimate_price(recipe: dict) -> float:
        """估算单道菜成本（元，供 1 人份一桌基准）。"""
        d_type = recipe.get("dish_type") or "其他"
        base = {"荤": 22, "素": 6, "汤": 9, "主食": 5,
                "甜点": 9, "饮品": 5, "半成品": 12, "其他": 8}.get(d_type, 8)
        text = recipe.get("name", "") + " " + " ".join(
            i.get("name", "") for i in recipe.get("ingredients", []))

        EXPENSIVE = ("牛肉", "牛腩", "牛排", "牛柳", "肥牛", "虾", "蟹", "海参",
                     "鲍", "扇贝", "生蚝", "三文鱼", "鳕鱼", "鳝", "鸽", "甲鱼", "羊肉",
                     "羊排", "鱼翅", "龙虾", "松茸", "蛤蜊", "海螺", "干贝")
        CHEAP = ("土豆", "白菜", "青菜", "豆腐", "豆芽", "黄瓜", "冬瓜", "西红柿",
                 "番茄", "萝卜", "豆角", "茄子", "南瓜", "鸡蛋", "蛋", "粉丝", "凉粉")

        adj = 0
        for kw in EXPENSIVE:
            if kw in text:
                adj = 12
                break
        else:
            for kw in CHEAP:
                if kw in text:
                    adj = -3
                    break
        return max(2.0, round(base + adj, 1))


_DB = None


def _get_db() -> FoodDB:
    global _DB
    if _DB is None:
        _DB = FoodDB()
    return _DB


def estimate_meal_cost(menu: list, people: int = 1) -> float:
    """一桌菜的总成本：Σ 单菜成本 × 人数系数（人数增加时菜量加大，成本边际递减）。"""
    factor = 1 + (max(1, people) - 1) * 0.35
    total = sum(FoodDB.estimate_price(r) for r in menu)
    return round(total * factor, 1)
