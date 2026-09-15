@echo off
chcp 65001 >nul
title 工艺包安全风险辨识系统 v0.3.1
cd /d "%~dp0"
echo ==================================================
echo    工艺包安全风险辨识系统   Demo v0.3.1
echo ==================================================
echo.

if not exist ".venv\Scripts\python.exe" (
  echo [首次运行] 创建虚拟环境并安装依赖，请稍候...
  py -m venv .venv
  if errorlevel 1 ( echo 未找到 Python 启动器 ^"py^"，请先安装 Python 3.10+ 后重试 & pause & exit /b 1 )
  ".venv\Scripts\python.exe" -m pip install --upgrade pip -q
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
  if errorlevel 1 ( echo 依赖安装失败，请检查网络后重试 & pause & exit /b 1 )
)

echo [启动] 服务地址： http://127.0.0.1:8000
echo [提示] 关闭本窗口或按 Ctrl+C 即停止服务
echo.
start "" http://127.0.0.1:8000
".venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000
pause
