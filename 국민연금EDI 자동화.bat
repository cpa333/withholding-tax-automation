@echo off
chcp 65001 >nul
cd /d "%~dp0"
python -u src\automation\nps\nps_auto_cdp.py
pause
