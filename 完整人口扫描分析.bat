@echo off
chcp 65001 >nul
cd /d "%~dp0"
python analyze.py report --full
echo.
echo 完整报告已生成在 reports 文件夹里。
echo 这个模式会扫描人口明细，存档很大时可能需要几分钟。
pause
