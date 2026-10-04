# -*- coding: utf-8 -*-
"""用 GitHub API 下载指定 skill 目录到全局 skills 目录（避免 git 直连被墙）。"""
import json
import os
import sys

import httpx

HOME = os.path.expanduser("~")
DEST_ROOT = os.path.join(HOME, ".pi", "agent", "skills")

# (repo, branch, 源目录前缀, 目标 skill 名)
WANTED = [
    ("emilkowalski/skills", "main", "skills/apple-design", "apple-design"),
    ("emilkowalski/skills", "main", "skills/improve-animations", "improve-animations"),
    ("anthropics/skills", "main", "skills/skill-creator", "skill-creator"),
    ("anthropics/skills", "main", "skills/frontend-design", "frontend-design"),
]


def get_tree(repo, branch):
    r = httpx.get(f"https://api.github.com/repos/{repo}/git/trees/{branch}?recursive=1",
                  timeout=60, headers={"Accept": "application/vnd.github+json"})
    r.raise_for_status()
    data = r.json()
    if data.get("truncated"):
        print(f"⚠️ {repo} 的 tree 被截断，可能不全")
    return [t for t in data.get("tree", []) if t["type"] == "blob"]


def main():
    os.makedirs(DEST_ROOT, exist_ok=True)
    for repo, branch, prefix, dest_name in WANTED:
        print(f"\n=== {repo} -> {dest_name} ===")
        try:
            tree = get_tree(repo, branch)
            files = [t for t in tree if t["path"].startswith(prefix + "/")]
            if not files:
                print("  [FAIL] 未找到文件")
                continue
            dest_dir = os.path.join(DEST_ROOT, dest_name)
            os.makedirs(dest_dir, exist_ok=True)
            n = 0
            for f in files:
                rel = f["path"][len(prefix) + 1:]  # 去掉前缀
                dst = os.path.join(dest_dir, rel)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                url = f"https://raw.githubusercontent.com/{repo}/{branch}/{f['path']}"
                try:
                    content = httpx.get(url, timeout=60).content
                    with open(dst, "wb") as fh:
                        fh.write(content)
                    n += 1
                except Exception as e:
                    print(f"  [WARN] 下载失败 {rel}: {str(e)[:60]}")
            print(f"  [OK] 下载 {n} 个文件 -> {dest_dir}")
        except Exception as e:
            print(f"  [FAIL] {str(e)[:100]}")


if __name__ == "__main__":
    main()
