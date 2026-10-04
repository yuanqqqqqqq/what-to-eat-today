# -*- coding: utf-8 -*-
"""
下载中国食物成分表（第 6 版）数据并合并为单一 JSON。

数据源: Sanotsu/china-food-composition-data（中国食物成分表标准版第6版，
已整理为结构化 JSON）。合并输出 data/food_composition.json：
    [{"name": 食物名, "kcal": 每100g千卡, "protein": 蛋白质g, "fat": 脂肪g,
      "carb": 碳水g, "fiber": 膳食纤维g, ...}]

可重复运行（幂等）。数据存本地后完全离线可用。
"""
import json
import os
import sys

import httpx

REPO = "Sanotsu/china-food-composition-data"
DIR = "json_data_v3_20260825_qwen38max_kimi_k3_fixed"
API = f"https://api.github.com/repos/{REPO}/contents/{DIR}"
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "data", "food_composition.json")


def list_files():
    r = httpx.get(API, timeout=30, headers={"Accept": "application/vnd.github+json"})
    r.raise_for_status()
    return [it for it in r.json() if it.get("name", "").endswith(".json")]


def fetch(url):
    return httpx.get(url, timeout=30).json()


def normalize(item):
    """提取我们关心的营养字段，字段可能是字符串或缺失。"""
    def num(k):
        v = item.get(k)
        try:
            return float(v)
        except (TypeError, ValueError):
            return None
    return {
        "name": item.get("foodName", "").strip(),
        "code": item.get("foodCode", ""),
        "kcal": num("energyKCal"),
        "protein": num("protein"),
        "fat": num("fat"),
        "carb": num("CHO"),
        "fiber": num("dietaryFiber"),
    }


def main():
    files = list_files()
    print(f"发现 {len(files)} 个数据文件")
    foods = []
    seen = set()
    for f in files:
        try:
            data = fetch(f["download_url"])
            if not isinstance(data, list):
                continue
            for item in data:
                if not isinstance(item, dict):
                    continue
                n = normalize(item)
                if not n["name"] or n["name"] in seen:
                    continue
                seen.add(n["name"])
                foods.append(n)
        except Exception as e:
            print(f"  ⚠️ {f['name']} 失败: {str(e)[:80]}")
    foods.sort(key=lambda x: x["name"])
    json.dump(foods, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    have_kcal = sum(1 for x in foods if x["kcal"] is not None)
    print(f"✅ 合并 {len(foods)} 种食物（其中 {have_kcal} 种有热量）→ {OUT}")


if __name__ == "__main__":
    main()
