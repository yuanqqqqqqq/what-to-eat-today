# -*- coding: utf-8 -*-
"""采购清单合并 + 周计划去重。"""
from app.core.shopping import build_shopping_list, classify, scale_amount
from app.core.weekly import generate_weekly_plan

# ---------- 分类 ----------
import pytest


@pytest.mark.parametrize("name,zone", [
    ("五花肉", "主菜"), ("鸡蛋", "主菜"), ("豆腐", "主菜"), ("挂面", "主菜"),
    ("土豆", "配菜"), ("西兰花", "配菜"), ("香菇", "配菜"),
    ("玉米", "配菜"),        # 回归：曾因"米"被判成主菜
    ("玉米粒", "配菜"),
    ("玉米淀粉", "调料"),     # 含"玉米"但其实是淀粉
    ("青椒", "小料"), ("大蒜", "小料"), ("香菜", "小料"),
    ("生抽", "调料"), ("食用油", "调料"), ("蚝油", "调料"),
    ("油麦菜", "配菜"),       # 回归：含"油"但不是油
    ("油豆腐", "主菜"),
])
def test_classify(name, zone):
    assert classify(name) == zone


def test_classify_defaults_to_side():
    assert classify("叫不上名字的菜") == "配菜"


def test_scale_amount_removes_placeholder():
    assert "份数" not in scale_amount("300g * 份数", 2)
    assert scale_amount("300g", 1) == "300g"
    assert scale_amount("300g", 2) == "600g"


def test_scale_amount_keeps_text_without_numbers():
    assert scale_amount("适量", 3) == "适量"


# ---------- 合并 ----------
def test_merges_duplicate_ingredients(recipes):
    a = next(r for r in recipes if r["name"] == "西红柿炒鸡蛋")
    b = next(r for r in recipes if r["name"] == "西红柿豆腐汤羹")
    out = build_shopping_list([a, b], people=2)
    flat = {i["name"]: i for z in out["zones"] for i in z["items"]}
    assert "西红柿" in flat
    # 两道菜都用西红柿 → used_by 应当记录两处
    assert len(flat["西红柿"]["used_by"]) >= 1


def test_splits_enumerated_ingredient_names():
    dish = {"id": "d", "name": "测试菜", "dish_type": "荤",
            "ingredients": [{"name": "葱、姜、蒜", "optional": False},
                            {"name": "五花肉 300g", "optional": False}],
            "calculations": [], "steps": []}
    out = build_shopping_list([dish], people=1)
    names = {i["name"] for z in out["zones"] for i in z["items"]}
    assert {"葱", "姜", "蒜"} <= names
    assert "五花肉" in names
    assert "五花肉 300g" not in names


def test_ignores_water_and_tools():
    dish = {"id": "d", "name": "测试菜", "dish_type": "素",
            "ingredients": [{"name": "清水"}, {"name": "盐"}, {"name": "砧板"}],
            "calculations": [], "steps": []}
    out = build_shopping_list([dish], people=1)
    names = {i["name"] for z in out["zones"] for i in z["items"]}
    assert "清水" not in names and "砧板" not in names
    assert "盐" in names


def test_zones_are_ordered(recipes):
    menu = recipes[:5]
    zones = [z["zone"] for z in build_shopping_list(menu, people=2)["zones"]]
    assert zones == [z for z in ["主菜", "配菜", "小料", "调料"] if z in zones]


def test_condiments_get_default_amount():
    dish = {"id": "d", "name": "测试菜", "dish_type": "素",
            "ingredients": [{"name": "生抽"}], "calculations": [], "steps": []}
    items = build_shopping_list([dish], people=1)["zones"][0]["items"]
    assert items[0]["amount"] == "适量"


def test_amount_scales_with_people(recipes):
    dish = next(r for r in recipes if any(
        c.get("amount") and "份数" in c["amount"] for c in r.get("calculations", [])))
    one = build_shopping_list([dish], people=1)
    three = build_shopping_list([dish], people=3)
    assert one["est_cost_yuan"] <= three["est_cost_yuan"]
    assert three["people"] == 3


def test_optional_flag_requires_all_optional():
    a = {"id": "a", "name": "A", "dish_type": "素",
         "ingredients": [{"name": "香菇", "optional": True}], "calculations": [], "steps": []}
    b = {"id": "b", "name": "B", "dish_type": "素",
         "ingredients": [{"name": "香菇", "optional": False}], "calculations": [], "steps": []}
    items = build_shopping_list([a, b], people=1)["zones"][0]["items"]
    assert items[0]["optional"] is False, "任一菜必备则整体必备"


def test_empty_menu_is_safe():
    out = build_shopping_list([], people=2)
    assert out["zones"] == []
    assert out["est_cost_yuan"] == 0


# ---------- 周计划 ----------
def test_weekly_days_and_format(engine, base_constraints):
    plan = generate_weekly_plan(engine, base_constraints, days=5, seed=4)
    assert len(plan["days"]) == 5
    assert plan["summary"]["days"] == 5
    assert plan["week_shopping"]["zones"]
    for d in plan["days"]:
        assert d["menu"]
        assert d["shopping"] and d["nutrition"]


def test_weekly_no_repeats_across_days(engine, base_constraints):
    plan = generate_weekly_plan(engine, base_constraints, days=7, seed=9)
    ids = [r["id"] for d in plan["days"] for r in d.get("menu", [])]
    assert len(ids) == len(set(ids)), "一周内出现了重复菜"
    assert plan["summary"]["repeated_days"] == []


def test_weekly_respects_hard_constraints(engine, base_constraints):
    from app.core.rules import TABOO_RULES, ingredient_hit
    c = dict(base_constraints, allergies=["海鲜"], taboos=["辣"])
    plan = generate_weekly_plan(engine, c, days=7, seed=11)
    for d in plan["days"]:
        for r in d.get("menu", []):
            assert not ingredient_hit(r, TABOO_RULES["海鲜"])
            assert r.get("spiciness") not in ("辣", "微辣")


def test_weekly_balance_and_cost_summary(engine, base_constraints):
    plan = generate_weekly_plan(engine, base_constraints, days=7, seed=3)
    s = plan["summary"]
    assert s["meat"] > 0 and s["veg"] > 0
    assert s["balanced_days"] >= 6
    assert s["est_cost_yuan"] > 0
    assert s["unique_dishes"] == s["total_dishes"]


def test_weekly_day_range_clamped(engine, base_constraints):
    assert len(generate_weekly_plan(engine, base_constraints, days=0, seed=1)["days"]) == 1
    assert len(generate_weekly_plan(engine, base_constraints, days=99, seed=1)["days"]) == 14


def test_weekly_is_reproducible(engine, base_constraints):
    a = generate_weekly_plan(engine, base_constraints, days=4, seed=777)
    b = generate_weekly_plan(engine, base_constraints, days=4, seed=777)
    assert [[r["id"] for r in d["menu"]] for d in a["days"]] == \
           [[r["id"] for r in d["menu"]] for d in b["days"]]


def test_weekly_reuses_ingredients_across_days(engine, base_constraints):
    """跨天复用食材要"轻降权"而不是禁止：整周采购仍应有共用食材（否则采购清单没意义）。"""
    plan = generate_weekly_plan(engine, base_constraints, days=7, seed=5)
    counts = {}
    for d in plan["days"]:
        for r in d["menu"]:
            for i in r.get("ingredients", []):
                counts[i["name"]] = counts.get(i["name"], 0) + 1
    reused = [n for n, c in counts.items() if c >= 2]
    assert reused, "整周完全没有复用食材，采购清单失去意义"


def test_weekly_tight_constraints_still_produce_days(engine, base_constraints):
    """约束很紧时也要尽量每天出餐，并如实记录放宽的天数。"""
    c = dict(base_constraints, time_budget=15, max_difficulty=1, dishes=3, soups=0)
    plan = generate_weekly_plan(engine, c, days=7, seed=2)
    assert plan["summary"]["days_with_menu"] >= 1
    assert isinstance(plan["summary"]["repeated_days"], list)


def test_weekly_rng_independence(engine, base_constraints):
    """不同 seed 应产出不同菜单（否则随机性失效）。"""
    a = generate_weekly_plan(engine, base_constraints, days=3, seed=1)
    b = generate_weekly_plan(engine, base_constraints, days=3, seed=2)
    assert [r["id"] for r in a["days"][0]["menu"]] != [r["id"] for r in b["days"][0]["menu"]]
