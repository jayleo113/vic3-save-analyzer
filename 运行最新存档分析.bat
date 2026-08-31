@echo off
chcp 65001 >nul
cd /d "%~dp0"
python analyze.py report
echo.
echo 报告已生成在 reports 文件夹里。
echo 如果上面提示未找到 python，请安装 Python 或把 python 加入 PATH。
pause
