@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

echo ══════════════════════════════════════════════
echo   원천징수 자동화 — 초기 환경 설정
echo ══════════════════════════════════════════════
echo.

:: ── 1. 관리자 권한 확인 ──────────────────────────
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [!] 관리자 권한이 필요합니다.
    echo     우클릭 → "관리자 권한으로 실행"을 선택해 주세요.
    echo.
    pause
    exit /b 1
)
echo [✓] 관리자 권한 확인
echo.

:: ── 2. Python 설치 확인 ──────────────────────────
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [✗] Python이 설치되어 있지 않습니다.
    echo.
    echo     Microsoft Store에서 "Python 3.12"를 설치해 주세요:
    echo     https://apps.microsoft.com/detail/9ncvdn91xzqp
    echo.
    echo     또는 https://www.python.org/downloads/ 에서 다운로드 후
    echo     설치 시 "Add Python to PATH" 체크박스를 반드시 선택하세요.
    echo.
    pause
    exit /b 1
)

:: 버전 확인 (3.10+)
for /f "tokens=2 delims= " %%v in ('python --version 2^>^&1') do set PYVER=%%v
for /f "tokens=1,2 delims=." %%a in ("%PYVER%") do (
    set PYMAJOR=%%a
    set PYMINOR=%%b
)
if %PYMAJOR% lss 3 (
    echo [✗] Python 3.10 이상이 필요합니다. 현재: %PYVER%
    pause
    exit /b 1
)
if %PYMAJOR% equ 3 if %PYMINOR% lss 10 (
    echo [✗] Python 3.10 이상이 필요합니다. 현재: %PYVER%
    pause
    exit /b 1
)
echo [✓] Python %PYVER% 확인
echo.

:: ── 3. pip 업그레이드 ─────────────────────────────
echo [..] pip 업그레이드 중...
python -m pip install --upgrade pip >nul 2>&1
echo [✓] pip 업그레이드 완료
echo.

:: ── 4. 패키지 설치 ────────────────────────────────
echo [..] Python 패키지 설치 중...
pip install -r "%~dp0requirements.txt"
if %errorlevel% neq 0 (
    echo [✗] 패키지 설치 실패. 위 에러 메시지를 확인하세요.
    pause
    exit /b 1
)
echo [✓] 패키지 설치 완료
echo.

:: ── 5. Playwright 브라우저 설치 ───────────────────
echo [..] Playwright Chromium 브라우저 설치 중...
echo     (최초 설치 시 약 150MB 다운로드)
playwright install chromium
if %errorlevel% neq 0 (
    echo [✗] Playwright 브라우저 설치 실패.
    pause
    exit /b 1
)
echo [✓] Playwright Chromium 설치 완료
echo.

:: ── 6. Chrome 설치 확인 ───────────────────────────
set CHROME_FOUND=0

if exist "C:\Program Files\Google\Chrome\Application\chrome.exe" set CHROME_FOUND=1
if exist "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe" set CHROME_FOUND=1
if exist "%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe" set CHROME_FOUND=1

if %CHROME_FOUND% equ 0 (
    echo [!] Google Chrome이 설치되어 있지 않습니다.
    echo     다음 페이지에서 설치해 주세요:
    echo     https://www.google.com/chrome/
    echo.
    echo     설치 후 이 스크립트를 다시 실행하세요.
    pause
    exit /b 1
)
echo [✓] Google Chrome 설치 확인
echo.

:: ── 완료 ──────────────────────────────────────────
echo ══════════════════════════════════════════════
echo   환경 설정 완료!
echo   다음 명령으로 프로그램을 실행하세요:
echo     python gui_main.py
echo ══════════════════════════════════════════════
pause
