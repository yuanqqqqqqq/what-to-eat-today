# -*- coding: utf-8 -*-
"""LLM 容错：没有 Key / Key 无效 / 超时 / 返回异常，核心推荐都必须照常可用。

这是项目的重要卖点：不配 LLM 也能完整使用。
"""
import httpx
import pytest

from app.agents.planner import _pairing_note, _template_pairing_note, generate_plan, simplify_recipe
from app.config import get_llm_config, is_masked, mask_key, save_llm_config
from app.llm.client import LLMClient, LLMError

MENU = [{"id": "a", "name": "西红柿炒鸡蛋", "dish_type": "素", "difficulty": 2,
         "estimated_minutes": 15, "calories_kcal": 200, "ingredients": [], "steps": []},
        {"id": "b", "name": "白灼菜心", "dish_type": "素", "difficulty": 1,
         "estimated_minutes": 10, "calories_kcal": 120, "ingredients": [], "steps": []}]


# ---------- 客户端可用性 ----------
def test_unavailable_without_key():
    assert LLMClient(base_url="https://api.deepseek.com/v1", api_key="", model="m").available is False
    assert LLMClient(base_url="", api_key="sk-x", model="m").available is False
    assert LLMClient(base_url="https://x/v1", api_key="sk-x", model="").available is False


def test_ollama_needs_no_key():
    assert LLMClient(base_url="http://127.0.0.1:11434/v1", api_key="", model="qwen").available is True


def test_chat_without_config_raises_llm_error():
    with pytest.raises(LLMError):
        LLMClient(base_url="", api_key="", model="").chat([{"role": "user", "content": "hi"}])


# ---------- 错误信息不含 Key ----------
def test_error_message_never_contains_api_key(monkeypatch):
    secret = "sk-verysecretvalue12345"
    llm = LLMClient(base_url="https://api.example.com/v1", api_key=secret, model="m")

    def raise_status(*a, **k):
        req = httpx.Request("POST", "https://api.example.com/v1/chat/completions",
                            headers={"Authorization": f"Bearer {secret}"})
        resp = httpx.Response(401, request=req)
        raise httpx.HTTPStatusError("unauthorized", request=req, response=resp)

    monkeypatch.setattr(httpx, "post", raise_status)
    with pytest.raises(LLMError) as e:
        llm.chat([{"role": "user", "content": "hi"}])
    assert secret not in str(e.value)
    assert "401" in str(e.value)


def test_timeout_becomes_llm_error(monkeypatch):
    llm = LLMClient(base_url="https://x/v1", api_key="k", model="m", timeout=0.01)

    def raise_timeout(*a, **k):
        raise httpx.ConnectTimeout("timed out")

    monkeypatch.setattr(httpx, "post", raise_timeout)
    with pytest.raises(LLMError) as e:
        llm.chat([{"role": "user", "content": "hi"}])
    assert "超时" in str(e.value)


def test_malformed_response_becomes_llm_error(monkeypatch):
    llm = LLMClient(base_url="https://x/v1", api_key="k", model="m")

    def ok(*a, **k):
        return httpx.Response(200, json={"unexpected": True},
                              request=httpx.Request("POST", "https://x/v1/chat/completions"))

    monkeypatch.setattr(httpx, "post", ok)
    with pytest.raises(LLMError):
        llm.chat([{"role": "user", "content": "hi"}])


def test_non_json_response_becomes_llm_error(monkeypatch):
    llm = LLMClient(base_url="https://x/v1", api_key="k", model="m")

    def ok(*a, **k):
        return httpx.Response(200, text="<html>502</html>",
                              request=httpx.Request("POST", "https://x/v1/chat/completions"))

    monkeypatch.setattr(httpx, "post", ok)
    with pytest.raises(LLMError):
        llm.chat([{"role": "user", "content": "hi"}])


# ---------- 搭配说明的回落 ----------
def test_pairing_note_without_llm_uses_template_and_says_so():
    llm = LLMClient(base_url="", api_key="", model="")
    note, used = _pairing_note(MENU, {"people": 2}, llm)
    assert used is False
    assert note == _template_pairing_note(MENU, {"people": 2})
    assert "本餐组合" in note


def test_pairing_note_falls_back_when_call_fails(monkeypatch):
    llm = LLMClient(base_url="https://x/v1", api_key="k", model="m")
    monkeypatch.setattr(LLMClient, "chat", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    note, used = _pairing_note(MENU, {"people": 2}, llm)
    assert used is False, "调用失败却声称用了 LLM 是误导"
    assert "本餐组合" in note


def test_pairing_note_falls_back_on_empty_reply(monkeypatch):
    llm = LLMClient(base_url="https://x/v1", api_key="k", model="m")
    monkeypatch.setattr(LLMClient, "chat", lambda *a, **k: "   ")
    note, used = _pairing_note(MENU, {"people": 2}, llm)
    assert used is False
    assert "本餐组合" in note


def test_pairing_note_uses_llm_when_it_works(monkeypatch):
    llm = LLMClient(base_url="https://x/v1", api_key="k", model="m")
    monkeypatch.setattr(LLMClient, "chat", lambda *a, **k: "荤素搭配得当，清清爽爽。")
    note, used = _pairing_note(MENU, {"people": 2}, llm)
    assert used is True
    assert note == "荤素搭配得当，清清爽爽。"


def test_template_note_warns_when_no_veg():
    meat_only = [dict(MENU[0], dish_type="荤")]
    assert "缺少蔬菜" in _template_pairing_note(meat_only, {})


# ---------- 端到端：没有 LLM 也能出完整方案 ----------
def test_generate_plan_works_without_llm(clean_user_data):
    plan = generate_plan({"people": 3, "dishes": 2, "soups": 1, "taboos": [], "allergies": [],
                          "taste_prefs": [], "devices": [], "pantry": [], "locked_ids": [],
                          "dislikes": [], "favorite_ids": [], "seed": 1})
    assert plan["ok"] is True
    assert plan["llm_used"] is False
    assert plan["menu"] and plan["shopping"]["zones"] and plan["nutrition"]["total_kcal"] > 0
    assert plan["pairing_note"]


def test_generate_plan_survives_broken_llm(clean_user_data, monkeypatch):
    """配了一个用不了的 Key：推荐结果必须完整，只是文案退回模板。"""
    save_llm_config({"base_url": "https://api.invalid/v1", "api_key": "sk-broken", "model": "m"})
    monkeypatch.setattr(LLMClient, "chat",
                        lambda *a, **k: (_ for _ in ()).throw(LLMError("LLM 接口返回 401")))
    plan = generate_plan({"people": 3, "dishes": 2, "soups": 1, "taboos": [], "allergies": [],
                          "taste_prefs": [], "devices": [], "pantry": [], "locked_ids": [],
                          "dislikes": [], "favorite_ids": [], "seed": 2})
    assert plan["ok"] is True
    assert plan["llm_used"] is False
    assert plan["menu"]
    assert "本餐组合" in plan["pairing_note"]


def test_simplify_without_llm_reports_clearly(clean_user_data):
    out = simplify_recipe("西红柿炒鸡蛋")
    assert out["ok"] is False
    assert out["recipe"]
    assert "LLM" in out["error"] or "Ollama" in out["error"]


def test_simplify_survives_llm_failure(clean_user_data, monkeypatch):
    save_llm_config({"base_url": "https://api.invalid/v1", "api_key": "sk-broken", "model": "m"})
    monkeypatch.setattr(LLMClient, "chat",
                        lambda *a, **k: (_ for _ in ()).throw(LLMError("LLM 请求超时（30 秒）")))
    out = simplify_recipe("西红柿炒鸡蛋")
    assert out["ok"] is False
    assert "超时" in out["error"]
    assert out["recipe"], "失败也要把原菜谱带回去，前端还能显示原做法"


# ---------- Key 脱敏 ----------
@pytest.mark.parametrize("key,expected", [
    ("", ""),
    ("short", "****"),
    ("sk-abcdefghijklmnop", "sk-****mnop"),
])
def test_mask_key(key, expected):
    assert mask_key(key) == expected


def test_is_masked():
    assert is_masked("sk-****mnop") is True
    assert is_masked("sk-real") is False
    assert is_masked("") is False


def test_saved_config_roundtrip(clean_user_data):
    save_llm_config({"base_url": "https://x/v1", "api_key": "sk-abcdefghijkl", "model": "m"})
    cfg = get_llm_config()
    assert cfg["api_key"] == "sk-abcdefghijkl"
    # 脱敏串回传不应覆盖真实 Key
    save_llm_config({"base_url": "https://x/v1", "api_key": mask_key(cfg["api_key"]), "model": "m2"})
    assert get_llm_config()["api_key"] == "sk-abcdefghijkl"
    assert get_llm_config()["model"] == "m2"
