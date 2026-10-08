# -*- coding: utf-8 -*-
"""家庭味觉画像：写入/读取必须对称，脏名字必须清洗，且只影响软约束。"""
import json

import pytest

from app.core.profile import TasteProfile, default_profile, load_profile
from app.paths import data_file


@pytest.fixture
def dish():
    return {
        "id": "r9999", "name": "测试西兰花炒肉", "dish_type": "荤",
        "taste": ["咸鲜", "清淡"],
        "ingredients": [
            {"name": "西兰花 1 个"},          # 带数量
            {"name": "五花肉 300g"},          # 带数量
            {"name": "小料"},                 # 小节标题，不是食材
            {"name": "生抽"},                 # 调料
        ],
    }


def test_record_cleans_ingredient_names(clean_user_data, dish):
    TasteProfile().record(dish, 1)
    saved = json.load(open(data_file("profile.json"), encoding="utf-8"))
    keys = set(saved["ingredient_scores"])
    assert keys == {"西兰花", "五花肉"}, f"应当只剩清洗后的实质主料，实际 {keys}"
    assert "小料" not in keys and "生抽" not in keys
    assert not any("1 个" in k for k in keys)


def test_write_and_read_are_symmetric(clean_user_data, dish):
    """回归：写入用清洗后的名字、读取也必须用同一套清洗，否则画像永远拿不到分。"""
    p = TasteProfile()
    before = p.score_recipe(dish)
    p.record(dish, 1)
    after = TasteProfile().score_recipe(dish)
    assert after > before, "记录一次喜欢后，同一道菜的画像得分必须提高"
    assert after - before > 2.0, "菜品 + 口味 + 食材三项都应加分"


def test_dislike_lowers_score(clean_user_data, dish):
    p = TasteProfile()
    p.record(dish, -1)
    assert TasteProfile().score_recipe(dish) < 0


def test_taste_scores_accumulate(clean_user_data, dish):
    p = TasteProfile()
    p.record(dish, 1)
    p.record(dish, 1)
    saved = json.load(open(data_file("profile.json"), encoding="utf-8"))
    assert saved["dish_likes"]["r9999"] == 2
    assert saved["taste_scores"]["咸鲜"] == 2


def test_history_is_capped(clean_user_data, dish):
    p = TasteProfile()
    for _ in range(210):
        p.record(dish, 1)
    saved = json.load(open(data_file("profile.json"), encoding="utf-8"))
    assert len(saved["history"]) == 200
    assert saved["count"] == 210


def test_summary_shape(clean_user_data, dish):
    p = TasteProfile()
    p.record(dish, 1)
    s = p.summary()
    for key in ("count", "top_tastes", "top_ingredients", "avoid_ingredients", "top_dishes"):
        assert key in s
    assert s["count"] == 1
    assert any(x["name"] == "测试西兰花炒肉" for x in s["top_dishes"])
    assert any(x["name"] == "西兰花" for x in s["top_ingredients"])


def test_empty_profile_is_safe(clean_user_data):
    p = TasteProfile()
    s = p.summary()
    assert s["count"] == 0
    assert p.score_recipe({"id": "x", "ingredients": []}) == 0.0


def test_recipe_without_id_is_ignored(clean_user_data):
    """没有 id 的菜谱不能污染画像。"""
    p = TasteProfile()
    p.record({"name": "无 id 的菜", "ingredients": [{"name": "土豆"}]}, 1)
    assert p.summary()["count"] == 0


def test_profile_only_affects_scoring_not_constraints(engine, base_constraints, clean_user_data, recipes):
    """画像只进软约束打分：不能因为"讨厌牛肉"就突破忌口/过敏那套硬约束。"""
    dish_with_beef = next(r for r in recipes if any("牛肉" in i.get("name", "") for i in r["ingredients"])
                          and r.get("dish_type") == "荤")
    p = TasteProfile()
    for _ in range(3):
        p.record(dish_with_beef, -1)

    c = dict(base_constraints, profile=TasteProfile())
    pool_without_profile = set(id(r) for r in engine.hard_filter(dict(base_constraints)))
    pool_with_profile = set(id(r) for r in engine.hard_filter(c))
    assert pool_without_profile == pool_with_profile, "画像不该改变候选池"
    assert engine.score(dish_with_beef, c) < engine.score(dish_with_beef, base_constraints)


# ---------- 回归：空画像曾被污染 / 文件句柄曾不释放 ----------
def test_default_profile_returns_fresh_containers():
    """default_profile() 必须每次新建：共享容器会被 record() 原地改坏。"""
    a, b = default_profile(), default_profile()
    a["dish_likes"]["x"] = 1
    a["history"].append({"x": 1})
    assert b["dish_likes"] == {} and b["history"] == []


def test_record_does_not_pollute_module_default(clean_user_data, dish):
    """回归：load_profile 曾用浅拷贝，record 会把分数写进模块级默认值。"""
    TasteProfile().record(dish, 1)
    assert default_profile()["dish_likes"] == {}
    assert load_profile()["dish_likes"].get(dish["id"]) == 1


def test_removing_profile_file_clears_scores(clean_user_data, dish):
    """用户删掉 profile.json 后，内存里不能再残留旧分数。"""
    TasteProfile().record(dish, 1)
    assert TasteProfile().score_recipe(dish) > 0
    data_file("profile.json").unlink()
    assert TasteProfile().score_recipe(dish) == 0.0


def test_corrupt_profile_file_is_ignored(clean_user_data, dish):
    data_file("profile.json").write_text("{ not json", encoding="utf-8")
    p = TasteProfile()
    assert p.summary()["count"] == 0
    p.record(dish, 1)
    assert json.load(open(data_file("profile.json"), encoding="utf-8"))["count"] == 1


def test_wrong_type_fields_are_reset(clean_user_data):
    data_file("profile.json").write_text(
        json.dumps({"dish_likes": "oops", "count": 5}), encoding="utf-8")
    p = TasteProfile()
    assert p.data["dish_likes"] == {}
    assert p.data["history"] == []


def test_profile_file_handle_is_released(clean_user_data, dish):
    """Windows 上不关闭句柄会导致删不掉/覆盖不了用户数据文件。"""
    TasteProfile().record(dish, 1)
    assert TasteProfile().summary()["count"] == 1
    data_file("profile.json").unlink()   # 句柄没释放这里会 PermissionError
