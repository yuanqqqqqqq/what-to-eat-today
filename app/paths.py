# -*- coding: utf-8 -*-
"""路径统一：区分只读资源（打包进 _MEIPASS）和可写数据（exe 旁边）。

PyInstaller 打包后：
- 只读资源（frontend、内置菜谱/成分表）在 sys._MEIPASS（临时解压目录）。
- 可写数据（用户菜谱/价格/常备/设置/画像）在 exe 旁边的 data/ 目录。
"""
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def resource_dir() -> Path:
    """只读资源目录（frontend、内置菜谱/成分表）。"""
    if is_frozen():
        return Path(sys._MEIPASS)
    return _PROJECT_ROOT


def data_dir() -> Path:
    """可写数据目录。打包后放在 exe 旁边，保证可写。"""
    d = (Path(sys.executable).parent if is_frozen() else _PROJECT_ROOT) / "data"
    d.mkdir(parents=True, exist_ok=True)
    return d


def resource(rel: str) -> Path:
    return resource_dir() / rel


def data_file(rel: str) -> Path:
    return data_dir() / rel
