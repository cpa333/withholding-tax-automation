@echo off
chcp 65001 >nul
cd /d "%~dp0"
python -u src\automation\nhis\nhis_edi_auto_cdp.py
pause
