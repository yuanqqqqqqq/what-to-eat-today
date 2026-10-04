# -*- coding: utf-8 -*-
"""
数据清洗：修错字、剥离"主料：/必备：/可选："前缀、删除工具类食材、修正耗时异常值。
运行：python scripts/clean_recipes.py
会先备份 data/recipes.json 为 recipes.json.bak。
"""
import json
import shutil
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
SRC = BASE / "data" / "recipes.json"

# 错字映射
TYPO_FIX = {"胡箩卜": "胡萝卜", "箩卜": "萝卜"}

# 工具关键词（命中即从食材里删除）
TOOL_KWS = ("密封袋", "量杯", "厨房秤", "砧板", "手套", "厨房纸", "蒸鱼盘", "盘夹", "夹子",
            "筷子", "牙签", "定时器", "保鲜膜", "锡纸", "油纸", "吸油纸", "蒸笼", "擀面杖",
            "打蛋器", "压汁器", "锅铲", "勺子", "铲子", "刷子", "杯子", "工具", "锅", "碗", "盘")


def clean_name(name: str) -> str:
    n = str(name).strip()
    for t, f in TYPO_FIX.items():
        n = n.replace(t, f)
    return n


def is_tool(name: str) -> bool:
    return any(k in name for k in TOOL_KWS)


def strip_prefix(name: str):
    """剥离"主料：/必备：/可选："前缀，返回 (名字, 是否可选)。"""
    n = str(name).strip()
    optional = False
    for p in ("主料：", "必备：", "主料:", "必备:"):
        if n.startswith(p):
            n = n[len(p):].strip()
            break
    if n.startswith(("可选：", "可选:")):
        n = n[3:].strip()
        optional = True
    return n, optional


def main():
    recipes = json.load(open(SRC, encoding="utf-8"))
    shutil.copy(SRC, SRC.with_suffix(".json.bak"))

    cleaned = 0
    removed_tool = 0
    fixed_min = 0

    for r in recipes:
        # 1. 修正耗时异常（隔夜/长时间发酵类，实际动手时间一般 1-3 小时）
        m = r.get("estimated_minutes")
        if m and m > 360:
            r["estimated_minutes"] = 180
            fixed_min += 1

        # 2. 清洗 ingredients
        new_ings = []
        for ing in r.get("ingredients", []):
            name = ing.get("name", "")
            name, optional = strip_prefix(name)
            name = clean_name(name)
            if not name or is_tool(name):
                removed_tool += 1
                continue
            if name != ing.get("name"):
                cleaned += 1
            ing["name"] = name
            ing["optional"] = optional
            new_ings.append(ing)
        r["ingredients"] = new_ings

        # 3. 清洗 calculations 的 name（剥前缀 + 修错字 + 删工具项）
        new_calcs = []
        for c in r.get("calculations", []):
            name = c.get("name", "")
            name, _ = strip_prefix(name)
            name = clean_name(name)
            if not name or is_tool(name):
                continue
            c["name"] = name
            new_calcs.append(c)
        r["calculations"] = new_calcs

    json.dump(recipes, open(SRC, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"清洗完成：共 {len(recipes)} 道菜")
    print(f"  修错字/前缀 {cleaned} 处，删工具类食材 {removed_tool} 个，修耗时异常 {fixed_min} 道")


if __name__ == "__main__":
    main()
