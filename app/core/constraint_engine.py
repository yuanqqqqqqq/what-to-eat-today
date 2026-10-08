# -*- coding: utf-8 -*-
"""
约束内随机引擎（产品核心）
流程：硬约束过滤 -> 软约束打分 -> 加权随机 -> 组合校验

纯确定性代码实现，不依赖 LLM，可测试、可复现。
"""
import random
from .rules import (
    TABOO_RULES, ALLERGY_RULES, ingredient_hit, recipe_needs_devices, is_homely,
    substantive_ingredients,
)
from .scenes import scene_hard_exclude, scene_score
from .food_db import estimate_meal_cost


class ConstraintEngine:
    # 参与"几菜几汤"的 dish_type（主食/甜点/饮品/半成品等不参与）
    MEAL_DISH_TYPES = {"荤", "素"}
    SOUP_DISH_TYPES = {"汤"}

    # ---- 软约束权重（只影响概率，不影响硬约束；改这里请同步 tests/test_constraint_engine.py）----
    W_FAVORITE = 3.0          # 收藏过
    W_PANTRY_HIT = 3.0        # 每命中一种家里现成食材
    W_PANTRY_CAP = 6.0        # 食材复用加分上限（否则常备食材一多，这几道菜垄断推荐）
    W_TASTE = 1.5             # 每命中一个口味偏好
    W_SEASON = 1.0            # 当季
    MIN_WEIGHT = 0.5          # 权重保底：低分菜概率低但不为零（"惊喜但不离谱"）
    # 同餐重复：与已选菜共享实质主料时逐级降权（0.45^n）
    DIVERSITY_FACTOR = 0.45
    DIVERSITY_FLOOR = 0.15
    # 荤素搭配：整桌还没有素菜/荤菜时，给对应类型加权
    VEG_BONUS = 1.6
    MEAT_BONUS = 1.4
    # 周计划：跨天复用上周用过的食材，轻微降权（复用是好事，所以力度很轻）
    W_RECENT_INGREDIENT = -0.4
    W_RECENT_CAP = -2.0

    def __init__(self, recipes):
        self.recipes = recipes
        self._sub_cache = {}

    # ---------- 第一步：硬约束过滤 ----------
    def hard_filter(self, constraints):
        no_spicy = "辣" in constraints.get("taboos", [])
        other_kws = self._taboo_keywords(constraints, exclude_spicy=True)
        dislikes = constraints.get("dislikes") or []
        devices = set(constraints.get("devices", []))
        time_budget = constraints.get("time_budget")
        max_difficulty = constraints.get("max_difficulty")
        exclude_ids = set(constraints.get("exclude_ids") or [])
        scene_id = constraints.get("scene_id")

        pool = []
        for r in self.recipes:
            # 周计划去重：排除已经用过的菜
            if r.get("id") in exclude_ids:
                continue
            # 家常化：默认排除名贵/偏贵食材（数据保留，可搜索）
            if constraints.get("homely", True) and not is_homely(r):
                continue
            # 场景硬排除（便当少汤 / 控糖避甜食等）
            if scene_id and scene_hard_exclude(scene_id, r):
                continue
            # 忌口"辣"：优先用 LLM 标注的辣度（微辣也算辣）
            if no_spicy and r.get("spiciness") in ("辣", "微辣"):
                continue
            # 其他忌口/过敏（原料关键词命中即排除）
            if other_kws and ingredient_hit(r, other_kws):
                continue
            # 讨厌的食材（直接匹配菜名/原料，硬排除）
            if dislikes and ingredient_hit(r, dislikes):
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
        # 收藏的菜加分（用户点过收藏，更倾向出现）
        favorite_ids = constraints.get("favorite_ids") or []
        if favorite_ids and recipe.get("id") in favorite_ids:
            s += self.W_FAVORITE
        # 食材复用：家里现有食材命中加分（优先消耗），有上限，避免常备食材一多就垄断
        pantry = [p.strip() for p in constraints.get("pantry", []) if p.strip()]
        if pantry:
            names = [ing.get("name", "") for ing in recipe.get("ingredients", [])]
            names += [c.get("name", "") for c in recipe.get("calculations", [])]
            joined = " ".join(names)
            hits = sum(1 for p in pantry if p in joined)
            if hits:
                s += min(self.W_PANTRY_HIT * hits, self.W_PANTRY_CAP)
        # 口味偏好：LLM 标注的 taste 字段
        prefs = constraints.get("taste_prefs", [])
        if prefs:
            r_tastes = set(recipe.get("taste") or [])
            s += self.W_TASTE * sum(1 for p in prefs if p in r_tastes)
        # 时令：只有"正是这个季节"才加分。
        # 曾经的写法把"四季"也当作时令命中，结果 372 道里 270 道都拿这 1.0 分，
        # 相当于给大多数菜加了个常数，时令信号等于没有。
        season = constraints.get("season")
        if season and recipe.get("season") == season:
            s += self.W_SEASON
        # 周计划：上周（前几天）用过的食材轻微降权，让整周不至于反复同一批主料
        recent = constraints.get("recent_ingredients") or set()
        if recent:
            reused = self._sub_ingredients(recipe) & set(recent)
            if reused:
                s += max(self.W_RECENT_INGREDIENT * len(reused), self.W_RECENT_CAP)
        # 家庭味觉画像（软约束）：喜欢的菜 / 口味 / 食材加分，讨厌的减分
        profile = constraints.get("profile")
        if profile is not None:
            s += profile.score_recipe(recipe)
        # 营养师回退反馈（软约束）：如"缺蔬菜"给素菜加分，"热量偏高"给低热量菜加分
        hint = constraints.get("retry_hint") or ""
        if hint:
            if ("蔬菜" in hint or "素" in hint) and recipe.get("dish_type") == "素":
                s += 2.0
            if "热量" in hint or "清淡" in hint:
                kcal = recipe.get("calories_kcal") or 0
                if 0 < kcal <= 200:
                    s += 2.0
            if "蛋白" in hint and recipe.get("dish_type") in ("荤", "汤"):
                s += 1.0
        # 场景软约束（便当耐放 / 家宴硬菜 / 控糖低 GI / 减脂低热量）
        s += scene_score(constraints.get("scene_id"), recipe)
        return s

    # ---------- 第三步：加权随机 ----------
    def weighted_sample(self, candidates, k, constraints, rng, adjust=None, context=None):
        """按权重不放回抽取 k 个。

        adjust(candidate, context) 返回一个乘数，用于让"已选了什么"影响后续概率
        （组合多样性 / 荤素搭配）。context 以已有选择（含锁定菜）为起点。
        默认 adjust=None 时为纯独立加权抽样。
        """
        if not candidates:
            return []
        picked = []
        ctx = list(context or [])
        remain = list(candidates)
        for _ in range(min(k, len(remain))):
            if not remain:
                break
            weights = []
            for r in remain:
                # 分数 -> 权重：保底 MIN_WEIGHT，避免高分垄断、低分归零（"惊喜但不离谱"）
                w = max(self.MIN_WEIGHT, 1.0 + self.score(r, constraints))
                if adjust:
                    w *= adjust(r, ctx)
                weights.append(w)
            total = sum(weights)
            if total <= 0:
                break
            x = rng.random() * total
            acc = 0.0
            idx = len(remain) - 1
            for i, w in enumerate(weights):
                acc += w
                if x <= acc:
                    idx = i
                    break
            chosen = remain.pop(idx)
            picked.append(chosen)
            ctx.append(chosen)
        return picked

    def combo_adjust(self, constraints):
        """返回"已选菜如何影响下一道菜概率"的函数（只改概率，不改硬约束）。"""
        pool_has_veg = constraints.get("_pool_has_veg", True)

        def adjust(cand, picked):
            if not picked:
                return 1.0
            w = 1.0
            # 同餐食材重复：与已选菜共享实质主料就降权（避免"西红柿炒蛋 + 西红柿蛋汤"）
            ing = self._sub_ingredients(cand)
            if ing:
                shared = sum(len(ing & self._sub_ingredients(p)) for p in picked)
                if shared:
                    w *= self.DIVERSITY_FACTOR ** shared
            # 荤素搭配：整桌还没素菜/荤菜时给对应类型加权
            types = {p.get("dish_type") for p in picked}
            d_type = cand.get("dish_type")
            if d_type == "素" and "素" not in types and pool_has_veg:
                w *= self.VEG_BONUS
            elif d_type == "荤" and "荤" not in types:
                w *= self.MEAT_BONUS
            return max(w, self.DIVERSITY_FLOOR)

        return adjust

    def _sub_ingredients(self, recipe) -> set:
        """一道菜的实质主料集合（过滤调料/葱姜蒜），带缓存。"""
        rid = recipe.get("id")
        if rid is not None and rid in self._sub_cache:
            return self._sub_cache[rid]
        names = [i.get("name", "") for i in recipe.get("ingredients", [])]
        out = set(substantive_ingredients(names))
        if rid is not None:
            self._sub_cache[rid] = out
        return out

    # ---------- 第四步：组合校验（硬约束，不通过就换一组）----------
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
        # 总预算（整桌，含人数系数）：与前端展示的成本用同一个函数、同一份价格表，
        # 否则"用户填了菜市场价，预算校验却按内置均价算"。
        budget = constraints.get("budget")
        if budget and self.meal_cost(combo, constraints) > budget:
            return False
        return True

    def meal_cost(self, combo, constraints) -> float:
        """整桌成本估算（与采购清单展示口径一致）。"""
        return estimate_meal_cost(combo, constraints.get("people", 1))

    # ---------- 主入口 ----------
    def recommend(self, constraints, rng=None, max_attempts=50):
        """
        返回 (菜单列表, 说明 dict)
        constraints: {people, dishes, soups, taboos, allergies, taste_prefs,
                      budget, time_budget, devices, max_difficulty, must_include,
                      pantry, locked_ids, exclude_ids, recent_ingredients}
        """
        rng = rng or random.Random()
        max_attempts = max(1, int(max_attempts or 1))
        dishes_n = max(0, int(constraints.get("dishes", 2) or 0))
        soups_n = max(0, int(constraints.get("soups", 1) or 0))
        total_n = dishes_n + soups_n

        # 锁定菜：优先放入菜单（用户保存的菜，再随机也不消失），绕过家常化过滤
        locked_ids = constraints.get("locked_ids") or []
        locked = [r for r in self.recipes if r.get("id") in locked_ids][:total_n]
        locked_ids_set = {r["id"] for r in locked}

        pool = self.hard_filter(constraints)
        if not pool and not locked:
            return [], {"error": "硬约束过滤后无候选菜", "pool_size": 0}
        if total_n == 0 and not locked:
            return [], {"error": "请至少选择 1 道菜或 1 道汤", "pool_size": len(pool)}

        # 已锁定的菜分别占了几道荤/素/汤，剩余菜位再随机补齐
        locked_soups = sum(1 for r in locked if r.get("dish_type") in self.SOUP_DISH_TYPES)
        locked_dishes = sum(1 for r in locked if r.get("dish_type") in self.MEAL_DISH_TYPES)
        need_soups = max(0, soups_n - locked_soups)
        need_dishes = max(0, dishes_n - locked_dishes)

        soup_pool = [r for r in pool if r.get("dish_type") in self.SOUP_DISH_TYPES and r.get("id") not in locked_ids_set]
        dish_pool = [r for r in pool if r.get("dish_type") in self.MEAL_DISH_TYPES and r.get("id") not in locked_ids_set]
        pool_has_meat = any(r.get("dish_type") == "荤" for r in dish_pool) or any(r.get("dish_type") == "荤" for r in locked)

        # 荤素搭配：候选池里没有素菜时不必给素菜加权
        constraints = dict(constraints)
        constraints["_pool_has_veg"] = any(r.get("dish_type") == "素" for r in dish_pool)
        adjust = self.combo_adjust(constraints)

        best = None            # 硬约束通过 + 软偏好（荤素均衡）也满足
        first_valid = None     # 硬约束通过，但荤素不均衡（尽量不用）
        best_fallback = None   # 硬约束都没过，成本最接近约束的兜底组合
        best_fallback_cost = None
        attempts = 0
        pool_has_veg = constraints["_pool_has_veg"]
        for _ in range(max_attempts):
            attempts += 1
            # 锁定菜先入席，让后续抽签能看到"已经有什么"，从而做荤素与食材互补
            dishes = self.weighted_sample(
                dish_pool, need_dishes, constraints, rng, adjust=adjust, context=locked) if need_dishes else []
            soups = self.weighted_sample(
                soup_pool, need_soups, constraints, rng, adjust=adjust, context=locked + dishes) if need_soups else []
            combo = locked + dishes + soups
            if self.validate_combo(combo, constraints, pool_has_meat):
                # 硬约束已过。再看软偏好：多菜位却没有素菜 → 记下备选，继续多摇几次
                if self._is_balanced(combo, pool_has_veg):
                    best = combo
                    break
                if first_valid is None:
                    first_valid = combo
                continue
            # 兜底：记住成本最低的组合（如预算太紧，返回最接近预算的）
            cost = self.meal_cost(combo, constraints)
            if best_fallback_cost is None or cost < best_fallback_cost:
                best_fallback = combo
                best_fallback_cost = cost

        # 兜底优先级：均衡组合 > 硬约束通过但不均衡 > 都不过时成本最低
        # 注意：最后一档可能不满足预算/荤素搭配，前端必须显著提示（info.fallback）。
        fallback = best is None and first_valid is None and best_fallback is not None
        final = best or first_valid or best_fallback or locked or []
        info = {
            "pool_size": len(pool),
            "soup_pool": len(soup_pool),
            "dish_pool": len(dish_pool),
            "locked_count": len(locked),
            "attempts_used": attempts,
            "fallback": fallback,
            "balanced": self._is_balanced(final, pool_has_veg),
        }
        if fallback:
            info["fallback_reason"] = self._fallback_reason(final, constraints, pool_has_meat)
        return final, info

    @staticmethod
    def _is_balanced(combo, pool_has_veg: bool) -> bool:
        """软偏好：多菜位的整桌至少配一道素菜（候选池里确实有素菜时）。"""
        if not pool_has_veg:
            return True
        dish_part = [r for r in combo if r.get("dish_type") != "汤"]
        if len(dish_part) < 2:
            return True
        return any(r.get("dish_type") == "素" for r in dish_part)

    def _fallback_reason(self, combo, constraints, pool_has_meat) -> str:
        """兜底时说明"哪条硬约束没满足"，让用户知道该放宽什么。"""
        if not combo:
            return "没有可用的候选菜"
        if constraints.get("budget"):
            cost = self.meal_cost(combo, constraints)
            if cost > constraints["budget"]:
                return f"预算 {constraints['budget']:.0f} 元偏紧，最低约 {cost:.0f} 元"
        dish_part = [r for r in combo if r.get("dish_type") != "汤"]
        if pool_has_meat and len(dish_part) >= 2 and not any(r.get("dish_type") == "荤" for r in dish_part):
            return "候选菜里没有合适的荤菜，无法兼顾荤素搭配"
        return "约束组合较紧，已给出最接近的一组"
