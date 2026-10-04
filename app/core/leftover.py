# -*- coding: utf-8 -*-
"""
一菜两吃：剩菜二次加工推荐。

输入一道（可能剩了的）菜名，输出若干"换个花样再吃一顿"的方案：
复用其"实质主料"（肉类/蔬菜等，过滤掉调料与葱姜蒜）+ 在菜谱库中找
可做的二次加工菜，并给出加工提示。
"""
import random

from .rules import substantive_ingredients

# 类别 -> 二次加工方向（关键词命中菜名，仅作次级信号）+ 通用加工提示
REUSE_HINTS = {
    "肉菜": {"keywords": ["回锅", "炒饭", "卤", "豆腐", "焖饭", "馅饼", "煲", "蒸"], "tip": "剩肉切片/切丁，回锅加蔬菜快炒，或做成盖浇、配豆腐红烧"},
    "水产": {"keywords": ["豆腐", "蒸蛋", "煲", "炖"], "tip": "剩鱼虾拆肉，煮粥、配豆腐或蒸蛋"},
    "素菜": {"keywords": ["炒饭", "拌面", "蛋饼", "凉拌", "馅饼", "粉丝"], "tip": "剩菜切碎，摊蛋饼、炒饭或拌面"},
    "汤": {"keywords": ["粥", "拌面", "面", "粉丝"], "tip": "剩汤做汤底，煮面、煮粥或煮粉丝"},
    "主食": {"keywords": ["炒饭", "拌饭", "烙饼", "炒粉"], "tip": "剩饭做炒饭/拌饭，剩饼可回锅烙脆"},
    "早餐": {"keywords": ["饼", "粥", "炒饭", "蛋饼"], "tip": "剩主食改做煎饼或煮粥"},
    "甜点": {"keywords": ["粥", "饼"], "tip": "甜点剩料可煮粥或做饼"},
    "半成品": {"keywords": ["炒", "蒸", "卤", "炖"], "tip": "半成品二次加热，或搭配蔬菜炒制"},
    "调料": {"keywords": [], "tip": "调料可继续使用，无需二次加工"},
    "饮品": {"keywords": [], "tip": "饮品建议当顿喝完，或冷藏保存"},
}

# 调料 / 葱姜蒜等：不算"可复用主料"，过滤逻辑见 rules.substantive_ingredients


def find_recipe(engine, name: str):
    """按名称查找菜谱：先精确，再子串。"""
    if not name:
        return None
    name = name.strip()
    for r in engine.recipes:
        if r.get("name") == name:
            return r
    for r in engine.recipes:
        if name in r.get("name", ""):
            return r
    # 反过来：菜名包含用户输入的关键片段
    for r in engine.recipes:
        rn = r.get("name", "")
        if len(name) >= 2 and name in rn:
            return r
    return None


def _ingredients(recipe: dict) -> list:
    names = []
    for ing in recipe.get("ingredients", []):
        n = ing.get("name", "").strip()
        if n and n not in names:
            names.append(n)
    for c in recipe.get("calculations", []):
        n = c.get("name", "").strip()
        if n and n not in names:
            names.append(n)
    return names


def suggest_reuse(engine, recipe_name: str, n: int = 3, rng=None) -> dict:
    """返回 {"source": 原菜, "suggestions": [{recipe, how, reuse_ingredients}]}"""
    rng = rng or random.Random()
    src = find_recipe(engine, recipe_name)
    if src is None:
        return {"source": None, "suggestions": [], "error": f"没找到菜「{recipe_name}」，请换个菜名试试"}

    category = src.get("category_cn") or "肉菜"
    hints = REUSE_HINTS.get(category) or REUSE_HINTS.get(src.get("dish_type")) or {"keywords": [], "tip": "切碎回锅或配饭再加工"}
    src_sub = set(substantive_ingredients(_ingredients(src)))

    scored = []
    for r in engine.recipes:
        if r.get("id") == src.get("id"):
            continue
        rname = r.get("name", "")
        r_sub = set(substantive_ingredients(_ingredients(r)))
        overlap = src_sub & r_sub

        s = 0.0
        # 主信号：实质主料重叠（真正能"复用"的部分）
        if overlap:
            s += 6.0 * len(overlap)
        # 次级信号：菜名命中二次加工方向关键词（逐个累计）
        kw_hits = [k for k in hints["keywords"] if k in rname]
        if kw_hits:
            s += 2.0 * len(kw_hits)
        # 快手菜优先
        est = r.get("estimated_minutes")
        if est is not None:
            if est <= 15:
                s += 1.5
            elif est <= 30:
                s += 0.8

        if overlap or any(k in rname for k in hints["keywords"]):
            scored.append((s, r, sorted(overlap)))
    scored.sort(key=lambda x: x[0], reverse=True)

    out = []
    for s, r, overlap in scored[: max(1, n)]:
        reuse = "、".join(overlap)
        if reuse:
            how = f"剩的「{src.get('name')}」可复用：{reuse}。{hints['tip']}，即可做成「{r.get('name')}」"
        else:
            how = f"参考「{src.get('name')}」的口味方向：{hints['tip']}，做成「{r.get('name')}」"
        out.append({
            "recipe": r,
            "how": how,
            "reuse_ingredients": overlap,
            "score": round(s, 1),
        })
    return {"source": src, "suggestions": out}
