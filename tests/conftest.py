# -*- coding: utf-8 -*-
"""测试夹具。

关键点：在 import app.* 之前把 APP_DATA_DIR 指到临时目录，
否则测试会写坏用户真实数据（data/profile.json、prices.json、settings.json…）。
"""
import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

# ---- 必须在导入 app 之前设置 ----
_TMP_DATA = Path(tempfile.mkdtemp(prefix="meal-test-data-"))
os.environ["APP_DATA_DIR"] = str(_TMP_DATA)
os.environ.pop("LLM_API_KEY", None)
os.environ.pop("LLM_BASE_URL", None)
os.environ.pop("LLM_MODEL", None)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.constraint_engine import ConstraintEngine  # noqa: E402
from app.paths import data_file, resource  # noqa: E402


@pytest.fixture(scope="session")
def recipes():
    return json.load(open(resource("data/recipes.json"), encoding="utf-8"))


@pytest.fixture(scope="session")
def engine(recipes):
    return ConstraintEngine(recipes)


@pytest.fixture
def base_constraints():
    """一份完整、干净的请求参数（避免每个用例重复拼）。"""
    return {
        "people": 3, "dishes": 2, "soups": 1,
        "taboos": [], "allergies": [], "taste_prefs": [], "devices": [],
        "pantry": [], "locked_ids": [], "dislikes": [], "favorite_ids": [],
        "budget": None, "time_budget": None, "max_difficulty": None,
        "must_include": [], "nutrition_goal": None, "scene_id": None, "homely": True,
    }


@pytest.fixture
def clean_user_data():
    """每个用例前清掉用户数据文件，保证互不干扰。"""
    for name in ("profile.json", "pantry.json", "prices.json",
                 "settings.json", "user_recipes.json"):
        p = data_file(name)
        if p.exists():
            p.unlink()
    yield
    for name in ("profile.json", "pantry.json", "prices.json",
                 "settings.json", "user_recipes.json"):
        p = data_file(name)
        if p.exists():
            p.unlink()


@pytest.fixture
def client(clean_user_data):
    """FastAPI 测试客户端。"""
    from fastapi.testclient import TestClient

    from app.main import app
    with TestClient(app) as c:
        yield c


@pytest.fixture
def raw_client(clean_user_data):
    """不把服务端异常直接抛出来的客户端：用于验证 500 的响应体。"""
    from fastapi.testclient import TestClient

    from app.main import app
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
