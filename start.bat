@echo off
chcp 65001 >nul
cd /d "%~dp0"
title 今天吃什么 - 家庭餐桌助手

where python >nul 2>nul
if errorlevel 1 (
    echo [错误] 没有检测到 Python，请先到 https://www.python.org/downloads/ 安装
    pause
    exit /b
)

echo ============================================
echo   今天吃什么 · 家庭餐桌助手
echo ============================================
echo.
echo [1/2] 安装依赖（首次需要 1-2 分钟）...
pip install -r requirements.txt -q

echo [2/2] 启动服务，浏览器即将打开...
start "" /b python -m uvicorn app.main:app --host 127.0.0.1 --port 8000

timeout /t 3 /nobreak >nul
start "" http://127.0.0.1:8000

echo.
echo ✅ 已启动！浏览器会打开 http://127.0.0.1:8000
echo    关闭这个黑色窗口，服务就会停止。
echo.
pause
