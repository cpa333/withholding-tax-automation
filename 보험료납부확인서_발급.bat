@echo off
chcp 65001 >nul
echo ========================================
echo   보험료 납부확인서 자동 발급
echo ========================================
echo.

cd /d "%~dp0"
python -u src\automation\nhis\nhis_auto_cdp.py

echo.
pause
