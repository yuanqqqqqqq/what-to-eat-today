# -*- coding: utf-8 -*-
"""营养分析：不编造、口径明确、有免责声明、达标评估不空转。"""
import pytest

from app.core.food_db import FoodDB
from app.core.nutrition import DISCLAIMER, analyze, assess


@pytest.fixture
def menu(recipes):
    names = ["西红柿炒鸡蛋", "白灼菜心", "山药南瓜炖鸡汤"]
    picked = [next((r for r in recipes if r["name"] == n), None) for n in names]
    return [r for r in picked if r]


def test_analyze_returns_estimates_and_disclaimer(menu):
    n = analyze(menu, people=3, goal="均衡")
    assert n["disclaimer"] == DISCLAIMER
    assert n["estimated"] is True
    assert "估算" in n["disclaimer"]
    assert "医疗" in n["disclaimer"], "必须说明不是医疗/营养诊断"


def test_kcal_uses_recipe_data_unchanged(menu):
    """热量口径 = 菜谱库数据，不能被这次改动悄悄改掉。"""
    n = analyze(menu, people=3)
    assert n["total_kcal"] == sum(r.get("calories_kcal") or 0 for r in menu)
    assert n["per_person_kcal"] == round(n["total_kcal"] / 3)


def test_macros_are_grams_not_fabricated_ratios(recipes):
    """蛋白质/脂肪/碳水必须是成分表算出来的克数，不是固定百分比。"""
    dish = next(r for r in recipes if r["name"] == "蒜蓉西兰花")
    n = analyze([dish], people=1)
    assert n["macro_counted"] == 1
    # 旧实现用 total*0.20/0.30/0.50 硬套出克数，这里必须与那个逻辑不同
    assert n["protein_g"] != round(n["total_kcal"] * 0.20 / 4, 1)
    assert n["protein_g"] > 0 and n["fat_g"] > 0


def test_unreliable_macros_are_none_not_zero(recipes):
    """交叉校验失败的菜：营养素给 None（未知），不能给 0（看起来像"没有"）。"""
    dish = next(r for r in recipes if r["name"] == "西红柿炒鸡蛋")
    n = analyze([dish], people=1)
    assert n["macro_counted"] == 0, "该菜的营养素与整菜热量差得太多，应被剔除"
    assert n["protein_g"] is None
    assert n["fat_g"] is None
    assert n["per_person_macros"]["protein_g"] is None
    assert "未计入" in n["macro_note"] or "没有匹配" in n["macro_note"]
    assert n["total_kcal"] > 0, "热量始终来自菜谱库，不受影响"


def test_macro_energy_share_sums_to_100(menu):
    n = analyze(menu, people=2)
    if n["protein_pct"] is None:
        pytest.skip("该菜单营养素未通过交叉校验，跳过")
    assert abs(n["protein_pct"] + n["fat_pct"] + n["carb_pct"] - 100) <= 2


def test_low_coverage_is_reported_not_faked():
    """成分表完全查不到数据时：不给编造的数字，如实标注未计入。"""
    fake = {"id": "x1", "name": "不存在的菜", "dish_type": "素", "calories_kcal": 200,
            "ingredients": [{"name": "不存在食材A"}, {"name": "不存在食材B"}], "steps": []}
    n = analyze([fake], people=1)
    assert n["macro_counted"] == 0
    assert n["macro_coverage"] == 0.0
    assert n["macro_skipped"] == ["不存在的菜"]
    assert n["protein_g"] is None, "查不到数据时应是「未知」，不是 0"
    assert n["protein_pct"] is None, "没有可信数据时不该给供能比"


def test_coverage_reported_for_normal_menu(menu):
    n = analyze(menu, people=1)
    assert 0.0 <= n["macro_coverage"] <= 1.0
    assert n["macro_total"] == len(menu)
    assert n["macro_counted"] + len(n["macro_skipped"]) == len(menu)


def test_meat_veg_ratio_no_zero_division():
    veg_only = [{"id": "v", "name": "炒青菜", "dish_type": "素", "calories_kcal": 120,
                 "ingredients": [], "steps": []}]
    meat_only = [{"id": "m", "name": "红烧肉", "dish_type": "荤", "calories_kcal": 700,
                  "ingredients": [], "steps": []}]
    # 没有素菜 → 比值无意义（None），不能除零崩掉
    assert analyze(meat_only, people=1)["meat_veg_ratio"] is None
    # 没有荤菜 → 比值为 0（明确"没有荤"），不是 None
    assert analyze(veg_only, people=1)["meat_veg_ratio"] == 0.0


def test_people_count_scales_per_person(menu):
    one = analyze(menu, people=1)["per_person_kcal"]
    four = analyze(menu, people=4)["per_person_kcal"]
    assert one > four


def test_zero_people_does_not_crash(menu):
    assert analyze(menu, people=0)["per_person_kcal"] > 0


def test_empty_menu_is_safe():
    n = analyze([], people=2)
    assert n["total_kcal"] == 0
    assert n["macro_coverage"] == 0.0


# ---------- 达标评估（LangGraph 营养师节点用） ----------
def test_assess_empty_menu_reports_issue():
    assert assess([], analyze([], people=1)) == ["菜单为空"]


def test_assess_single_dish_does_not_demand_balance():
    """只有 1 道菜时不该要求"荤素齐全"，否则会无意义地反复回退。"""
    menu = [{"id": "a", "name": "红烧肉", "dish_type": "荤", "calories_kcal": 800,
             "ingredients": [], "steps": []}]
    issues = assess(menu, analyze(menu, people=1), goal="均衡")
    assert "缺蔬菜" not in issues


def test_assess_flags_missing_veg_for_multi_dish(recipes):
    meats = [r for r in recipes if r.get("dish_type") == "荤" and r["name"] != "白灼菜心"][:2]
    issues = assess(meats, analyze(meats, people=2), goal="均衡")
    assert "缺蔬菜" in issues


def test_assess_flags_high_calorie_for_diet(recipes):
    heavy = sorted(recipes, key=lambda r: r.get("calories_kcal") or 0, reverse=True)[:3]
    issues = assess(heavy, analyze(heavy, people=1), goal="减脂")
    assert "热量偏高" in issues


def test_assess_vegetarian_menu_flags_protein(menu):
    """没有荤菜的整桌：均衡目标下要提示缺优质蛋白（会触发 LangGraph 回退重选）。"""
    issues = assess(menu, analyze(menu, people=3), goal="均衡")
    assert issues == ["缺优质蛋白"]


def test_assess_balanced_menu_passes(recipes, menu):
    """有荤有素的一桌应当达标，不该引发无意义的回退。"""
    meat = next(r for r in recipes if r["name"] == "青椒土豆炒肉")
    full = menu + [meat]
    assert assess(full, analyze(full, people=3), goal="均衡") == []


# ---------- 成分表查询 ----------
def test_lookup_handles_messy_names():
    from app.core.food_db import _get_db
    db = _get_db()
    for raw in ("西兰花 1 个", "125ml 淡奶油", "鸡蛋 2 个"):
        assert db.lookup(raw) is not None, f"{raw} 查不到"


def test_lookup_does_not_fuzzy_match_single_chars():
    """单字查询曾经被模糊匹配到"盐水鸭"，必须直接返回 None。"""
    from app.core.food_db import _get_db
    db = _get_db()
    assert db.lookup("盐") is None
    assert db.lookup("油") is None


def test_estimate_kcal_within_sane_range(recipes):
    kcal = [FoodDB.estimate_kcal(r) for r in recipes]
    assert min(kcal) >= 40
    assert max(kcal) <= 2200
    assert len([k for k in kcal if k > 1500]) < len(kcal) * 0.05


def test_estimate_macros_consistent_with_kcal(recipes):
    """多数菜的营养素换算能量应与整菜热量同量级（口径自洽）。"""
    ok = 0
    total = 0
    for r in recipes[:120]:
        m = FoodDB.estimate_macros(r)
        e = m["protein_g"] * 4 + m["fat_g"] * 9 + m["carb_g"] * 4
        k = r.get("calories_kcal") or 0
        if not k or not e:
            continue
        total += 1
        if 0.5 <= e / k <= 2.0:
            ok += 1
    assert total > 80
    assert ok / total >= 0.7, f"营养素与热量口径自洽率过低：{ok}/{total}"
