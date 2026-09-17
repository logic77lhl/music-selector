@echo off
setlocal EnableDelayedExpansion
title Music Selector - 本地音乐快速试听与选歌工具
cd /d "%~dp0"

echo ============================================================
echo   Music Selector - 本地音乐快速试听与选歌工具
echo ============================================================
echo.

rem ---------- 1. 检查 Python ----------
where python >nul 2>nul
if errorlevel 1 (
    echo [错误] 未找到 Python，请先安装 Python 3.8+ 并勾选 Add to PATH
    pause
    exit /b 1
)
python --version

rem ---------- 2. 安装/检查依赖 ----------
python -c "import mutagen" >nul 2>nul
if errorlevel 1 (
    echo.
    echo [安装] 首次运行，正在安装依赖 mutagen ...
    python -m pip install mutagen
    if errorlevel 1 (
        echo [错误] 依赖安装失败，请手动执行: python -m pip install mutagen
        pause
        exit /b 1
    )
)

rem ---------- 3. 索引已存在则直接启动 ----------
if exist "data\library.json" goto start_server

rem ---------- 4. 无索引：交互式输入音乐目录 ----------
echo.
echo [提示] 尚未建立音乐库索引。
set /p MUSIC_DIR=请输入音乐目录路径（例如 D:\Music）:
set "MUSIC_DIR=!MUSIC_DIR:"=!"
if "!MUSIC_DIR!"=="" (
    echo [错误] 未输入目录，无法建立索引。
    pause
    exit /b 1
)
echo.
echo [扫描] 正在生成索引，首次扫描几千首约需 1~2 分钟...
python analyze_music.py "!MUSIC_DIR!"
if errorlevel 1 (
    echo [错误] 索引生成失败，请检查目录路径。
    pause
    exit /b 1
)
echo.

rem ---------- 5. 启动服务 ----------
:start_server
echo [启动] 正在启动本地服务，浏览器将自动打开 ...
echo        访问地址: http://127.0.0.1:5000
echo        按 Ctrl+C 停止服务后关闭本窗口
echo.
python app.py

echo.
echo 服务已停止。
pause
