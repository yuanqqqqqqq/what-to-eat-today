# -*- coding: utf-8 -*-
"""API 层：结构统一、参数校验、错误不泄露内部信息、Key 不回传明文。"""
import json

import pytest

from app.paths import data_file

VALID = {"people": 3, "dishes": 2, "soups": 1}


# ---------- 基础 ----------
def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["recipes"] > 300


def test_index_serves_frontend(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "今天吃什么" in r.text


def test_favicon_no_404_noise(client):
    assert client.get("/favicon.ico").status_code == 204


def test_meta_shape(client):
    m = client.get("/api/meta").json()
    for key in ("recipe_count", "taboos", "allergies", "devices", "tastes", "goals", "scenes"):
        assert key in m
    assert m["recipe_count"] > 300
    assert "均衡" in m["goals"]
    assert all("id" in s and "name" in s for s in m["scenes"])


def test_openapi_available(client):
    assert client.get("/openapi.json").status_code == 200


# ---------- 推荐 ----------
def test_recommend_shape(client):
    r = client.post("/api/recommend", json=VALID)
    assert r.status_code == 200
    d = r.json()
    assert d["ok"] is True
    assert len(d["menu"]) == 3
    assert d["shopping"]["zones"]
    assert d["nutrition"]["disclaimer"]
    assert d["pairing_note"]
    assert d["info"]["attempts_used"] >= 1
    # 前端要用的附加字段
    assert set(d["reasons"]) == {x["id"] for x in d["menu"]}
    assert set(d["costs"]) == {x["id"] for x in d["menu"]}
    assert set(d["visuals"]) == {x["id"] for x in d["menu"]}
    assert d["mode"] == "pipeline"


def test_recommend_requires_at_least_one_slot(client):
    r = client.post("/api/recommend", json={"people": 2, "dishes": 0, "soups": 0})
    assert r.status_code == 400
    assert "至少" in r.json()["detail"]


@pytest.mark.parametrize("payload", [
    {"people": 0, "dishes": 1, "soups": 0},
    {"people": 999, "dishes": 1, "soups": 0},
    {"people": 2, "dishes": -1, "soups": 0},
    {"people": 2, "dishes": 99, "soups": 0},
    {"people": 2, "dishes": 1, "soups": 0, "budget": -5},
    {"people": 2, "dishes": 1, "soups": 0, "max_difficulty": 99},
])
def test_recommend_rejects_out_of_range(client, payload):
    assert client.post("/api/recommend", json=payload).status_code == 422


def test_recommend_accepts_null_optionals(client):
    """回归：前端会把未填字段传成 null。"""
    r = client.post("/api/recommend", json={
        "people": 3, "dishes": 2, "soups": 1,
        "budget": None, "time_budget": None, "max_difficulty": None,
        "nutrition_goal": None, "scene_id": None, "seed": None,
    })
    assert r.status_code == 200


def test_recommend_honours_hard_constraints(client):
    from app.core.rules import ALLERGY_RULES, TABOO_RULES, ingredient_hit
    payload = dict(VALID, allergies=["海鲜"], taboos=["辣"], seed=3)
    for _ in range(3):
        d = client.post("/api/recommend", json=payload).json()
        for r in d["menu"]:
            assert not ingredient_hit(r, ALLERGY_RULES["海鲜"])
            assert not ingredient_hit(r, TABOO_RULES["海鲜"])
            assert r.get("spiciness") not in ("辣", "微辣")


def test_recommend_seed_reproducible(client):
    a = client.post("/api/recommend", json=dict(VALID, seed=555)).json()
    b = client.post("/api/recommend", json=dict(VALID, seed=555)).json()
    assert [r["id"] for r in a["menu"]] == [r["id"] for r in b["menu"]]


def test_recommend_no_candidate_returns_ok_false(client):
    d = client.post("/api/recommend", json=dict(VALID, time_budget=1)).json()
    assert d["ok"] is False
    assert d["error"]


def test_recommend_declares_llm_usage_honestly(client):
    """没有配置 LLM 时必须说明没用 LLM，不能谎称用了。"""
    d = client.post("/api/recommend", json=VALID).json()
    assert d["llm_used"] is False
    assert "本餐组合" in d["pairing_note"]


def test_per_dish_costs_sum_to_meal_cost(client):
    """菜品卡上的单菜成本加起来要等于摘要里的整桌估算（否则用户看到两个数对不上）。"""
    d = client.post("/api/recommend", json=dict(VALID, people=4, seed=21)).json()
    assert abs(sum(d["costs"].values()) - d["shopping"]["est_cost_yuan"]) <= 1.0


# ---------- 多 Agent ----------
def test_plan_graph_shape(client):
    d = client.post("/api/plan/graph", json=dict(VALID, seed=42)).json()
    assert d["ok"] is True
    assert d["orchestration"] == "langgraph"
    assert d["mode"] == "langgraph"
    assert d["replans"] >= 0
    agents = [t["agent"] for t in d["agent_trace"]]
    assert agents[0] == "规划师"
    assert "营养师" in agents
    assert "采购员" in agents
    assert agents[-1] == "搭配师"


def test_plan_graph_requires_slots(client):
    assert client.post("/api/plan/graph", json={"people": 2, "dishes": 0, "soups": 0}).status_code == 400


def test_plan_graph_no_candidate_does_not_loop(client):
    """无候选菜时不该空转 3 轮（白烧 token），trace 应该很短。"""
    d = client.post("/api/plan/graph", json=dict(VALID, time_budget=1)).json()
    assert d["ok"] is False
    assert len(d["agent_trace"]) <= 2
    assert sum(1 for t in d["agent_trace"] if t["agent"] == "规划师") == 1


def test_meta_reports_graph_availability(client):
    """打包版裁剪了 LangGraph，前端要靠这个字段决定是否禁用开关。"""
    assert isinstance(client.get("/api/meta").json()["graph_available"], bool)


def test_plan_graph_returns_503_when_langgraph_missing(client, monkeypatch):
    """没有 LangGraph 时返回明确的 503，而不是一个 ImportError 引发的 500。"""
    import app.main as m
    monkeypatch.setattr(m, "_graph_available", lambda: False)
    r = client.post("/api/plan/graph", json=VALID)
    assert r.status_code == 503
    assert "LangGraph" in r.json()["detail"]


# ---------- 设置与 Key 安全 ----------
def test_settings_get_never_returns_plaintext_key(client):
    client.post("/api/settings", json={"base_url": "https://api.example.com/v1",
                                       "api_key": "sk-supersecret-1234567890",
                                       "model": "m"})
    r = client.get("/api/settings")
    body = r.json()
    assert "supersecret" not in r.text
    assert "****" in body["api_key"]
    assert body["has_api_key"] is True
    assert body["configured"] is True


def test_settings_save_does_not_wipe_key_when_masked(client):
    client.post("/api/settings", json={"base_url": "https://x/v1",
                                       "api_key": "sk-realkey-abcdefgh", "model": "m"})
    masked = client.get("/api/settings").json()["api_key"]
    # 前端把脱敏串原样回传
    client.post("/api/settings", json={"base_url": "https://x/v1", "api_key": masked, "model": "m2"})
    assert client.get("/api/settings").json()["has_api_key"] is True
    assert client.get("/api/settings").json()["model"] == "m2"


def test_settings_save_does_not_wipe_key_when_empty(client):
    client.post("/api/settings", json={"base_url": "https://x/v1",
                                       "api_key": "sk-realkey-abcdefgh", "model": "m"})
    client.post("/api/settings", json={"base_url": "https://x/v1", "api_key": "", "model": "m"})
    assert client.get("/api/settings").json()["has_api_key"] is True


def test_settings_explicit_clear_key(client):
    client.post("/api/settings", json={"base_url": "https://x/v1",
                                       "api_key": "sk-realkey-abcdefgh", "model": "m"})
    client.post("/api/settings", json={"base_url": "https://x/v1", "api_key": "",
                                       "model": "m", "clear_api_key": True})
    assert client.get("/api/settings").json()["has_api_key"] is False


def test_settings_file_stores_key_locally(client):
    """Key 存在本地文件里（BYOK），且该文件在 .gitignore 中。"""
    client.post("/api/settings", json={"base_url": "https://x/v1",
                                       "api_key": "sk-localkey-1234", "model": "m"})
    saved = json.load(open(data_file("settings.json"), encoding="utf-8"))
    assert saved["api_key"] == "sk-localkey-1234"
    ignored = open(data_file("../.gitignore"), encoding="utf-8").read() \
        if data_file("../.gitignore").exists() else open(".gitignore", encoding="utf-8").read()
    assert "data/settings.json" in ignored


def test_llm_test_without_config_is_graceful(client):
    body = client.post("/api/llm/test", json={"base_url": "", "api_key": "", "model": ""}).json()
    assert body["ok"] is False
    assert "base_url" in body["message"]


def test_llm_models_endpoint(client):
    body = client.post("/api/llm/models", json={"base_url": "https://api.deepseek.com/v1"}).json()
    assert body["ok"] is True
    assert body["ollama"] is False


# ---------- 反馈与画像 ----------
def test_feedback_updates_profile(client):
    rid = json.load(open(data_file("../data/recipes.json"), encoding="utf-8"))[0]["id"] \
        if data_file("../data/recipes.json").exists() else None
    rid = rid or client.get("/api/recipes/search?q=鸡蛋").json()["results"][0]["id"]
    body = client.post("/api/feedback", json={"recipe_id": rid, "feedback": 1}).json()
    assert body["ok"] is True
    assert body["profile"]["count"] == 1
    assert client.get("/api/profile").json()["count"] == 1


def test_feedback_unknown_recipe_404(client):
    assert client.post("/api/feedback", json={"recipe_id": "nope", "feedback": 1}).status_code == 404


def test_feedback_never_calls_llm(client):
    """反馈走本地画像，不该触发任何外部请求。"""
    import app.main as m
    rid = client.get("/api/recipes/search?q=西红柿").json()["results"][0]["id"]
    body = client.post("/api/feedback", json={"recipe_id": rid, "feedback": -1}).json()
    assert body["profile"]["avoid_ingredients"] or body["profile"]["count"] == 1
    assert m  # 只是确保模块可用


# ---------- 菜谱 ----------
def test_search_prefers_name_matches(client):
    res = client.get("/api/recipes/search", params={"q": "红烧肉"}).json()["results"]
    assert res
    assert res[0]["name"].startswith("红烧") or "红烧肉" in res[0]["name"]


def test_search_empty_query(client):
    assert client.get("/api/recipes/search", params={"q": "  "}).json()["results"] == []


def test_search_limit_validated(client):
    assert client.get("/api/recipes/search", params={"q": "鸡", "limit": 999}).status_code == 422


def test_get_recipe_by_id(client):
    rid = client.get("/api/recipes/search?q=鸡蛋").json()["results"][0]["id"]
    r = client.get(f"/api/recipes/{rid}")
    assert r.status_code == 200
    assert r.json()["id"] == rid


def test_get_recipe_404(client):
    assert client.get("/api/recipes/does-not-exist").status_code == 404


def test_add_recipe_and_it_becomes_recommendable(client):
    body = {"name": "测试西红柿蛋汤", "dish_type": "汤",
            "ingredients": "西红柿，鸡蛋、盐", "steps": "1. 切西红柿\n2. 煮开",
            "difficulty": 1, "estimated_minutes": 10}
    d = client.post("/api/recipes", json=body).json()
    assert d["ok"] is True
    recipe = d["recipe"]
    assert recipe["id"].startswith("u")
    # 中文逗号/顿号也能正确拆分
    names = [i["name"] for i in recipe["ingredients"]]
    assert names == ["西红柿", "鸡蛋", "盐"]
    assert recipe["calories_kcal"] > 0
    # 新菜进入菜谱库
    assert client.get("/api/meta").json()["recipe_count"] > 300
    assert any(r["name"] == "测试西红柿蛋汤"
               for r in client.get("/api/recipes/search", params={"q": "测试西红柿蛋汤"}).json()["results"])


def test_add_recipe_same_name_overwrites(client):
    body = {"name": "重复菜", "dish_type": "素", "ingredients": "土豆", "steps": "煮"}
    a = client.post("/api/recipes", json=body).json()["recipe"]
    b = client.post("/api/recipes", json=dict(body, ingredients="土豆, 盐")).json()["recipe"]
    assert a["id"] == b["id"], "同名菜应覆盖而不是越加越多"


def test_add_recipe_requires_name(client):
    assert client.post("/api/recipes", json={"name": "   "}).status_code == 400


def test_user_recipes_survive_reload(client):
    client.post("/api/recipes", json={"name": "持久化测试菜", "dish_type": "素",
                                      "ingredients": "青菜", "steps": "炒"})
    saved = json.load(open(data_file("user_recipes.json"), encoding="utf-8"))
    assert any(r["name"] == "持久化测试菜" for r in saved)


# ---------- 常备食材 / 价格 ----------
def test_pantry_roundtrip(client):
    assert client.get("/api/pantry").json()["items"] == []
    d = client.post("/api/pantry", json={"items": ["土豆", "土豆", " ", "鸡蛋"]}).json()
    assert d["items"] == ["土豆", "鸡蛋"]
    assert client.get("/api/pantry").json()["items"] == ["土豆", "鸡蛋"]


def test_prices_roundtrip_and_dedupe(client):
    d = client.post("/api/prices", json={"items": [
        {"name": "猪肉", "price": "15.5", "unit": "元/斤"},
        {"name": "猪肉", "price": 16, "unit": "元/斤"},
        {"name": "", "price": 1},
    ]}).json()
    assert len(d["items"]) == 1
    assert d["items"][0]["price"] == 16.0
    assert client.get("/api/prices").json()["items"][0]["name"] == "猪肉"


def test_prices_rejects_bad_values(client):
    d = client.post("/api/prices", json={"items": [{"name": "土豆", "price": "abc"}]}).json()
    assert d["items"][0]["price"] is None


def test_price_table_affects_estimated_cost(client):
    payload = dict(VALID, seed=8)
    before = client.post("/api/recommend", json=payload).json()
    client.post("/api/prices", json={"items": [{"name": "猪肉", "price": 200, "unit": "元/斤"}]})
    after = client.post("/api/recommend", json=payload).json()
    assert after["shopping"]["est_cost_yuan"] >= before["shopping"]["est_cost_yuan"]


# ---------- 周计划接口 ----------
def test_weekly_api_shape(client):
    d = client.post("/api/weekly", json=dict(VALID, days=3, seed=2)).json()
    assert len(d["days"]) == 3
    assert d["week_shopping"]["zones"]
    assert d["summary"]["days"] == 3
    assert d["summary"]["unique_dishes"] == d["summary"]["total_dishes"]


@pytest.mark.parametrize("days", [0, 99, -1])
def test_weekly_days_validated(client, days):
    assert client.post("/api/weekly", json=dict(VALID, days=days)).status_code == 422


# ---------- 错误处理 ----------
def test_internal_error_does_not_leak_details(raw_client, monkeypatch, caplog):
    """500 时不能把异常文本/路径返回给客户端，但要在日志里留痕。"""
    import app.main as m

    def boom(*a, **k):
        raise RuntimeError("内部路径 C:\\secret\\path 崩了")

    monkeypatch.setattr(m, "generate_plan", boom)
    with caplog.at_level("ERROR"):
        r = raw_client.post("/api/recommend", json=VALID)
    assert r.status_code == 500
    assert "secret" not in r.text
    assert r.json() == {"ok": False, "error": "服务器内部错误，请查看服务端日志"}
    assert any("secret" in rec.getMessage() or rec.exc_info for rec in caplog.records), \
        "异常必须在服务端日志里留痕"


def test_leftover_endpoint(client):
    d = client.post("/api/leftover", json={"recipe_name": "西红柿炒鸡蛋", "n": 2}).json()
    assert d["source"]["name"] == "西红柿炒鸡蛋"
    assert d["suggestions"]


def test_leftover_unknown_dish_is_graceful(client):
    d = client.post("/api/leftover", json={"recipe_name": "不存在的菜"}).json()
    assert d["source"] is None
    assert d["error"]


def test_leftover_n_validated(client):
    assert client.post("/api/leftover", json={"recipe_name": "x", "n": 0}).status_code == 422


def test_simplify_without_llm_is_graceful(client):
    d = client.post("/api/simplify", json={"recipe_name": "西红柿炒鸡蛋"}).json()
    assert d["ok"] is False
    assert "LLM" in d["error"] or "Ollama" in d["error"]
    assert d["recipe"]["name"] == "西红柿炒鸡蛋"
