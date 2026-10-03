# -*- coding: utf-8 -*-
"""
HowToCook Markdown -> 结构化菜谱 JSON 解析器
输入: data/raw/md/*.md + data/raw/md_index.json
输出: data/recipes.json
"""
import json
import os
import re

CATEGORY_CN = {
    "aquatic": "水产",
    "breakfast": "早餐",
    "condiment": "调料",
    "dessert": "甜点",
    "drink": "饮品",
    "meat_dish": "肉菜",
    "semi-finished": "半成品",
    "soup": "汤",
    "staple": "主食",
    "vegetable_dish": "素菜",
}

# 用于把"必备原料和工具"里的工具项和原料项分开
TOOL_KEYWORDS = [
    "锅", "刀", "烤箱", "面包机", "微波炉", "空气炸锅", "蒸锅", "高压锅",
    "打蛋器", "案板", "铲", "勺", "碗", "盆", "电子秤", "温度计",
    "料理机", "破壁机", "电饭煲", "冰箱", "搅拌机", "烤盘", "模具",
    "漏勺", "蒸笼", "滤网", "保鲜膜", "锡纸", "硅胶", "厨具",
]


def clean_inline(text):
    """去掉行内 markdown 标记（`code`、**bold**、链接等）"""
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"\*\*([^*]*)\*\*", r"\1", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    return text.strip()


def extract_minutes(text):
    """从描述文本提取耗时（分钟）。支持 '约 X 分钟'、'X 小时'、'X 小时 Y 分钟'。"""
    if not text:
        return None
    total = 0
    m = re.search(r"(\d+)\s*小时[半零-]*?\s*(\d+)?\s*分钟?", text)
    if m:
        total += int(m.group(1)) * 60
        if m.group(2):
            total += int(m.group(2))
        return total if total else None
    m2 = re.search(r"(\d+)\s*分钟", text)
    if m2:
        return int(m2.group(1))
    m3 = re.search(r"(\d+)\s*小时", text)
    if m3:
        return int(m3.group(1)) * 60
    return None


def strip_optional_marker(name):
    """把 '糖（可选）' 拆成 (糖, True) 或 '盐' -> (盐, False)"""
    m = re.search(r"([（(]可选[)）])", name)
    optional = bool(m)
    clean = re.sub(r"[（(]可选[)）]", "", name).strip()
    return clean, optional


def parse_header(lines):
    """返回 (菜名, 描述, 难度, 卡路里)。描述只取标题后、第一个 ## 前的正文。"""
    name = ""
    desc_lines = []
    difficulty = None
    calories = None
    for line in lines:
        s = line.strip()
        if s.startswith("## "):
            break  # 进入 section，停止收集描述
        if s.startswith("# ") and not name:
            name = re.sub(r"的做法$", "", s[2:].strip())
            continue
        if not name:
            continue
        if s.startswith("预估烹饪难度"):
            m = re.search(r"([★]+)", s)
            difficulty = len(m.group(1)) if m else None
            continue
        if s.startswith("预估卡路里"):
            m = re.search(r"(\d+)", s)
            calories = int(m.group(1)) if m else None
            continue
        if s and not s.startswith(">") and not s.startswith("!") and not s.startswith("!["):
            desc_lines.append(s)
    return name, " ".join(desc_lines).strip(), difficulty, calories


def split_sections(lines):
    """按 ## 标题切分，返回 {section_name: [lines]}，保留顺序"""
    sections = []
    current_name = None
    current_lines = []
    for line in lines:
        if line.strip().startswith("## "):
            if current_name is not None:
                sections.append((current_name, current_lines))
            current_name = line.strip()[3:].strip()
            current_lines = []
        else:
            current_lines.append(line)
    if current_name is not None:
        sections.append((current_name, current_lines))
    return sections


def parse_list_items(lines):
    """解析 - / 1. 列表，返回 [(indent, text)]，text 已去行内标记"""
    items = []
    for line in lines:
        raw = line.rstrip("\n")
        if not raw.strip():
            continue
        m = re.match(r"^(\s*)([-+*]|\d+[.、])\s+(.*)$", raw)
        if m:
            indent = len(m.group(1))
            items.append((indent, clean_inline(m.group(3))))
    return items


def parse_ingredients_tools(section_lines):
    """解析'必备原料和工具' -> (ingredients, tools)"""
    ingredients = []
    tools = []
    for _, text in parse_list_items(section_lines):
        name, optional = strip_optional_marker(text)
        name = re.split(r"[（(]", name)[0].strip()  # 去掉括号里的说明
        if not name:
            continue
        if any(kw in name for kw in TOOL_KEYWORDS):
            tools.append(name)
        else:
            ingredients.append({"name": name, "optional": optional})
    return ingredients, tools


def split_name_amount(text):
    """把 '西红柿 = 1 个（约 180g） * 份数' 拆成 (西红柿, 1 个...)"""
    m = re.split(r"[=：:]\s*", text, maxsplit=1)
    if len(m) == 2 and m[0].strip():
        return m[0].strip(), m[1].strip()
    # 无等号：以第一个数字为界
    m2 = re.search(r"\d", text)
    if m2 and m2.start() > 1:
        left = text[:m2.start()].rstrip("（( ")
        return left, text[m2.start():].strip()
    return text.strip(), ""


def parse_calculation(section_lines):
    """解析'计算'部分，返回 [{name, amount, optional, group}]，保留 ### 子标题为 group"""
    result = []
    current_group = None
    for line in section_lines:
        s = line.strip()
        if s.startswith("### "):
            current_group = s[4:].strip()
            continue
        m = re.match(r"^\s*[-+*]\s+(.*)$", line)
        if m:
            text = clean_inline(m.group(1))
            name, optional = strip_optional_marker(text)
            ing_name, amount = split_name_amount(name)
            result.append({
                "name": ing_name,
                "amount": amount,
                "optional": optional,
                "group": current_group,
            })
    return result


def parse_operation(section_lines):
    """解析'操作'部分，返回 [{group, steps: [str]}]，子步骤拼入父步骤"""
    groups = []
    current_group = None
    current_steps = []  # list of {text, sub:[str]}
    for line in section_lines:
        s = line.strip()
        if not s:
            continue
        if s.startswith("### "):
            if current_group is not None or current_steps:
                groups.append({"group": current_group, "steps": current_steps})
            current_group = s[4:].strip()
            current_steps = []
            continue
        # 有序步骤
        m = re.match(r"^(\d+)[.、]\s*(.*)$", s)
        if m:
            current_steps.append({"text": clean_inline(m.group(2)), "sub": []})
            continue
        # 无序子步骤（缩进的 - ）
        m2 = re.match(r"^[-+*]\s*(.*)$", s)
        if m2:
            sub_text = clean_inline(m2.group(1))
            if current_steps:
                current_steps[-1]["sub"].append(sub_text)
            else:
                current_steps.append({"text": sub_text, "sub": []})
            continue
        # 其他纯文本：附加到当前组最后一步的 sub，或作为独立说明
        if s and not s.startswith(">") and not s.startswith("!"):
            if current_steps:
                current_steps[-1]["sub"].append(clean_inline(s))
    if current_group is not None or current_steps:
        groups.append({"group": current_group, "steps": current_steps})
    # 去掉空组
    return [g for g in groups if g["steps"]]


def parse_extra(section_lines):
    """解析'附加内容' -> (tips, video_links)"""
    tips = []
    links = []
    for line in section_lines:
        s = line.strip()
        m = re.search(r"https?://[^\s)\]]+", s)
        if m:
            links.append(m.group(0))
            continue
        item = re.sub(r"^[-+*]\s*", "", s)
        item = clean_inline(item)
        if item and not item.startswith("如果您遵循"):
            tips.append(item)
    return tips, links


def parse_file(path, source_path):
    with open(path, encoding="utf-8") as f:
        text = f.read()
    lines = text.split("\n")
    name, desc, difficulty, calories = parse_header(lines)
    sections = split_sections(lines)
    sec_map = {n: l for n, l in sections}

    ingredients, tools = [], []
    if "必备原料和工具" in sec_map:
        ingredients, tools = parse_ingredients_tools(sec_map["必备原料和工具"])

    calculations = []
    if "计算" in sec_map:
        calculations = parse_calculation(sec_map["计算"])

    steps = []
    if "操作" in sec_map:
        steps = parse_operation(sec_map["操作"])

    tips, video_links = [], []
    if "附加内容" in sec_map:
        tips, video_links = parse_extra(sec_map["附加内容"])

    return {
        "name": name,
        "description": desc,
        "difficulty": difficulty,
        "calories_kcal": calories,
        "estimated_minutes": extract_minutes(desc),
        "ingredients": ingredients,
        "tools": tools,
        "calculations": calculations,
        "steps": steps,
        "tips": tips,
        "video_links": video_links,
        "source": "HowToCook",
        "source_path": source_path,
    }


def main():
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    md_dir = os.path.join(base, "data", "raw", "md")
    index = json.load(open(os.path.join(base, "data", "raw", "md_index.json"), encoding="utf-8"))

    recipes = []
    skipped = []
    for fname in sorted(index.keys()):
        source_path = index[fname]
        parts = source_path.split("/")
        category = parts[1] if len(parts) > 1 else "other"
        if category == "template":
            skipped.append(source_path)
            continue
        r = parse_file(os.path.join(md_dir, fname), source_path)
        r["id"] = f"r{len(recipes):04d}"
        r["category"] = category
        r["category_cn"] = CATEGORY_CN.get(category, category)
        # 粗分荤素（后续 LLM 精修）
        if category in ("meat_dish", "aquatic"):
            r["dish_type"] = "荤"
        elif category in ("vegetable_dish",):
            r["dish_type"] = "素"
        elif category in ("staple",):
            r["dish_type"] = "主食"
        elif category in ("soup",):
            r["dish_type"] = "汤"
        else:
            r["dish_type"] = "其他"
        recipes.append(r)

    out = os.path.join(base, "data", "recipes.json")
    json.dump(recipes, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"解析完成: {len(recipes)} 道菜 -> {out}")
    if skipped:
        print(f"跳过 template 等: {len(skipped)} 个")

    # 统计质量
    no_cal = sum(1 for r in recipes if r["calories_kcal"] is None)
    no_diff = sum(1 for r in recipes if r["difficulty"] is None)
    no_ing = sum(1 for r in recipes if not r["ingredients"])
    no_step = sum(1 for r in recipes if not r["steps"])
    print(f"缺卡路里: {no_cal}, 缺难度: {no_diff}, 缺原料: {no_ing}, 缺步骤: {no_step}")


if __name__ == "__main__":
    main()
