@echo off
REM 在 Windows 上打包：双击或命令行运行
REM 需要先装 Python 3.10+，然后 pip install pyinstaller numpy
chcp 65001 >nul
cd /d "%~dp0"
python build_app.py
echo.
echo 产物在 dist\扑克复盘台.exe
pause
