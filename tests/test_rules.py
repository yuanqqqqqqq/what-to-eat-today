# -*- coding: utf-8 -*-
"""规则表：食材名清洗、忌口词表缺口、设备识别、家常化过滤。"""
import pytest

from app.core.rules import (
    ALLERGY_RULES, TABOO_RULES, ingredient_hit,
    ingredient_variants, is_homely, is_substantive_ingredient, recipe_needs_devices,
    split_ingredient_names, strip_quantity, substantive_ingredients,
)


# ---------- 食材名清洗 ----------
@pytest.mark.parametrize("raw,expected", [
    ("西兰花 1 个", "西兰花"),
    ("猪肉 300g", "猪肉"),
    ("125ml 淡奶油", "淡奶油"),
    ("高筋面粉：400g", "高筋面粉"),
    ("辣椒：青椒或者红椒都可以", "辣椒"),
    ("花椒：可选", "花椒"),
    ("新鲜菜心", "新鲜菜心"),      # 前缀形容词不动，"新鲜菜心"由 lookup 负责兜底
    ("", ""),
])
def test_strip_quantity(raw, expected):
    assert strip_quantity(raw) == expected


@pytest.mark.parametrize("raw,expected", [
    ("主料：五花肉", "五花肉"),
    ("必备：盐", "盐"),
    ("辅料：油、冰糖", "油、冰糖"),
    ("原料：五花肉 300g", "五花肉"),
])
def test_strip_quantity_removes_label_prefixes(raw, expected):
    """"主料/辅料/必备"这类分类标签要剥掉——标签后面才是食材。"""
    assert strip_quantity(raw) == expected


def test_bare_section_labels_are_not_ingredients():
    """源数据里被解析成食材的小节标题（HowToCook 的"小料"段落名）不是食材。"""
    for label in ("小料", "原料", "辅料", "配料"):
        assert is_substantive_ingredient(label) is False
        assert label not in substantive_ingredients([label, "土豆"])


@pytest.mark.parametrize("raw,expected", [
    ("葱、姜", ["葱", "姜"]),
    ("料酒、盐、冰糖、植物油", ["料酒", "盐", "冰糖", "植物油"]),
    ("西兰花 1 个", ["西兰花"]),
    ("黑鳕鱼，带皮", ["黑鳕鱼，带皮"]),   # 逗号是修饰语，不拆
])
def test_split_ingredient_names(raw, expected):
    assert split_ingredient_names(raw) == expected


def test_ingredient_variants_include_split_parts():
    v = ingredient_variants("生抽、蚝油、盐")
    assert "生抽" in v and "蚝油" in v and "盐" in v


# ---------- 调料过滤 ----------
@pytest.mark.parametrize("name", ["生抽", "蚝油", "盐", "白糖", "食用油", "葱", "蒜", "香菜"])
def test_seasonings_are_not_substantive(name):
    assert is_substantive_ingredient(name) is False


@pytest.mark.parametrize("name", ["土豆", "五花肉", "西兰花", "豆腐", "鸡蛋", "粉丝"])
def test_main_ingredients_are_substantive(name):
    assert is_substantive_ingredient(name) is True


def test_substantive_ingredients_dedupes_and_filters():
    out = substantive_ingredients(["土豆", "盐", "土豆", "五花肉", ""])
    assert out == ["土豆", "五花肉"]


# ---------- 忌口词表：针对真实菜谱的缺口审计 ----------
def test_taboo_coverage_against_real_recipes(recipes):
    """关键词如果出现在菜里，就必须真的能被该忌口过滤掉。

    这份清单是"漏放"的高风险项——过敏/忌口漏掉比误伤严重得多。
    """
    must_cover = {
        "猪肉": ["腊肠", "香肠", "咸肉", "猪油", "五花", "排骨", "里脊", "培根", "火腿"],
        "海鲜": ["虾", "蟹", "鱿鱼", "扇贝", "海参", "鲍鱼", "海带", "紫菜"],
        "牛肉": ["牛腩", "牛排", "肥牛"],
        "禽肉": ["鸡", "鸭", "鹅"],
        "奶制品": ["牛奶", "奶酪", "黄油", "奶油", "芝士", "酸奶"],
        "豆制品": ["豆腐", "腐竹", "豆干", "豆皮", "黄豆"],
        "菌菇": ["香菇", "金针菇", "木耳", "银耳"],
        "酒精": ["料酒", "啤酒", "黄酒", "米酒", "醪糟"],
    }
    corpus = " ".join(
        r.get("name", "") + " " + " ".join(i.get("name", "") for i in r.get("ingredients", []))
        for r in recipes
    )
    for taboo, words in must_cover.items():
        kws = TABOO_RULES[taboo]
        for w in words:
            if w not in corpus:
                continue
            assert any(w in k or k in w or w in k for k in kws), \
                f"忌口「{taboo}」缺少关键词「{w}」"


def test_allergy_gluten_covers_wheat_products():
    for w in ("面粉", "面条", "面包", "吐司", "面筋", "蛋糕", "饼干", "小麦"):
        assert any(k in w or w in k for k in ALLERGY_RULES["麸质"]), f"麸质过敏漏掉 {w}"


def test_ingredient_hit_checks_name_and_ingredients():
    r = {"name": "西红柿炒鸡蛋", "ingredients": [{"name": "西红柿"}, {"name": "鸡蛋"}]}
    assert ingredient_hit(r, ["鸡蛋"]) is True
    assert ingredient_hit(r, ["西红柿"]) is True
    assert ingredient_hit(r, ["牛肉"]) is False


def test_ingredient_hit_includes_calculations():
    r = {"name": "青菜", "ingredients": [], "calculations": [{"name": "猪油"}]}
    assert ingredient_hit(r, ["猪"]) is True


# ---------- 设备 ----------
def test_recipe_needs_devices_detects_oven():
    r = {"tools": ["烤箱", "烤盘"]}
    assert recipe_needs_devices(r) == {"烤箱"}


def test_recipe_needs_devices_multiple():
    r = {"tools": ["高压锅", "微波炉"]}
    assert recipe_needs_devices(r) == {"高压锅", "微波炉"}


def test_recipe_without_tools_needs_nothing():
    assert recipe_needs_devices({"tools": []}) == set()


def test_device_rules_are_substring_based():
    """工具名带修饰（"家用烤箱"）也要能识别。"""
    assert recipe_needs_devices({"tools": ["家用烤箱一台"]}) == {"烤箱"}


# ---------- 家常化 ----------
@pytest.mark.parametrize("text", ["鲍鱼捞饭", "龙虾汤", "松茸炖鸡", "黑松露意面"])
def test_premium_dishes_are_not_homely(text):
    assert is_homely({"name": text, "ingredients": []}) is False


@pytest.mark.parametrize("text", ["土豆丝", "西红柿炒鸡蛋", "青椒肉丝"])
def test_common_dishes_are_homely(text):
    assert is_homely({"name": text, "ingredients": []}) is True


def test_crayfish_is_homely_but_lobster_is_not():
    """小龙虾是家常夜宵，"龙虾"关键词不能误伤它。"""
    assert is_homely({"name": "麻辣小龙虾", "ingredients": []}) is True
    assert is_homely({"name": "芝士焗龙虾", "ingredients": []}) is False
