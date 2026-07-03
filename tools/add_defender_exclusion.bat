@echo off
chcp 65001 >nul
REM ============================================================
REM  원천징수 자동화 - Windows Defender 예외 추가 도우미
REM  사용법: 이 파일을 우클릭하여 "관리자 권한으로 실행" 하세요.
REM  (설치/업데이트 시 자동으로 실행되지 않습니다 - 사용자가 직접 실행)
REM ============================================================

REM 관리자 권한 확인
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo [오류] 이 스크립트는 관리자 권한이 필요합니다.
    echo        이 파일을 우클릭하여 "관리자 권한으로 실행" 을 선택하세요.
    echo.
    pause
    exit /b 1
)

set "INSTALL_DIR=%LOCALAPPDATA%\원천징수자동화"
set "DATA_DIR=%LOCALAPPDATA%\원천징수자동화-data"

echo.
echo == 원천징수 자동화 - Windows Defender 예외 추가 ==
echo.
echo [1/3] 설치 폴더 예외 추가: %INSTALL_DIR%
powershell -NoProfile -ExecutionPolicy Bypass -Command "Add-MpPreference -ExclusionPath '%INSTALL_DIR%'"
echo [2/3] 데이터 폴더 예외 추가: %DATA_DIR%
powershell -NoProfile -ExecutionPolicy Bypass -Command "Add-MpPreference -ExclusionPath '%DATA_DIR%'"
echo [3/3] 프로세스 예외 추가: 원천징수자동화.exe
powershell -NoProfile -ExecutionPolicy Bypass -Command "Add-MpPreference -ExclusionProcess '원천징수자동화.exe'"
echo.
echo [완료] Windows Defender 예외 추가가 끝났습니다.
echo        이제 프로그램(원천징수 자동화)을 다시 실행해 보세요.
echo.
echo 주의: 회사 PC에서 "이 작업이 차단되었습니다" 라는 메시지가 뜨면
echo        회사 보안(EDR) 정책 때문입니다. 이 경우 Windows 보안 앱에서
echo        수동으로 제외를 추가하거나 사내 보안 담당자에게 문의하세요.
echo.
pause
