@echo off
chcp 65001 >nul
cd /d "%~dp0"
python analyze.py systems --limit 30
echo.
echo 主要国家体系表已生成在 reports 文件夹里。
pause
