@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================
echo   今天吃什么 - 打包成 exe
echo ============================================
echo [1/2] 安装打包工具 PyInstaller...
python -m pip install pyinstaller -q

echo [2/2] 打包中（首次约 1-3 分钟，请耐心等待）...
python -m PyInstaller --noconfirm --clean --onefile ^
  --name "今天吃什么" ^
  --add-data "frontend;frontend" ^
  --add-data "data/recipes.json;data" ^
  --add-data "data/food_composition.json;data" ^
  --exclude-module langgraph ^
  --exclude-module langchain ^
  --exclude-module langchain_core ^
  --exclude-module langgraph_sdk ^
  --exclude-module matplotlib ^
  --exclude-module pandas ^
  --exclude-module numpy ^
  --exclude-module PIL ^
  --exclude-module scipy ^
  run.py

echo.
echo ✅ 完成！双击 dist\今天吃什么.exe 即可使用
echo    （首次双击会自动打开浏览器 http://127.0.0.1:8000）
pause
