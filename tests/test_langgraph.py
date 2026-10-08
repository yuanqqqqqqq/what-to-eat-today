# -*- coding: utf-8 -*-
"""LangGraph 编排：图结构、回退有上限、无候选不空转、无 LLM 也能跑通。"""
from app.agents.orchestrator import (
    MAX_ATTEMPTS, _GRAPH, orchestrate, route_after_nutrition, route_after_shopper,
)

BASE = {"people": 3, "dishes": 2, "soups": 1, "taboos": [], "allergies": [],
        "taste_prefs": [], "devices": [], "pantry": [], "locked_ids": [],
        "dislikes": [], "favorite_ids": []}


def test_max_attempts_is_bounded():
    """必须存在硬上限，避免"营养不达标 → 重新规划"无限循环。"""
    assert 1 <= MAX_ATTEMPTS <= 10


def test_graph_compiles_with_expected_nodes():
    nodes = set(_GRAPH.get_graph().nodes)
    assert {"planner", "nutritionist", "shopper", "writer"} <= nodes


def test_happy_path_runs_all_four_agents(clean_user_data):
    r = orchestrate(dict(BASE), seed=42)
    assert r["ok"] is True
    agents = [t["agent"] for t in r["agent_trace"]]
    assert agents == ["规划师", "营养师", "采购员", "搭配师"]
    assert r["replans"] == 0


def test_route_after_nutrition_paths():
    assert route_after_nutrition({"menu": [], "nutrition_issues": []}) == "end"
    assert route_after_nutrition({"menu": [{}], "nutrition_issues": ["缺蔬菜"], "attempt": 1}) == "planner"
    assert route_after_nutrition({"menu": [{}], "nutrition_issues": [], "attempt": 1}) == "shopper"
    # 超过上限就不再回退
    assert route_after_nutrition(
        {"menu": [{}], "nutrition_issues": ["缺蔬菜"], "attempt": MAX_ATTEMPTS}) == "shopper"


def test_route_after_shopper_skips_writer_without_menu():
    assert route_after_shopper({"menu": []}) == "end"
    assert route_after_shopper({"menu": [{}]}) == "writer"


def test_no_candidate_menu_does_not_replan_repeatedly(clean_user_data):
    r = orchestrate(dict(BASE, time_budget=1), seed=1)
    assert r["ok"] is False
    assert r["error"]
    planners = [t for t in r["agent_trace"] if t["agent"] == "规划师"]
    assert len(planners) == 1, "没有候选菜时不该反复重规划"


def test_replans_never_exceed_limit(clean_user_data):
    """逼营养师挑刺（减脂目标 + 高热量菜单），回退次数也必须封顶。"""
    r = orchestrate(dict(BASE, nutrition_goal="减脂", dishes=3, soups=0), seed=5)
    if r["ok"]:
        assert 0 <= r["replans"] <= MAX_ATTEMPTS


def test_orchestrate_returns_real_seed(clean_user_data):
    """回归：以前把入参 seed 原样回传，None 时不反映实际用的种子。"""
    r = orchestrate(dict(BASE), seed=None)
    assert isinstance(r["seed"], int)


def test_orchestrate_with_explicit_seed_is_reproducible(clean_user_data):
    a = orchestrate(dict(BASE), seed=2024)
    b = orchestrate(dict(BASE), seed=2024)
    assert [x["id"] for x in a["menu"]] == [x["id"] for x in b["menu"]]
    assert [t["note"] for t in a["agent_trace"]] == [t["note"] for t in b["agent_trace"]]


def test_works_without_llm(clean_user_data):
    r = orchestrate(dict(BASE), seed=7)
    assert r["llm_used"] is False
    assert r["pairing_note"]
    assert any("模板" in t["note"] for t in r["agent_trace"] if t["agent"] == "搭配师")


def test_respects_hard_constraints(clean_user_data):
    from app.core.rules import ALLERGY_RULES, TABOO_RULES, ingredient_hit
    r = orchestrate(dict(BASE, allergies=["海鲜"], taboos=["辣"], time_budget=40), seed=13)
    assert r["ok"] is True
    for dish in r["menu"]:
        assert not ingredient_hit(dish, ALLERGY_RULES["海鲜"])
        assert not ingredient_hit(dish, TABOO_RULES["海鲜"])
        assert dish.get("spiciness") not in ("辣", "微辣")
        assert (dish.get("estimated_minutes") or 0) <= 40


def test_nutrition_issues_are_injected_as_soft_hint(clean_user_data, monkeypatch):
    """营养师的改进方向必须真的传进规划师（软约束），而不是只写在 trace 里。"""
    import app.agents.orchestrator as orch

    # 让营养师稳定报"缺蔬菜"，从而必然触发回退
    monkeypatch.setattr(orch, "assess", lambda menu, nutrition, goal: ["缺蔬菜"])

    seen = []
    real_recommend = orch.get_engine().recommend

    def spy(constraints, **kwargs):
        seen.append(constraints.get("retry_hint", ""))
        return real_recommend(constraints, **kwargs)

    monkeypatch.setattr(orch.get_engine(), "recommend", spy)
    r = orch.orchestrate(dict(BASE), seed=3)

    assert len(seen) >= 2, "营养不达标却没有回退重规划"
    assert seen[0] == "", "第一轮不该带改进方向"
    assert seen[1] == "缺蔬菜", "第二轮必须带上营养师给的改进方向"
    assert r["replans"] == len(seen) - 1
    assert len(seen) <= MAX_ATTEMPTS, f"回退次数超过上限：{len(seen)}"

    # 引擎真的会响应这个提示（score 里对"蔬菜"有加权）
    hint_constraints = dict(BASE, retry_hint="缺蔬菜")
    veg = {"id": "v", "name": "炒青菜", "dish_type": "素", "ingredients": [], "steps": []}
    meat = {"id": "m", "name": "红烧肉", "dish_type": "荤", "ingredients": [], "steps": []}
    assert orch.get_engine().score(veg, hint_constraints) > orch.get_engine().score(meat, hint_constraints)


def test_orchestrate_response_has_frontend_fields(clean_user_data):
    r = orchestrate(dict(BASE), seed=8)
    assert set(r["reasons"]) == {d["id"] for d in r["menu"]}
    assert set(r["costs"]) == {d["id"] for d in r["menu"]}
    assert set(r["visuals"]) == {d["id"] for d in r["menu"]}
    assert r["reasons"], "至少要给出推荐理由"
    assert all(v in ("🍖", "🥬", "🍲", "🍚", "🍰", "🥤", "🥟", "🐟", "🍽️")
               for v in r["visuals"].values())


def test_reasons_explain_favorites_and_locks(clean_user_data, recipes):
    meat = next(r for r in recipes if r.get("dish_type") == "荤")
    r = orchestrate(dict(BASE, locked_ids=[meat["id"]], favorite_ids=[meat["id"]]), seed=1)
    reasons = r["reasons"].get(meat["id"], [])
    assert any("锁定" in x for x in reasons)
    assert any("收藏" in x for x in reasons)


def test_pantry_reason_mentions_ingredient(clean_user_data, recipes):
    dish = next(r for r in recipes if any("土豆" in i.get("name", "") for i in r["ingredients"]))
    r = orchestrate(dict(BASE, pantry=["土豆"], locked_ids=[dish["id"]], dishes=1, soups=0), seed=1)
    assert any("土豆" in x for x in r["reasons"].get(dish["id"], []))


def test_every_dish_always_has_a_reason(clean_user_data):
    """每道菜都必须有推荐理由——前端为它留了位置，空着就是 UI 事故。"""
    for seed in range(6):
        r = orchestrate(dict(BASE), seed=seed)
        for dish in r["menu"]:
            assert r["reasons"].get(dish["id"]), f"第 {seed} 轮「{dish['name']}」没有推荐理由"
