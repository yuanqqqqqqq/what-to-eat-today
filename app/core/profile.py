# -*- coding: utf-8 -*-
"""
家庭味觉画像：记录 👍/👎 反馈，沉淀口味 / 食材 / 菜品偏好，反哺推荐打分。

数据存在 data/profile.json（纯本地）。画像只作用于"软约束打分"阶段，
不改变忌口 / 过敏等硬约束。
"""
import json
import logging
from datetime import datetime

from .rules import substantive_ingredients
from ..paths import data_file

logger = logging.getLogger(__name__)

PROFILE_FILE = data_file("profile.json")


def default_profile() -> dict:
    """新建一份空画像。

    必须是"每次新建"而不是共享一个模块级常量：这些值是 dict/list，
    一旦被 record() 原地修改，就会污染所有后续的"空画像"
    （例如用户删掉 profile.json 后，旧分数还在内存里生效）。
    """
    return {
        "dish_likes": {},        # recipe id -> 累计分（喜欢 +1 / 不喜欢 -1）
        "dish_names": {},        # recipe id -> 菜名
        "taste_scores": {},      # 口味 -> 累计分
        "ingredient_scores": {}, # 实质主料 -> 累计分
        "history": [],           # 最近反馈（倒序，最多 200 条）
        "count": 0,
    }


# 兼容旧引用（只读用途）；内部一律用 default_profile() 新建
DEFAULT_PROFILE = default_profile()


def load_profile() -> dict:
    out = default_profile()
    if PROFILE_FILE.exists():
        try:
            with open(PROFILE_FILE, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                # 合并旧文件缺的字段；已有字段直接取文件里的容器（本身就是新对象）
                for k, v in data.items():
                    if k in out:
                        out[k] = v
                for k, v in default_profile().items():
                    if not isinstance(out.get(k), type(v)):
                        logger.warning("profile.json 字段 %s 类型异常，已重置", k)
                        out[k] = v
                return out
            logger.warning("profile.json 不是对象，已忽略")
        except Exception:
            logger.warning("profile.json 读取失败，按空画像处理", exc_info=True)
    return out


def save_profile(data: dict) -> None:
    PROFILE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(PROFILE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)


class TasteProfile:
    def __init__(self):
        self.data = load_profile()

    def record(self, recipe: dict, feedback: int) -> None:
        """feedback: 1 喜欢 / -1 不喜欢。"""
        rid = recipe.get("id", "")
        if not rid:
            return
        self.data["dish_likes"][rid] = self.data["dish_likes"].get(rid, 0) + feedback
        self.data["dish_names"][rid] = recipe.get("name", "")
        for t in recipe.get("taste") or []:
            self.data["taste_scores"][t] = self.data["taste_scores"].get(t, 0) + feedback
        # 只沉淀实质主料（过滤调料/葱姜蒜/小节标题，并按清洗后的名字聚合，
        # 否则"西兰花"与"西兰花 1 个"会变成两个桶，画像被稀释）
        for name in substantive_ingredients([ing.get("name", "") for ing in recipe.get("ingredients", [])]):
            self.data["ingredient_scores"][name] = self.data["ingredient_scores"].get(name, 0) + feedback
        self.data["history"].insert(0, {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "recipe_id": rid,
            "name": recipe.get("name", ""),
            "feedback": feedback,
            "tastes": recipe.get("taste") or [],
        })
        self.data["history"] = self.data["history"][:200]
        self.data["count"] += 1
        save_profile(self.data)

    def score_recipe(self, recipe: dict) -> float:
        """画像对一道菜的加分 / 减分（软约束，力度弱于硬约束）。

        取食材的方式必须和 record() 完全一致（都走 substantive_ingredients 的清洗），
        否则写进去的是"西兰花"、读的是"西兰花 1 个"，画像永远拿不到分。
        """
        s = 0.0
        s += self.data["dish_likes"].get(recipe.get("id"), 0) * 2.0
        for t in recipe.get("taste") or []:
            s += self.data["taste_scores"].get(t, 0) * 0.5
        names = substantive_ingredients([ing.get("name", "") for ing in recipe.get("ingredients") or []])
        for name in names:
            s += self.data["ingredient_scores"].get(name, 0) * 0.3
        return s

    def summary(self) -> dict:
        """画像摘要：最爱的口味 / 食材 / 菜品，供前端展示。"""
        def top(d, k=5):
            return [{"name": name, "score": sc} for name, sc in
                    sorted(d.items(), key=lambda x: x[1], reverse=True) if sc > 0][:k]

        def bottom(d, k=5):
            return [{"name": name, "score": sc} for name, sc in
                    sorted(d.items(), key=lambda x: x[1]) if sc < 0][:k]

        dish_names = self.data.get("dish_names", {})
        top_dishes = [{"name": dish_names.get(rid, rid), "score": sc}
                      for rid, sc in sorted(self.data["dish_likes"].items(), key=lambda x: x[1], reverse=True)
                      if sc > 0][:8]

        return {
            "count": self.data["count"],
            "top_tastes": top(self.data["taste_scores"]),
            "top_ingredients": top(self.data["ingredient_scores"], k=8),
            "avoid_ingredients": bottom(self.data["ingredient_scores"], k=8),
            "top_dishes": top_dishes,
        }
