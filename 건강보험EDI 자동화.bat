@echo off
chcp 65001 >nul
cd /d "%~dp0"
rem 병렬 실행용 CDP 포트. 원복(단일)하려면 아래 줄을 지우세요.
set WTAX_CDP_PORT=9224
python -u src\automation\nhis\nhis_edi_auto_cdp.py
pause
