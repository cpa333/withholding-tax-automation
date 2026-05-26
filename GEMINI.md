# Withholding Tax Automation

This project automates withholding tax processes by controlling external platforms (Health Insurance Corporation, WEHAGO, Hometax) and is delivered as a Windows executable.

## Project Overview
The application is a Python-based Windows automation tool designed to streamline tax-related tasks across multiple Korean platforms.

### Core Modules
1. **Health Insurance Corporation Control (공단 사이트 제어):** Automation of tasks on the National Health Insurance platform.
2. **WEHAGO Control (WEHAGO 제어):** Automation of data entry or retrieval from the WEHAGO accounting platform.
3. **Hometax Control (홈택스 제어):** Automation of withholding tax filing via file conversion on the National Tax Service (Hometax) platform.

## Architecture & Tech Stack
- **Language:** Python 3.10+
- **Platform:** Windows (.exe via PyInstaller or Nuitka)
- **Automation:** Playwright (CDP 연결 모드, `--remote-debugging-port=9223`)
- **PDF:** PyMuPDF (fitz)
- **Excel:** openpyxl
- **OS 제어:** pywinauto (WEHAGO PrintDialog Windows Forms 앱 제어)
- **Browser:** Chrome (CDP, subprocess.Popen으로 실행 — Playwright launch 사용 금지)

## Building and Running
- **Development:** `python main.py`
- **Packaging:** *TODO: Add specific PyInstaller/Nuitka command for generating .exe*

## Development Conventions
- **Module Separation:** Each control module (공단, WEHAGO, 홈택스) should be isolated in its own package/script.
- **Error Handling:** Robust exception handling for network timeouts and UI changes on external sites.
- **Security:** Sensitive credentials must be handled securely (e.g., encrypted local storage or user input, never hardcoded).

## Directory Structure
- `src/`
    - `automation/`
        - `nhis/` (공단) — 건강보험공단 자동화
        - `nps/` — 국민연금 EDI 자동화
        - `wehago/` — WEHAGO 급여 자동화
        - `hometax/` — 홈택스 원천세 신고 자동화
    - `ui/`
    - `utils/`
- `results/` — 다운로드/변환된 엑셀 파일
- `build/`
- `main.py`

## Critical: Chrome Launch Method

**반드시 `subprocess.Popen`으로 Chrome을 실행하고 `connect_over_cdp`로 연결할 것.**

`playwright.chromium.launch()`로 실행하면 `download.save_as()`가 **0바이트 파일**을 반환함.
Playwright의 `launch()`는 자체 다운로드 인터셉션을 설정하여 CDP 연결 시 스트림 캡처가 충돌하기 때문.
subprocess로 실행하면 Chrome이 독립적으로 다운로드를 처리하고 Playwright는 CDP로만 연결하여 정상 작동.

### CDP 포트: 9223 (9222 사용 금지)

WEHAGO Print 서비스(WehagoPrint.exe, WehagoAgent.exe 등)가 9222 포트를 점유/차단함.
반드시 `--remote-debugging-port=9223`을 사용할 것.

```python
# 올바른 방식
subprocess.Popen([chrome_path, "--remote-debugging-port=9223", "--user-data-dir=...", "--start-maximized", url])
browser = await playwright.chromium.connect_over_cdp("http://localhost:9223")

# 잘못된 방식 (WEHAGO 서비스가 포트 차단)
--remote-debugging-port=9222

# 잘못된 방식 (다운로드 0바이트)
browser = await playwright.chromium.launch(headless=False, args=["--remote-debugging-port=9223"])
```

### Chrome 종료 이슈

`taskkill /F /IM chrome.exe`로 종료되지 않는 경우가 빈번함.
WEHAGO 백그라운드 서비스가 Chrome을 유지/재실행하는 것으로 추정.
종료 안 되면 사용자에게 직접 브라우저 창을 닫으라고 요청 후 `tasklist`로 확인.

### WEHAGO 메인 "전체" 탭 필수

기본 탭이 "T edge 사용"이면 수임처 카드가 0개.
메인 페이지 진입 후 반드시 "전체" 탭(`ul.main_tab_bx` 첫 번째 `li > button`) 클릭 필요.

## WEHAGO Automation Flow (`wehago_auto_cdp.py`)

1. **Chrome 실행** — CDP 디버깅 모드로 Chrome 실행 (user profile junction 사용, 기존 Chrome 종료 후 2초 대기)
2. **로그인** — WEHAGO 메인에서 로그인 상태 확인 (Human-in-the-loop), `bring_to_front()`로 WEHAGO 탭 활성화
3. **수임처 급여 이동** — 급여 버튼 → SmartA URL 캡처
4. **급여자료입력** — SWSA0101 메뉴 이동 → 간이세액 개정 안내 모달 X 닫기
5. **급여+상여 선택** — 구분 드롭다운에서 `급여+상여` 선택
6. **복사후 재계산** — 모달 있으면 복사후 재계산 → 취소, 없으면 스킵
7. **엑셀 다운로드** — `#collect` 드롭다운 (Playwright `locator.click()`) → 엑셀 내려받기
8. **업로드 변환** — 다운로드 엑셀 헤더 평탄화, 사원코드 4자리 패딩
9. **마감 상태 확인** — 네비게이션 바 버튼 텍스트로 판별:
   - "해제" → 마감 완료 (급여 확정) → 엑셀 업로드 SKIP
   - "완료"/"마감" → 미마감 → 엑셀 업로드 진행
10. **엑셀 업로드** (미마감 시에만 실행):
    - ① 행1 선택 — `offsetParent` + `th.click()` (DPR 무관)
    - ② 엑셀제목설정 → 제목설정 확인 모달
    - 확인 버튼 — 다이얼로그 내부에서만 탐색 (해상도 무관)
    - 후속 1/5: `#confirm` 확인
    - 후속 2/5: "연결되지 않은 사원" 확인
    - 후속 3/5: "삭제후 업로드" → dry_run=취소, 실운영=확인
    - 후속 4/5: dry_run 시 "변환이 취소" 확인, 실운영 시 완료 확인
11. **PDF 다운로드** — OS 레벨 PrintDialog 제어 (pywinauto):
    - `#print` 버튼 → 일괄출력 클릭 → WEHAGO PrintDialog (`Duzon - PrintDialog`) 실행
    - 인쇄형태 드롭다운에서 항목 선택 (기본: `급여명세(사원당 한장)`)
    - PDF 저장 버튼 → Windows "다른 이름으로 저장" 대화상자 → `results/` 에 저장
    - PrintDialog 종료 (`btnClose`)
    - 모든 OS 제어는 `auto_id` + `control_type` + `CurrentName` 기반 (좌표 독립)
12. **수임처 변경** — 메뉴 옵션 4로 WEHAGO 메인 복귀 → 재검색 → 다른 수임처 전환 (재시작 불필요)

## Resolution-Independent Fixes

| 이슈 | 파일 | 수정 |
|------|------|------|
| CDP 좌표 빗나감 | `wehago_auto_cdp.py` | `Input.dispatchMouseEvent` → `offsetParent` + `th.click()` |
| rect.top > 700 실패 | `wehago_auto_cdp.py` | `rect.top > 700` → 다이얼로그 내부에서만 '확인' 탐색 |
| 하드코딩 스크롤 | `hometax_auto_cdp.py` | `scrollTo(0, 400)` → `scrollIntoView({block: 'center'})` |
| 모달 가시성 | `hometax_auto_cdp.py` | `rect.width === 0` → `offsetParent === null` |
| PrintDialog 제어 | `wehago_auto_cdp.py` | pywinauto `auto_id` + `control_type` + `CurrentName` (좌표 미사용) |
| #collect 드롭다운 미작동 | `_common.py` | JS `btn.click()` → Playwright `locator.click()` (합성 이벤트 문제) |
| 마감 상태 엑셀 업로드 | `run_swsa0101.py` | '해제' 버튼 감지 → 업로드 SKIP, '완료'/'마감' → 진행 |

## NHIS Session Extension Handling

공단 포털(medicare.nhis.or.kr)은 약 30분 비활동 시 세션 만료, **5분 전** "로그인 상태 연장" 팝업 등장.

### 자동 처리 (`auto_session_extend`)
- `nhis_auto_cdp.py`의 `run()` 실행 시 **백그라운드 태스크**로 30초 간격 팝업 감시
- "연장"/"시간연장" 텍스트 버튼 감지 시 자동 클릭 → 세션 유지
- 자동화 완료 후 태스크 취소

### 개발 테스트 (`trigger_session_popup_soon`)
세션 만료를 기다릴 필요 없이 팝업을 강제 트리거하여 테스트 가능:
```python
# CDP로 연결 후 호출
await trigger_session_popup_soon(page, seconds=10)  # 10초 후 팝업 등장
```
동작 방식: eXBuilder6의 `confirmExtensionTimerCallback()` 또는 `comLib.checkSession()` 을 setTimeout으로 지정 초 후 호출.

## NPS EDI Automation Flow (`nps_auto_cdp.py`)

국민연금 EDI (edi.nps.or.kr) — **Nexacro** 기반 엔터프라이즈 웹 프레임워크.

### 핵심: Nexacro 그리드 제어

Nexacro는 일반 DOM click/playwright click을 **무시**함. 이벤트를 직접 dispatch 해야 함:
- **행 선택:** `dblclick` 이벤트 (1차 click + 2차 click + dblclick 순차 발생)
- **셀 ID 패턴:** `{gridId}.body.gridrow_{row}.cell_{row}_{col}`
- **텍스트 매칭:** 행 인덱스보다 텍스트 기반 검색이 정확 (DOM 순서 ≠ 시각적 순서)

### 플로우

1. **Chrome 실행** — CDP 디버깅 모드 (포트 9223, WEHAGO와 공유)
2. **로그인 대기** — 공동인증서 로그인은 Human-in-the-loop
3. **Nexacro 메인 진입** — `edi.nps.or.kr/nexacro/index.html` 로 리디렉트
4. **사업장 선택** — 업무대행서비스 → 위탁사업장 → 그리드에서 더블클릭
5. **(이후 단계 개발 예정)** — 신고신청, 증명서 발급 등

### 모듈 구조

| 파일 | 역할 |
|------|------|
| `_common.py` | CDP 연결, 로그인 대기, Nexacro 그리드 헬퍼, 사업장 선택 |
| `nps_auto_cdp.py` | 메인 진입점 (대화형 메뉴) |

### 향후 배포

별도 `.bat` 파일로 실행 예정 (`국민연금EDI 자동화.bat`):
```bat
@echo off
chcp 65001 >nul
cd /d "%~dp0"
python -u src\automation\nps\nps_auto_cdp.py
pause
```
