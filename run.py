# -*- coding: utf-8 -*-
"""启动入口：起服务 + 自动打开浏览器。

开发：python run.py
打包：build.bat 用 PyInstaller 打成 exe，双击即可用。
"""
import threading
import webbrowser
import time

import uvicorn
from app.main import app


def open_browser():
    time.sleep(1.2)
    webbrowser.open("http://127.0.0.1:8000")


if __name__ == "__main__":
    threading.Thread(target=open_browser, daemon=True).start()
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")
