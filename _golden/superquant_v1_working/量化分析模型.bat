@echo off
chcp 65001 >nul
title 五维超脑控制台
cd /d "%~dp0"

echo ==========================================
echo  正在启动五维超脑...
echo ==========================================

:: 1. 核心检查：确认环境位置
if not exist "env\Scripts\python.exe" (
    echo [严重错误] 找不到 env 文件夹！
    echo 请确认 env 文件夹和本脚本在同一个目录下。
    pause
    exit
)

:: 2. 强制补全所有依赖 (绕过 pip.exe，直接用 python 调用模块，这是最稳的方法)
echo 正在检查并补全关键组件 (OpenAI/Matplotlib)...
.\env\Scripts\python.exe -m pip install openai matplotlib pandas streamlit plotly akshare backtrader -i https://pypi.tuna.tsinghua.edu.cn/simple

:: 3. 启动程序 (开启浏览器)
echo 正在拉起控制台...
.\env\Scripts\python.exe -m streamlit run app.py --global.developmentMode=false --server.headless=false

:: 4. 崩溃保护 (如果程序退出，不关闭窗口以便查看报错)
if %errorlevel% neq 0 (
    echo.
    echo ----------------------------------------------------
    echo [程序异常退出] 请截图上方红色报错信息发送给开发者
    echo ----------------------------------------------------
    pause
)