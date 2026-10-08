# -*- coding: utf-8 -*-
"""约束引擎：硬约束不可违反、软约束只影响概率、组合校验、兜底行为。"""
import random

from app.core.rules import (
    ALLERGY_RULES, TABOO_RULES, ingredient_hit, recipe_needs_devices,
)


def _menu(engine, constraints, seed=0):
    return engine.recommend(constraints, rng=random.Random(seed))


# ---------- 硬约束：一律不能被违反 ----------
def test_hard_constraints_never_violated(engine, base_constraints):
    """跨多种约束组合跑多轮，过敏/忌口/设备/时间/难度/忌食一次都不能破。"""
    cases = [
        {"taboos": ["辣"]},
        {"taboos": ["海鲜", "猪肉"]},
        {"allergies": ["花生", "蛋"]},
        {"allergies": ["麸质"]},
        {"devices": ["蒸锅"]},
        {"devices": []},
        {"time_budget": 25},
        {"max_difficulty": 2},
        {"dislikes": ["香菜"]},
        {"scene_id": "sugar_control"},
        {"taboos": ["辣"], "allergies": ["海鲜"], "time_budget": 30, "max_difficulty": 3},
    ]
    checked = 0
    for case in cases:
        for seed in range(12):
            c = dict(base_constraints, **case)
            menu, info = _menu(engine, c, seed)
            assert info.get("pool_size", 0) >= 0
            for r in menu:
                checked += 1
                # 忌口（"辣"走辣度字段，见下）
                kws = []
                for t in c["taboos"]:
                    if t != "辣":
                        kws += TABOO_RULES.get(t, [])
                assert not ingredient_hit(r, kws), f"忌口被违反: {r['name']} {case}"
                # 过敏
                akws = [k for a in c["allergies"] for k in ALLERGY_RULES.get(a, [])]
                assert not ingredient_hit(r, akws), f"过敏被违反: {r['name']} {case}"
                # 忌口"辣"按辣度字段
                if "辣" in c["taboos"]:
                    assert r.get("spiciness") not in ("辣", "微辣"), f"辣忌口被违反: {r['name']}"
                # 忌食
                assert not ingredient_hit(r, c["dislikes"]), f"忌食被违反: {r['name']}"
                # 时间
                if c["time_budget"]:
                    assert (r.get("estimated_minutes") or 9999) <= c["time_budget"]
                # 难度
                if c["max_difficulty"]:
                    assert (r.get("difficulty") or 0) <= c["max_difficulty"]
                # 设备
                need = recipe_needs_devices(r)
                assert not need or need.issubset(set(c["devices"])), \
                    f"设备不足却推荐: {r['name']} 需要 {need}"
    assert checked > 300, "样本太少，测试没起到作用"


def test_allergy_pork_hotdog_excluded(engine):
    """回归：腊肠曾不在猪肉规则里，导致"荷兰豆炒腊肠"能通过猪肉忌口。"""
    assert ingredient_hit({"name": "荷兰豆炒腊肠", "ingredients": []}, TABOO_RULES["猪肉"])
    c = {"people": 3, "dishes": 2, "soups": 1, "taboos": ["猪肉"], "allergies": [],
         "taste_prefs": [], "devices": [], "pantry": [], "locked_ids": [],
         "dislikes": [], "favorite_ids": []}
    for seed in range(30):
        menu, _ = _menu(engine, c, seed)
        for r in menu:
            assert not ingredient_hit(r, TABOO_RULES["猪肉"])


# ---------- 软约束：只影响概率，不做过滤 ----------
def test_pantry_prefers_but_does_not_filter(engine, base_constraints):
    """常备食材只加概率：命中会变多，但不命中的菜依然可能出现。"""
    c = dict(base_constraints, pantry=["土豆"])
    hits = 0
    total = 0
    for seed in range(60):
        menu, _ = _menu(engine, c, seed)
        for r in menu:
            total += 1
            if any("土豆" in i.get("name", "") for i in r.get("ingredients", [])):
                hits += 1
    assert hits > 0, "常备食材完全没生效"
    assert hits < total, "常备食材变成了硬过滤"


def test_pantry_bonus_is_capped(engine, base_constraints):
    """食材复用加分有上限：否则常备食材一多，少数菜垄断推荐。"""
    c = dict(base_constraints, pantry=["鸡蛋", "土豆", "西红柿", "豆腐", "白菜",
                                       "葱", "姜", "蒜", "猪肉", "香菇"])
    pool = engine.hard_filter(c)
    scores = sorted((engine.score(r, c) for r in pool), reverse=True)
    # 上限 6.0 + 收藏 3.0 + 口味 + 场景，不应出现几十上百的分数
    assert scores[0] <= 20, f"最高分 {scores[0]}，软约束权重失控"


def test_min_weight_keeps_low_score_dishes_possible(engine, base_constraints):
    """低分菜概率低但不为零（"惊喜但不离谱"），不能退化成 max(score)。"""
    c = dict(base_constraints)
    pool = engine.hard_filter(c)
    soup_pool = [r for r in pool if r.get("dish_type") == "汤"]
    picked_ids = set()
    for seed in range(40):
        sample = engine.weighted_sample(soup_pool, 1, c, random.Random(seed))
        picked_ids.add(sample[0]["id"])
    assert len(picked_ids) >= 5, "加权随机的多样性不足，像是在取 top-N"


def test_favorite_does_not_monopolize(engine, base_constraints):
    """收藏只是加分，不能让收藏菜每次都出现。"""
    pool = engine.hard_filter(base_constraints)
    fav = [r["id"] for r in pool if r.get("dish_type") == "荤"][:3]
    c = dict(base_constraints, favorite_ids=fav, dishes=1, soups=0)
    seen = set()
    for seed in range(60):
        menu, _ = _menu(engine, c, seed)
        if menu:
            seen.add(menu[0]["id"])
    assert len(seen) > 5, "收藏菜垄断了推荐"


# ---------- 组合校验 ----------
def test_validate_combo_rejects_duplicates(engine, base_constraints, recipes):
    one = recipes[0]
    assert engine.validate_combo([one, one], base_constraints) is False


def test_validate_combo_requires_must_include(engine, base_constraints, recipes):
    c = dict(base_constraints, must_include=["不存在的菜名XYZ"])
    assert engine.validate_combo(recipes[:2], c) is False
    c2 = dict(base_constraints, must_include=[recipes[0]["name"]])
    assert engine.validate_combo([recipes[0], recipes[1]], c2) is True


def test_budget_rejects_over_cost(engine, recipes, base_constraints):
    """预算校验用的必须和展示成本是同一口径（同函数、同价格表）。"""
    combo = recipes[:3]
    cheap = dict(base_constraints, budget=1)      # 1 元绝对不够
    assert engine.validate_combo(combo, cheap) is False
    rich = dict(base_constraints, budget=100000)
    assert engine.validate_combo(combo, rich) is True


def test_budget_uses_user_price_table(engine, recipes, clean_user_data, base_constraints):
    """用户填了菜市场价，预算校验必须认这份价格（回归：曾经被忽略）。"""
    import json

    from app.paths import data_file
    # 挑一道含"猪肉"的菜
    dish = next(r for r in recipes if any("猪肉" in i.get("name", "") for i in r["ingredients"]))
    # 把猪肉标成天价，1 元预算的组合必然被否决
    json.dump([{"name": "猪肉", "price": 999.0, "unit": "元/斤"}],
              open(data_file("prices.json"), "w", encoding="utf-8"), ensure_ascii=False)

    c = dict(base_constraints, budget=50, people=1)
    assert engine.meal_cost([dish], c) > 50
    assert engine.validate_combo([dish], c) is False


# ---------- 边界与兜底 ----------
def test_zero_slots_returns_clear_error(engine, base_constraints):
    c = dict(base_constraints, dishes=0, soups=0)
    menu, info = engine.recommend(c, rng=random.Random(0))
    assert menu == []
    assert "至少" in info["error"]


def test_no_candidate_returns_error(engine, base_constraints):
    c = dict(base_constraints, time_budget=1)   # 没有 1 分钟能做完的菜
    menu, info = engine.recommend(c, rng=random.Random(0))
    assert menu == []
    assert info["error"]


def test_max_attempts_zero_does_not_crash(engine, base_constraints):
    """回归：以前用循环变量 `_` 统计次数，max_attempts=0 会 UnboundLocalError。"""
    c = dict(base_constraints, dishes=1, soups=0)
    menu, info = engine.recommend(c, rng=random.Random(0), max_attempts=0)
    assert isinstance(menu, list)
    assert info["attempts_used"] >= 1


def test_tight_budget_fallback_is_reported(engine, base_constraints):
    """预算完全不可能满足时：给出最接近的组合，并如实标注 fallback。"""
    c = dict(base_constraints, people=9, dishes=4, soups=1, budget=5)
    menu, info = engine.recommend(c, rng=random.Random(1))
    assert menu, "应该给兜底方案而不是空菜单"
    assert info["fallback"] is True
    assert info.get("fallback_reason"), "兜底必须说明原因"


def test_balanced_combo_prefers_one_veg(engine, base_constraints):
    """多菜位时尽量配一道素菜（软偏好，通过有限次重摇实现）。"""
    c = dict(base_constraints)
    balanced = 0
    for seed in range(40):
        menu, info = _menu(engine, c, seed)
        if info.get("balanced"):
            balanced += 1
    assert balanced >= 36, f"荤素均衡命中率过低：{balanced}/40"


def test_diversity_reduces_shared_ingredients(engine, base_constraints):
    """同餐两道菜共享实质主料的比例应该很低。"""
    shared = 0
    for seed in range(60):
        menu, _ = _menu(engine, base_constraints, seed)
        subs = [engine._sub_ingredients(r) for r in menu]
        for i in range(len(subs)):
            for j in range(i + 1, len(subs)):
                if subs[i] & subs[j]:
                    shared += 1
                    break
    assert shared <= 12, f"同餐食材重复过多：{shared}/60"


def test_same_seed_is_reproducible(engine, base_constraints):
    a, _ = _menu(engine, base_constraints, 12345)
    b, _ = _menu(engine, base_constraints, 12345)
    assert [r["id"] for r in a] == [r["id"] for r in b]


def test_locked_dishes_always_kept(engine, base_constraints, recipes):
    locked = [r["id"] for r in recipes if r.get("dish_type") == "荤"][:1]
    c = dict(base_constraints, locked_ids=locked)
    for seed in range(15):
        menu, _ = _menu(engine, c, seed)
        assert locked[0] in [r["id"] for r in menu]
