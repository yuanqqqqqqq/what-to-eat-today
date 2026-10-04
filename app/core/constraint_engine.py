# -*- coding: utf-8 -*-
"""
约束内随机引擎（产品核心）
流程：硬约束过滤 -> 软约束打分 -> 加权随机 -> 组合校验

纯确定性代码实现，不依赖 LLM，可测试、可复现。
"""
import math
import random
from .rules import (
    TABOO_RULES, ALLERGY_RULES, ingredient_hit, recipe_needs_devices,
)


class ConstraintEngine:
    # 参与"几菜几汤"的 dish_type（主食/甜点/饮品/半成品等不参与）
    MEAL_DISH_TYPES = {"荤", "素"}
    SOUP_DISH_TYPES = {"汤"}

    def __init__(self, recipes):
        self.recipes = recipes

    # ---------- 第一步：硬约束过滤 ----------
    def hard_filter(self, constraints):
        no_spicy = "辣" in constraints.get("taboos", [])
        other_kws = self._taboo_keywords(constraints, exclude_spicy=True)
        devices = set(constraints.get("devices", []))
        time_budget = constraints.get("time_budget")
        max_difficulty = constraints.get("max_difficulty")
        budget = constraints.get("budget")
        exclude_ids = set(constraints.get("exclude_ids") or [])

        pool = []
        for r in self.recipes:
            # 周计划去重：排除已经用过的菜
            if r.get("id") in exclude_ids:
                continue
            # 忌口"辣"：优先用 LLM 标注的辣度（微辣也算辣）
            if no_spicy and r.get("spiciness") in ("辣", "微辣"):
                continue
            # 其他忌口/过敏（原料关键词命中即排除）
            if other_kws and ingredient_hit(r, other_kws):
                continue
            # 设备（需要的设备 ⊆ 用户设备）
            needed = recipe_needs_devices(r)
            if needed and not needed.issubset(devices):
                continue
            # 时间预算（单道菜耗时 <= 预算；耗时未知的菜在有限时约束时保守排除）
            if time_budget:
                est = r.get("estimated_minutes")
                if est is None or est > time_budget:
                    continue
            # 难度上限
            if max_difficulty and r.get("difficulty") and r["difficulty"] > max_difficulty:
                continue
            # 预算：粗估成本 = 卡路里 * 0.03 元/大卡（MVP 占位，后续接真实价格）
            if budget and r.get("calories_kcal"):
                est_cost = r["calories_kcal"] * 0.03
                if est_cost > budget:
                    continue
            pool.append(r)
        return pool

    def _taboo_keywords(self, constraints, exclude_spicy=False):
        kws = []
        for t in constraints.get("taboos", []):
            if exclude_spicy and t == "辣":
                continue
            kws.extend(TABOO_RULES.get(t, []))
        for a in constraints.get("allergies", []):
            kws.extend(ALLERGY_RULES.get(a, []))
        return kws

    # ---------- 第二步：软约束打分 ----------
    def score(self, recipe, constraints):
        s = 0.0
        # 食材复用：家里现有食材命中加分（优先消耗）
        pantry = [p.strip() for p in constraints.get("pantry", []) if p.strip()]
        if pantry:
            names = [ing["name"] for ing in recipe.get("ingredients", [])]
            names += [c["name"] for c in recipe.get("calculations", [])]
            joined = " ".join(names)
            for p in pantry:
                if p in joined:
                    s += 3.0
        # 口味偏好：LLM 标注的 taste 字段
        prefs = constraints.get("taste_prefs", [])
        if prefs:
            r_tastes = set(recipe.get("taste") or [])
            s += 1.5 * sum(1 for p in prefs if p in r_tastes)
        # 时令：当前季节匹配加分（"四季"通用菜恒加分）
        season = constraints.get("season")
        if season and recipe.get("season") in (season, "四季"):
            s += 1.0
        # 家庭味觉画像（软约束）：喜欢的菜 / 口味 / 食材加分，讨厌的减分
        profile = constraints.get("profile")
        if profile is not None:
            s += profile.score_recipe(recipe)
        return s

    # ---------- 第三步：加权随机 ----------
    def weighted_sample(self, candidates, k, constraints, rng):
        if not candidates:
            return []
        scored = [(self.score(r, constraints), r) for r in candidates]
        # 分数 -> 权重：保底 0.5，避免高分垄断、低分归零（"惊喜但不离谱"）
        weights = [max(0.5, 1.0 + sc) for sc, _ in scored]
        picked = []
        remain = list(candidates)
        remain_weights = list(weights)
        for _ in range(min(k, len(remain))):
            if not remain:
                break
            total = sum(remain_weights)
            r = rng.random() * total
            acc = 0
            idx = 0
            for i, w in enumerate(remain_weights):
                acc += w
                if r <= acc:
                    idx = i
                    break
            picked.append(remain.pop(idx))
            remain_weights.pop(idx)
        return picked

    # ---------- 第四步：组合校验 ----------
    def validate_combo(self, combo, constraints, pool_has_meat=False):
        if not combo:
            return False
        # 不重复
        ids = [r["id"] for r in combo]
        if len(ids) != len(set(ids)):
            return False
        # 想吃的菜必须在
        must = set(constraints.get("must_include", []))
        for m in must:
            if not any(m in r["name"] for r in combo):
                return False
        # 荤素搭配：非汤部分至少 1 道荤（前提：候选池里确实存在荤菜）
        dish_part = [r for r in combo if r.get("dish_type") != "汤"]
        if pool_has_meat and len(dish_part) >= 2:
            if not any(r.get("dish_type") == "荤" for r in dish_part):
                return False
        return True

    # ---------- 主入口 ----------
    def recommend(self, constraints, rng=None, max_attempts=50):
        """
        返回 (菜单列表, 说明 dict)
        constraints: {people, dishes, soups, taboos, allergies, taste_prefs,
                      budget, time_budget, devices, max_difficulty, must_include, pantry}
        """
        rng = rng or random.Random()
        dishes_n = constraints.get("dishes", 2)
        soups_n = constraints.get("soups", 1)
        total_n = dishes_n + soups_n

        pool = self.hard_filter(constraints)
        if not pool:
            return [], {"error": "硬约束过滤后无候选菜", "pool_size": 0}

        soup_pool = [r for r in pool if r.get("dish_type") in self.SOUP_DISH_TYPES]
        dish_pool = [r for r in pool if r.get("dish_type") in self.MEAL_DISH_TYPES]
        pool_has_meat = any(r.get("dish_type") == "荤" for r in dish_pool)

        best = None
        for _ in range(max_attempts):
            soups = self.weighted_sample(soup_pool, soups_n, constraints, rng) if soups_n else []
            dishes = self.weighted_sample(dish_pool, dishes_n, constraints, rng) if dishes_n else []
            combo = dishes + soups
            if self.validate_combo(combo, constraints, pool_has_meat):
                best = combo
                break
            if best is None:
                best = combo  # 兜底

        info = {
            "pool_size": len(pool),
            "soup_pool": len(soup_pool),
            "dish_pool": len(dish_pool),
            "attempts_used": _ + 1,
        }
        return best or [], info
