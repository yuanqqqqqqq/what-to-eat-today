# -*- coding: utf-8 -*-
"""
家庭味觉画像：记录 👍/👎 反馈，沉淀口味 / 食材 / 菜品偏好，反哺推荐打分。

数据存在 data/profile.json（纯本地）。画像只作用于"软约束打分"阶段，
不改变忌口 / 过敏等硬约束。
"""
import json
from datetime import datetime
from pathlib import Path

from .rules import substantive_ingredients
from ..paths import data_file

PROFILE_FILE = data_file("profile.json")

DEFAULT_PROFILE = {
    "dish_likes": {},        # recipe id -> 累计分（喜欢 +1 / 不喜欢 -1）
    "dish_names": {},        # recipe id -> 菜名
    "taste_scores": {},      # 口味 -> 累计分
    "ingredient_scores": {}, # 实质主料 -> 累计分
    "history": [],           # 最近反馈（倒序，最多 200 条）
    "count": 0,
}


def load_profile() -> dict:
    if PROFILE_FILE.exists():
        try:
            data = json.load(open(PROFILE_FILE, encoding="utf-8"))
            # 合并默认字段，防止旧文件缺字段
            out = dict(DEFAULT_PROFILE)
            out.update(data)
            return out
        except Exception:
            pass
    return dict(DEFAULT_PROFILE)


def save_profile(data: dict) -> None:
    PROFILE_FILE.parent.mkdir(parents=True, exist_ok=True)
    json.dump(data, open(PROFILE_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


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
        # 只沉淀实质主料（过滤盐/糖/油/葱姜蒜等调料）
        for name in substantive_ingredients([ing.get("name", "").strip() for ing in recipe.get("ingredients", [])]):
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
        """画像对一道菜的加分 / 减分（软约束，力度弱于硬约束）。"""
        s = 0.0
        s += self.data["dish_likes"].get(recipe.get("id"), 0) * 2.0
        for t in recipe.get("taste") or []:
            s += self.data["taste_scores"].get(t, 0) * 0.5
        for ing in recipe.get("ingredients") or []:
            name = ing.get("name", "").strip()
            if name:
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
