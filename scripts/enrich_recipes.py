# -*- coding: utf-8 -*-
"""
B 阶段：LLM 批量补全菜谱标签
给每道菜标注：spiciness(辣度) / taste(口味) / season(时令) / dish_type(荤素精修) / estimated_minutes(补缺)
输入: data/recipes.json + LLM 配置
输出: 原地更新 data/recipes.json（带断点续传，可重复运行）
"""
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.llm.client import LLMClient
from app.config import get_llm_config

BATCH_SIZE = 15
RETRIES = 3

PROMPT_TEMPLATE = """你是中餐菜谱数据标注员。对下面每道菜，输出 JSON 标注数组，字段与取值严格如下：
- spiciness: 从 ["不辣","微辣","辣"] 选一个（"青椒炒肉""农家一碗香"这类通常辣；"虎皮青椒""青椒酿"通常微辣或不辣）
- taste: 从 ["清淡","川辣","酸甜","咸鲜","重口"] 选 1-2 个
- season: 从 ["春","夏","秋","冬","四季"] 选一个（主要看主料是否当季）
- dish_type: 从 ["荤","素","汤","主食","甜点","饮品","半成品","其他"] 选一个（鸡蛋羹算"素"或"其他"，汤羹类算"汤"）
- estimated_minutes: 预估总耗时（整数分钟，含备菜+烹饪）

只输出 JSON 数组，不要任何解释、不要 markdown 代码块。格式示例：
[{"name":"西红柿炒鸡蛋","spiciness":"不辣","taste":["酸甜","清淡"],"season":"四季","dish_type":"素","estimated_minutes":15}]

菜谱列表：
{BATCH}
"""


def load_recipes():
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return json.load(open(os.path.join(base, "data", "recipes.json"), encoding="utf-8"))


def save_recipes(recipes):
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    json.dump(recipes, open(os.path.join(base, "data", "recipes.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)


def brief(recipe):
    return {
        "name": recipe["name"],
        "category": recipe.get("category_cn"),
        "ingredients": [i["name"] for i in recipe.get("ingredients", [])],
        "desc": (recipe.get("description") or "")[:50],
    }


def parse_json_array(text):
    """从 LLM 回复中稳健地提取 JSON 数组"""
    text = re.sub(r"```(?:json)?", "", text).strip()
    m = re.search(r"\[.*\]", text, re.DOTALL)
    if m:
        text = m.group(0)
    return json.loads(text)


def enrich_batch(client, batch):
    briefs = [brief(r) for r in batch]
    prompt = PROMPT_TEMPLATE.replace("{BATCH}", json.dumps(briefs, ensure_ascii=False))
    for attempt in range(RETRIES):
        try:
            reply = client.chat([{"role": "user", "content": prompt}], temperature=0.1, max_tokens=3000)
            data = parse_json_array(reply)
            # 校验是 list 且长度匹配
            if isinstance(data, list):
                return data
            raise ValueError("返回不是数组")
        except Exception as e:
            if attempt == RETRIES - 1:
                raise
            time.sleep(2 + attempt * 2)
    return []


def apply_result(recipes, result, by_name):
    """把 LLM 结果合并回 recipes"""
    applied = 0
    for item in result:
        name = item.get("name")
        r = by_name.get(name)
        if not r:
            continue
        sp = item.get("spiciness")
        if sp in ("不辣", "微辣", "辣"):
            r["spiciness"] = sp
        ta = item.get("taste")
        if isinstance(ta, list) and ta:
            r["taste"] = ta
        se = item.get("season")
        if se in ("春", "夏", "秋", "冬", "四季"):
            r["season"] = se
        dt = item.get("dish_type")
        if dt in ("荤", "素", "汤", "主食", "甜点", "饮品", "半成品", "其他"):
            r["dish_type"] = dt
        em = item.get("estimated_minutes")
        if isinstance(em, (int, float)) and em > 0:
            if r.get("estimated_minutes") is None:  # 只补缺失的
                r["estimated_minutes"] = int(em)
        applied += 1
    return applied


def main():
    cfg = get_llm_config()
    client = LLMClient(**cfg)
    if not client.available:
        print("❌ 未配置 LLM，请先填 Key")
        return

    recipes = load_recipes()
    by_name = {r["name"]: r for r in recipes}
    # 只处理缺 spiciness 的菜（幂等，可断点续传）
    todo = [r for r in recipes if "spiciness" not in r]
    total = len(todo)
    print(f"待补全: {total} 道（共 {len(recipes)} 道），每批 {BATCH_SIZE} 道")

    done = 0
    for i in range(0, total, BATCH_SIZE):
        batch = todo[i:i + BATCH_SIZE]
        try:
            result = enrich_batch(client, batch)
            n = apply_result(recipes, result, by_name)
            done += n
            save_recipes(recipes)  # 每批落盘，断点续传
            print(f"  批次 {i // BATCH_SIZE + 1}/{(total + BATCH_SIZE - 1) // BATCH_SIZE}: "
                  f"返回 {len(result)} 条，应用 {n} 条，累计 {done}/{total}")
        except Exception as e:
            print(f"  ⚠️ 批次 {i // BATCH_SIZE + 1} 失败: {str(e)[:120]}，跳过")
        time.sleep(0.5)

    save_recipes(recipes)
    # 统计
    have_sp = sum(1 for r in recipes if r.get("spiciness"))
    have_taste = sum(1 for r in recipes if r.get("taste"))
    have_season = sum(1 for r in recipes if r.get("season"))
    no_time = sum(1 for r in recipes if not r.get("estimated_minutes"))
    print(f"\n完成: 辣度 {have_sp}/372, 口味 {have_taste}/372, 时令 {have_season}/372, 仍缺耗时 {no_time}")


if __name__ == "__main__":
    main()
