# -*- coding: utf-8 -*-
"""
重算 372 道菜的热量：用食物成分表（主料密度模型）替换早期 LLM 估算的离谱值。

输入: data/recipes.json
输出: 原地更新 calories_kcal（并打印前后对比统计）
可重复运行（幂等）。

注意：写回格式（indent=2）必须与 clean_recipes.py / parse_recipes.py 保持一致，
否则每次重算都会把整个 1.6MB 数据文件重排一遍，diff 无法审阅。
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.food_db import FoodDB

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RECIPES = os.path.join(BASE, "data", "recipes.json")
JSON_INDENT = 2


def main():
    recipes = json.load(open(RECIPES, encoding="utf-8"))
    FoodDB()  # 预热成分表

    old_vals = [r.get("calories_kcal") for r in recipes]
    changed = 0
    for r in recipes:
        new = FoodDB.estimate_kcal(r)
        if r.get("calories_kcal") != new:
            changed += 1
        r["calories_kcal"] = new

    json.dump(recipes, open(RECIPES, "w", encoding="utf-8"),
              ensure_ascii=False, indent=JSON_INDENT)

    new_vals = [r["calories_kcal"] for r in recipes]
    print(f"重算完成：{len(recipes)} 道，其中 {changed} 道热量有变化")
    print(f"旧值范围: {min(old_vals)} ~ {max(old_vals)}，>800 大卡 {sum(1 for v in old_vals if v and v > 800)} 道")
    print(f"新值范围: {min(new_vals)} ~ {max(new_vals)}，>800 大卡 {sum(1 for v in new_vals if v > 800)} 道")
    print(f"新值均值: {sum(new_vals) / len(new_vals):.0f} 大卡")

    # 抽样展示
    print("\n抽样（前 10 道）：")
    for r in recipes[:10]:
        print(f"  {r['name']} ({r.get('dish_type')}): {r['calories_kcal']} 大卡")


if __name__ == "__main__":
    main()
