# -*- coding: utf-8 -*-
"""
多 Agent 编排（LangGraph）—— 路线图 v0.3。

四个 Agent 角色，用 StateGraph 串成"有状态、可回退"的工作流：

    规划师(planner) → 营养师(nutritionist) ──不达标且未超轮次──┐
                            │ 达标                     │
                            ▼                          │
                     采购员(shopper)                    │
                            │                          │
                     搭配师(writer) ←───────────────────┘
                            │
                           END

关键点：营养师评估不达标时，条件路由回退给规划师重新出菜单，
并把"改进方向"（缺蔬菜 / 热量偏高…）作为软约束注入下一轮打分。
全部节点在无 LLM 时也可用规则跑通（BYOK 友好）。
"""
import logging
import random
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from ..config import get_llm_config
from ..core.food_db import dish_costs
from ..core.nutrition import analyze, assess
from ..core.profile import TasteProfile
from ..core.shopping import build_shopping_list
from ..llm.client import LLMClient
from .planner import (
    _pairing_note,
    current_season,
    dish_reasons,
    dish_visual,
    get_engine,
)

logger = logging.getLogger(__name__)

# 营养不达标时最多回退几轮。硬上限，避免"无限重规划 + 无限调 LLM"。
MAX_ATTEMPTS = 3


class PlanState(TypedDict, total=False):
    constraints: dict
    seed: int
    menu: list
    info: dict
    nutrition: dict
    nutrition_issues: list
    retry_hint: str
    shopping: dict
    pairing_note: str
    llm_available: bool
    attempt: int
    trace: list


# ---------- Agent 节点 ----------
def planner_node(state: PlanState) -> dict:
    """菜单规划师：约束引擎出菜单（回退时响应营养师的改进方向）。"""
    attempt = state.get("attempt", 0) + 1
    constraints = dict(state["constraints"])
    hint = state.get("retry_hint", "")
    if hint:
        constraints["retry_hint"] = hint

    rng = random.Random((state.get("seed") or 0) + attempt * 7919)
    menu, info = get_engine().recommend(constraints, rng=rng)

    trace = list(state.get("trace", []))
    names = "、".join(r.get("name", "") for r in menu) if menu else "（无候选）"
    note = f"第 {attempt} 轮出菜单：{names}" + (f"（响应营养师：{hint}）" if hint else "")
    if not menu:
        note = f"第 {attempt} 轮无候选菜：{info.get('error', '')}"
    trace.append({"agent": "规划师", "note": note})
    return {"menu": menu, "info": info, "attempt": attempt, "trace": trace, "constraints": constraints}


def nutritionist_node(state: PlanState) -> dict:
    """营养师：分析 + 达标评估，不达标则给出改进方向。"""
    menu = state.get("menu", [])
    constraints = state["constraints"]
    nutrition = analyze(menu, people=constraints.get("people", 1), goal=constraints.get("nutrition_goal"))
    issues = assess(menu, nutrition, constraints.get("nutrition_goal"))
    hint = "、".join(issues)

    trace = list(state.get("trace", []))
    trace.append({
        "agent": "营养师",
        "note": ("✅ 达标" if not issues else f"⚠️ 不达标：{hint}") +
                f"（人均 {nutrition.get('per_person_kcal')} 大卡，荤/素/汤 "
                f"{nutrition.get('meat_count')}/{nutrition.get('veg_count')}/{nutrition.get('soup_count')}）",
    })
    return {"nutrition": nutrition, "nutrition_issues": issues, "retry_hint": hint, "trace": trace}


def shopper_node(state: PlanState) -> dict:
    """采购员：合并采购清单 + 分区。"""
    menu = state.get("menu", [])
    if not menu:
        return {"shopping": None, "trace": list(state.get("trace", []))}
    people = state["constraints"].get("people", 1)
    shopping = build_shopping_list(menu, people=people)
    trace = list(state.get("trace", []))
    zones = [z["zone"] for z in shopping.get("zones", [])]
    trace.append({"agent": "采购员", "note": f"生成 {len(zones)} 个分区清单：{'/'.join(zones)}，估算 {shopping.get('est_cost_yuan')} 元"})
    return {"shopping": shopping, "trace": trace}


def writer_node(state: PlanState) -> dict:
    """搭配师：搭配说明文案（LLM 优先，无 Key / 失败用模板）。"""
    menu = state.get("menu", [])
    constraints = state["constraints"]
    llm = LLMClient(**get_llm_config())
    note, used_llm = _pairing_note(menu, constraints, llm)

    trace = list(state.get("trace", []))
    trace.append({"agent": "搭配师", "note": ("🤖 LLM 生成搭配说明" if used_llm else "📝 模板搭配说明（未用 LLM）")})
    return {"pairing_note": note, "llm_available": used_llm, "trace": trace}


# ---------- 条件路由 ----------
def route_after_nutrition(state: PlanState) -> str:
    """nutritionist 之后去哪：回规划师重选 / 去采购员 / 直接结束。

    - 菜单为空：再怎么重规划也没有候选菜，直接 END（否则白跑 3 轮 + 白烧 LLM token）
    - 营养不达标且未超最大回退轮次：回规划师
    - 其余：去采购员
    """
    if not state.get("menu"):
        return "end"
    if state.get("nutrition_issues") and state.get("attempt", 0) < MAX_ATTEMPTS:
        return "planner"
    return "shopper"


def route_after_shopper(state: PlanState) -> str:
    """菜单为空时没有采购清单可做，跳过搭配师。"""
    return "writer" if state.get("menu") else "end"


# ---------- 构建并编译图（模块级缓存，只建一次） ----------
def _build_graph():
    g = StateGraph(PlanState)
    g.add_node("planner", planner_node)
    g.add_node("nutritionist", nutritionist_node)
    g.add_node("shopper", shopper_node)
    g.add_node("writer", writer_node)
    g.add_edge(START, "planner")
    g.add_edge("planner", "nutritionist")
    g.add_conditional_edges(
        "nutritionist",
        route_after_nutrition,
        {"planner": "planner", "shopper": "shopper", "end": END},
    )
    g.add_conditional_edges(
        "shopper",
        route_after_shopper,
        {"writer": "writer", "end": END},
    )
    g.add_edge("writer", END)
    return g.compile()


_GRAPH = _build_graph()


# ---------- 对外入口 ----------
def orchestrate(constraints: dict, seed: int = None) -> dict:
    """
    运行多 Agent 编排，返回与 generate_plan 兼容的结构，
    额外带 orchestration / replans / agent_trace 字段。
    """
    constraints = dict(constraints)
    if not constraints.get("season"):
        constraints["season"] = current_season()

    # 家庭味觉画像（软约束打分用，有反馈才生效）
    profile = TasteProfile()
    if profile.data.get("count"):
        constraints["profile"] = profile

    seed_val = seed if seed is not None else random.randint(0, 2**31)

    initial: PlanState = {
        "constraints": constraints,
        "seed": seed_val,
        "attempt": 0,
        "trace": [],
        "menu": [],
        "nutrition_issues": [],
    }
    result = _GRAPH.invoke(initial)

    menu = result.get("menu", [])
    if not menu:
        return {
            "ok": False,
            "error": (result.get("info") or {}).get("error", "无符合条件的菜"),
            "orchestration": "langgraph",
            "mode": "langgraph",
            "agent_trace": result.get("trace", []),
        }

    return {
        "ok": True,
        "menu": menu,
        "pairing_note": result.get("pairing_note", ""),
        "shopping": result.get("shopping"),
        "nutrition": result.get("nutrition"),
        "info": result.get("info", {}),
        "llm_used": result.get("llm_available", False),
        "seed": seed_val,          # 回传实际使用的种子（原来回的是入参，可能是 None）
        "mode": "langgraph",
        "orchestration": "langgraph",
        "replans": max(0, result.get("attempt", 1) - 1),
        "agent_trace": result.get("trace", []),
        "reasons": {r.get("id"): dish_reasons(r, constraints) for r in menu},
        "costs": dish_costs(menu, people=constraints.get("people", 1)),
        "visuals": {r.get("id"): dish_visual(r) for r in menu},
    }
