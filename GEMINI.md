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
        - `nhis/` (공단) — 건강보험공단 자동화 (개인용) + 건강보험 EDI 자동화 (법인용)
        - `nps/` — 국민연금 EDI 자동화
        - `wehago/` — WEHAGO 급여 자동화
        - `hometax/` — 홈택스 원천세 신고 자동화
    - `ui/`
    - `utils/`
        - `chrome_cdp.py` — Chrome CDP 실행/연결 공통 유틸
        - `stealth.py` — Playwright 스텔스 (navigator.webdriver 제거 등)
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

### 핵심: Nexacro 제어 방식

Nexacro는 일반 DOM click/playwright click을 **무시**함. 이벤트를 직접 dispatch 해야 함:
- **버튼/메뉴 클릭:** `mousedown` → `mouseup` → `click` 이벤트 순차 dispatch (`nexacro_click_button()`)
- **그리드 행 선택:** `dblclick` 이벤트 (1차 click + 2차 click + dblclick 순차 발생)
- **셀 ID 패턴:** `{gridId}.body.gridrow_{row}.cell_{row}_{col}`
- **텍스트 매칭:** 행 인덱스보다 텍스트 기반 검색이 정확 (DOM 순서 ≠ 시각적 순서)
- **메뉴 버튼 ID 패턴:** 상위 `btnTop_M{code}`, 하위 `btn2D_M{code}`

### 플로우

1. **Chrome 실행** — CDP 디버깅 모드 (포트 9223, WEHAGO와 공유)
2. **로그인 대기** — 공동인증서 로그인은 Human-in-the-loop
3. **Nexacro 메인 진입** — `edi.nps.or.kr/nexacro/index.html` 로 리디렉트
4. **사업장 선택** — 업무대행서비스 → 위탁사업장 → 그리드에서 더블클릭 (최초) / 사업장전환(`btnChangeBusi`) 이후
5. **결정내역 조회** — 상단 메뉴 '결정내역'(M08000000) → '국민연금보험료 결정내역'(M08010000)
6. **2차 결정내역 진입** — 이번 달 '2차' 행 더블클릭 → 상세 페이지(M08010200) 오픈
7. **(이후 단계 개발 예정)** — 가입자 내역 추출, 엑셀 저장 등

→ 현재 7~13단계까지 구현됨:

7. **가입자내역 탭 전환** — `tabbutton_2` 클릭 (click_detail_tab)
8. **출력** — '출력' 버튼(btn02 in div00) → 주민번호 전체표출(UHJE0002P1 모달) → 확인 → Crownix rdPreview 탭 오픈
9. **PDF 다운로드** — rdPreview 탭에서 PDF 버튼 클릭 → `~/Desktop/{수임처명}_국민연금/` 에 저장
10. **rdPreview 탭 닫기** — 다운로드 완료 후 자동 종료
11. **엑셀저장** — '엑셀저장' 버튼(btn01 in div01) → 주민번호 전체표출(UHJE0002P3 모달) → 확인 → Excel 다운로드
    - 다운로드 파일은 확장자 없이 저장됨 → `.xlsx` 추가 필요
12. **소급분내역/국고지원내역** — 동일 플로우(PDF+엑셀), 그리드 비어있으면 스킵
    - `process_tab_download()`: 탭 전환 → 그리드 확인 → PDF → 엑셀 순차 처리
    - 파일명: `국민연금보험료_결정내역_{YYYYMM}_{탭라벨}.pdf` / `..._{탭라벨}_엑셀.xlsx`
13. **사업장전환** — 페이지 상단 '사업장전환' 버튼(`btnChangeBusi`) → 사업장 그리드에서 더블클릭
    - 모달 그리드는 최초 로그인 시의 `GRID_WORKPLACE` 와 동일
    - `switch_workplace(page, name)` / `select_workplace(page, name)` 함수로 전환
    - 부분 매칭 지원: 이름 일부만 입력해도 검색, 다중 결과 시 사용자 선택
    - 표시 목록에 없으면 `_search_workplace_in_modal()`로 모달 내 검색 자동 실행
    - 검색 실패 시 이름 재입력 루프 (모달 재오픈)
    - 모달 검색 요소: 콤보 `cbo00.combolist.item_0`(사업장명), 입력 `edt08`, 버튼 `btn00`

### 메뉴 네비게이션 ID

| 메뉴 | ID | MDI 탭 |
|------|----|--------|
| 결정내역 (상위) | `btnTop_M08000000` | — |
| 국민연금보험료 결정내역 | `btn2D_M08010000` | `btnMdiM08010000` |
| 결정내역 조회요청(사업장별) | `btn2D_M08020000` | — |
| 2차 결정내역 상세 | 그리드 더블클릭 진입 | `btnMdiM08010200` |

### 결정내역 그리드 구조

**목록 페이지 (GRID_DECISION_LIST = `divWork_M08010000...grdList`)**

| col | 헤더 |
|-----|------|
| 0 | 순번 |
| 1 | 처리결과 통지일 (공단 → 사업장) |
| 2 | 접수번호 |
| 3 | 업무명 |
| 4 | 건수 |
| 5 | 확인 (사업장) |

**상세 페이지 (GRID_DECISION_DETAIL = `divWork_M08010200...Tabpage1.form`)**

- `grdList`: 산출내역/결정내역 (당월분 인원, 연금보험료, 소급분 등)
- `grdList2`: 가입자 내역 (성명, 주민등록번호, 기준소득월액, 연금보험료, 근로자기여금, 사용자부담금)
- `grdList3`: 소급분 내역
- `grdList4`/`grdList5`: 국고지원내역
- `grdExcelList`: 엑셀 저장용 (고지년월, 성명, 취득일, 상실일, 기준소득월액, 월보험료)
- 탭: 최종결정내역, 수납내역, 가입자내역, 소급분내역, 국고지원내역(예정)

### 결정내역 상세 탭 ID (`tabbutton_{index}`)

| 인덱스 | 탭명 | 상수 |
|--------|------|------|
| 0 | 최종결정내역 | `TAB_FINAL` |
| 1 | 수납내역 | `TAB_RECEIPT` |
| 2 | 가입자내역 | `TAB_MEMBER` |
| 3 | 소급분내역 | `TAB_RETRO` |
| 4 | 국고지원내역 | `TAB_GOVT` |

### 출력/PDF 플로우

1. **출력 버튼** (`btn02`) — `divWork_M08010200...div00.form.btn02`
2. **출력 옵션 모달** (UHJE0002P1) — 주민번호 표출옵션
   - 일부표출: `rdo06.radioitem0`
   - 전체표출: `rdo06.radioitem1`
   - 확인: `div00_00.form.btn01`, 취소: `div00_00.form.btn00`
3. **Crownix rdPreview** (`/comm/rdPreview.do`) — 새 탭으로 열림
   - 툴바에서 `PDF` 버튼(text="PDF") 클릭으로 다운로드
   - `Browser.setDownloadBehavior` CDP로 저장 경로 지정
4. **저장 경로:** `~/Desktop/{수임처명}_국민연금/국민연금보험료_결정내역_{YYYYMM}.pdf`

### 엑셀저장 플로우

1. **엑셀저장 버튼** (`btn01`) — `divWork_M08010200...div01.form.btn01`
2. **엑셀 옵션 모달** (UHJE0002P3) — 출력 모달과 동일 구조, 다른 모달 ID
   - 전체표출: `rdo06.radioitem1`
   - 확인: `div00_00.form.btn01`
3. **다운로드** — 확장자 없이 저장됨 → `.xlsx` 자동 추가
4. **저장 경로:** `~/Desktop/{수임처명}_국민연금/국민연금보험료_결정내역_{YYYYMM}_엑셀.xlsx`

### 통합저장 플로우 (국고지원내역)

1. **통합저장 버튼** (`btn02`) — `divWork_M08010200...div01.form.btn02`
2. **통합 모달** (UHJE0002P2) — 동일 구조, 또 다른 모달 ID
   - 전체표출: `rdo06.radioitem1`, 확인: `div00_00.form.btn01`
3. 모달 ID 정리: **출력=P1, 통합저장=P2, 엑셀저장=P3**

### 모듈 구조

| 파일 | 역할 |
|------|------|
| `_common.py` | CDP 연결, 로그인 대기, Nexacro 그리드/버튼 헬퍼, 사업장 선택, 메뉴/탭 네비게이션, 출력/PDF/엑셀 다운로드 |
| `nps_auto_cdp.py` | 메인 진입점 (전체 자동 / 대화형 메뉴) |

### 향후 배포

별도 `.bat` 파일로 실행 (`국민연금EDI 자동화.bat`):
```bat
@echo off
chcp 65001 >nul
cd /d "%~dp0"
python -u src\automation\nps\nps_auto_cdp.py
pause
```

### 실행 모드

| 모드 | 설명 |
|------|------|
| 전체 자동 (1) | 사업장전환 모달 → 수임처 선택 → 전체 워크플로우 자동 수행 → 반복 |
| 대화형 (2) | 메뉴 선택으로 단계별 수동 진행 |

### 전체 자동 워크플로우 (수임처 1개 단위)

1. 사업장전환 모달 열기 → 수임처 목록 표시 → 번호/이름(부분 매칭)으로 선택
   - 목록에 없어도 이름 직접 입력 → 모달 내 검색(`edt08`+`btn00`)으로 자동 탐색
   - 검색 실패 시 이름 재입력 루프
2. 결정내역 이동 (M08010000)
3. 2차 상세 진입 (M08010200)
4. 가입자내역 → PDF + 엑셀저장
5. 소급분내역 → PDF + 엑셀저장 (빈 경우 스킵)
6. 국고지원내역 → PDF + 통합저장 (빈 경우 스킵)
7. 저장 경로: `~/Desktop/{수임처명}_국민연금/`
8. 다음 수임처 전환 (사업장전환 버튼)

## NHIS EDI Automation Flow (`nhis_edi_auto_cdp.py`)

국민건강보험 EDI (edi.nhis.or.kr) — 법인 계정(업무대행, 서울회계법인) 자동화.
기존 개인용 `nhis_auto_cdp.py`와 별개 모듈.

### 사이트 구조

- **포털 URL:** `https://edi.nhis.or.kr/`
- **메인 페이지:** `https://edi.nhis.or.kr/homeapp/wep/m/retrieveMain.xx`
- **공지 팝업:** `retrievePopupData.do` — 로그인 시 자동 생성, 새 탭으로 열림
  - `#chk_close` 체크박스("하루동안 열지않기") → `closeWin()` JS 함수로 닫으면 쿠키 설정되어 다음 접속 시 재등장하지 않음
- **사업장 선택 팝업:** `retrieveFirmList.do` — 새 탭으로 열림
- **테이블 구조:** `table.list > tbody > tr > td` (td[1]=번호, td[2]=사업장명+링크, td[3]=관리번호, td[4]=단위기호)

### 시작 로직 (main)

1. `launch_chrome(url=NHIS_EDI_URL)` — CDP 모드(포트 9223)로 Chrome 실행/재사용
2. `connect_page(p)` — `_common_edi` 버전으로 `edi.nhis.or.kr` 탭 우선 반환
3. 이미 EDI 페이지면 `page.goto()` 생략 (팝업 재생성 방지)
4. **팝업 먼저 닫기** (`close_popups`) — 공지 팝업이 `pages[0]`일 수 있어 로그인 감시 전 처리 필요
5. `wait_for_login(page)` — 로그인 대기

### 수임사업장 선택

1. **선택 버튼:** `img[src*=we_btn_suim]` (alt="수임사업장선택")
   - 수임처 선택 상태에서는 버튼이 안 보임 → `img[src*=we_btn_relogin]` 으로 먼저 로그인 사업장 복귀 필요
2. **새 탭 팝업** 열림 (`retrieveFirmList.do?no=4`)
3. **페이징:** `fn_next('pageNo')` JavaScript 호출 (10건/페이지)
4. **전체 수집:** `list_all_firms()` — 21페이지 순회하여 202개 사업장 파싱
5. **사업장 선택:** `<a onclick="fn_firmChang('1','','관리번호','단위기호','사업장명','전체관리번호')">` 클릭
6. **검색:** `srchType` (사업장명/사업장관리번호) + `srchText` + `btnSubmit` 폼 제출
7. **선택 완료** 후 팝업 탭 닫기

### 모듈 구조

| 파일 | 역할 |
|------|------|
| `_common_edi.py` | CDP 연결, 로그인 대기, 팝업 닫기, 수임사업장 선택/검색/목록 수집, Nexacro 제어, 1사이클 워크플로우 |
| `nhis_edi_auto_cdp.py` | 메인 진입점 (전체 자동 / 대화형 메뉴) |

### 실행

별도 `.bat` 파일로 실행 (`건강보험EDI 자동화.bat`):
```bat
@echo off
chcp 65001 >nul
cd /d "%~dp0"
python -u src\automation\nhis\nhis_edi_auto_cdp.py
pause
```

### 메뉴

| 번호 | 기능 |
|------|------|
| 1 | 수임사업장 선택 (이름/번호 입력) |
| 2 | 전체 수임사업장 목록 조회 (페이징 수집) |
| 3 | 수임처 PDF 다운로드 (받은문서 → 가입자고지내역서) |
| 4 | 전체 자동 (수임처별 워크플로우 반복) |
| 0 | 종료 |

### 수임처 1사이클 워크플로우 (`run_single_firm_workflow`)

1. **받은문서 열기** — `pageLinkPopup1('201')` → 웹EDI 새 탭 (`webedi/xui/index.jsp`)
2. **'전체' 라디오 선택** — Nexacro 라디오 `rdo_prog_stat` → "전체" 항목 mousedown/mouseup/click
3. **서식명 선택** — Nexacro 콤보 `cbo_docid`
   - `cbo_docid` 요소 로딩 대기
   - `dropbutton` 클릭 → combolist **동적 생성** (클릭 전에는 DOM에 존재하지 않음)
   - combolist 생성 대기 후 "가입자 고지(산출) 내역서" 항목 mousedown/mouseup/click
4. **첫 행 더블클릭** — 그리드 `grid_list` row 0, col 3 (서식명) dblclick
5. **인쇄 버튼** — `div_top_img_print` mousedown/mouseup/click
6. **미리보기 탭** — `popup.html?formname=CO::WETZ_163.xfdl` 열림
7. **PDF 저장** — reportview iframe 내 `button[title="PDF 저장"]` 클릭 (Playwright locator)
   - `Browser.setDownloadBehavior` CDP로 저장 경로 지정
   - `~/Desktop/{수임처명}_국민건강보험/가입자고지내역서_건강_{YYYYMM}.pdf`
8. **탭 정리** — 미리보기 + 웹EDI 탭 닫기
9. **로그인 사업장 복귀** — `img[src*=we_btn_relogin]` 클릭
10. **모달 닫기** — 공지사항 등 팝업 탭 정리

### Nexacro 제어 방식

웹EDI 탭(`webedi/xui/index.jsp`)은 **Nexacro** 기반. 일반 DOM click/playwright click을 무시하므로 이벤트 직접 dispatch 필요:
- **버튼 클릭:** `mousedown` → `mouseup` → `click` (인라인 JS로 직접 dispatch)
- **그리드 행 선택:** `dblclick` 이벤트 (1차 click + 2차 click + dblclick)
- **셀 ID:** `{gridId}_body_gridrow_{row}_cell_{row}_{col}`
- **콤보박스:** `dropbutton` 클릭 → combolist가 **동적 생성**됨 (클릭 전에는 DOM에 없음) → `_item` div에서 TextBoxElement 텍스트로 매칭 후 클릭
- **라디오 (Nexacro API):** dispatchEvent로는 시각/데이터 불일치 발생 → **Nexacro 내부 API** 사용:
  - `wait_for_nexacro_ready(page)` — DOM 요소뿐 아니라 `nexacro.Application.mainframe.childframe.form` 접근 가능까지 대기
  - `nexacro_set_radio(page, index)` — `radio.set_index(index)` + `radio.on_fire_onitemchanged()` 로 내부 상태 + 시각 + 그리드 리로드 모두 처리
  - 인덱스: 0=전체, 1=신규, 2=열람
  - 접근 경로: `nexacro.Application.mainframe.childframe.form.components.div_body.components.rdo_prog_stat`
- **미리보기 PDF:** iframe(`reportview.jsp`) 내 버튼 — Playwright `locator.click()` 사용 (Nexacro 외부 영역)

### 주요 디버깅 포인트

| 문제 | 원인 | 해결 |
|------|------|------|
| 수임사업장선택 버튼 안 보임 | 수임처 선택 상태에서는 숨음 | 먼저 `we_btn_relogin`으로 로그인 사업장 복귀 |
| combolist not found | dropbutton 클릭 전에 combolist DOM 없음 | dropbutton 클릭 후 combolist 생성 대기 |
| 서식명 선택 후 값 불일치 | Nexacro 내부 상태 동기화 지연 | 1초 대기 후 input 값 확인 |
| 라디오 "전체" 안 바뀜 | dispatchEvent로 시각/데이터 불일치 | Nexacro API `set_index(0)` + `on_fire_onitemchanged()` 사용 |
| Nexacro API 접근 불가 | 프레임워크 로딩 전에 실행 | `wait_for_nexacro_ready()`로 mainframe.form 접근 확인 후 실행 |

## Playwright Stealth (`src/utils/stealth.py`)

### 적용 배경

이 프로젝트는 CDP 모드로 **실제 Chrome**에 연결하므로 이미 강력한 안티탐지 기반을 가짐:
- 실제 Chrome + 실제 사용자 프로필 (쿠키/히스토리/확장프로그램)
- Human-in-the-loop 공동인증서 로그인
- 대상 사이트(NHIS EDI, NPS EDI, WEHAGO, 홈택스)는 엔터프라이즈 안티봇 미사용

### 설계 원칙

**실제 Chrome의 핑거프린트 값을 위장하지 않는다.** playwright-stealth는 Headless Chrome 환경을 위해 만들어졌으므로, 실제 Chrome에서 WebGL vendor를 "Intel Iris"로 덮어쓰거나 hardwareConcurrency를 4로 강제 설정하면 **값 간 불일치**가 발생해 오히려 탐지 신호가 됨. 따라서 webdriver 등 자동화 마커만 제거하고 나머지는 실제 값 유지.

### 적용한 것

1. **Chrome 실행 인수** — 자동화 관련 플래그 미사용 (Chrome 경고문 방지). playwright-stealth JS 오버라이드에 전적으로 의존.
2. **`playwright-stealth` v2.0+ (Stealth 클래스)** — 선택적 모듈 적용:
   - **활성**: navigator.webdriver, plugins, permissions, vendor, chrome_app, chrome_csi, chrome_loadTimes, hairline, iframe_contentWindow, error_prototype
   - **비활성** (실제 값 유지): webgl_vendor, navigator_hardware_concurrency, navigator_platform, navigator_languages, navigator_user_agent, navigator_user_agent_data, sec_ch_ua, media_codecs, chrome_runtime
3. **신규 탭 자동 처리** — `context.on("page")` 콜백으로 사이트가 여는 팝업/탭에도 자동 스텔스 적용
4. **Fallback** — playwright-stealth 미설치 시 `navigator.webdriver` 수동 오버라이드만 적용

### 적용하지 않은 것 (해로움)

- **WebGL/hardwareConcurrency 위장** — 실제 GPU·코어 수와 불일치 → 탐지 신호
- **browserforge** (핑거프린트 위장) — 실제 프로필 핑거프린트와 충돌
- **User-Agent 로테이션** — 세션 깨짐
- **프록시 로테이션** — 단일 사용자/단일 PC
- **리소스 차단** — Nexacro, Crownix, Raon 등 필수 리소스 로딩 불가
- **마우스/타이핑 시뮬레이션** — Nexacro dispatchEvent와 충돌

### 적용 지점

| 파일 | 함수 | 역할 |
|------|------|------|
| `src/utils/stealth.py` | `apply_stealth()`, `stealth_all_pages()`, `register_auto_stealth()` | 스텔스 공통 유틸 |
| `src/utils/chrome_cdp.py` | `connect_page()` | 공용 CDP 연결 (WEHAGO) |
| `src/automation/nhis/_common_edi.py` | `connect_page()` | NHIS EDI 연결 |
| `src/automation/nps/_common.py` | `connect_page()` | NPS EDI 연결 |
| `src/automation/hometax/hometax_auto_cdp.py` | `connect_browser()` | 홈택스 연결 |
| `src/automation/wehago/wehago_auto_cdp.py` | `connect_browser()` | WEHAGO 연결 |
| `src/automation/nhis/nhis_auto_cdp.py` | inline | NHIS 개인용 자동화 |
| `src/automation/wehago/_full_run.py` | inline | WEHAGO 전체 실행 |
| `src/automation/wehago/_run_swer.py` | inline | SWER 원천징수이행 |

### 주요 요소 ID

| 요소 | ID |
|------|-----|
| 받은문서 그리드 | `mainframe_childframe_form_div_body_grid_list` |
| 서식명 콤보 | `mainframe_childframe_form_div_body_cbo_docid` |
| 상태 라디오 | `mainframe_childframe_form_div_body_rdo_prog_stat` |
| 인쇄 버튼 | `mainframe_childframe_form_div_top_img_print` |

---

## 대규모 배치 자동화 아키텍처 (설계 문서)

> **상태:** 설계 완료, 코드 구현은 `src/batch/` 모듈에 베이스 코드만 존재.
> 각 포털(NHIS EDI, NPS EDI, WEHAGO, Hometax)의 **전체 수임처 자동화** 적용 시 참고.

### 개요

현재 각 포털 자동화는 **1개 수임처 단위**로 수동 실행됨. 회계법인 실무에서는
월 100~200개 수임처를 순차 처리해야 하므로, SQLite 기반 배치 엔진으로
**크래시 복구, 재시도, 진행률 추적**을 자동화.

```
YAML 설정 → BatchEngine → [Job 1, Job 2, ..., Job N] → Reporter
                ↓                ↓
           SQLite DB        StateManager
         (checkpoint)     (step tracking)
```

### `src/batch/` 모듈 구조

| 파일 | 역할 |
|------|------|
| `models.py` | 데이터 모델 (Portal enum, Client/Batch/Job/Step dataclass, 상태 전이) |
| `db.py` | SQLite WAL 모드, Repository 패턴 (Client/Batch/Job/Step CRUD) |
| `state.py` | StateManager — 단계 체크포인트, 크래시 복구, 이어서 진행 |
| `engine.py` | BatchEngine — 비동기 배치 오케스트레이터 |
| `reporter.py` | HTML + CSV 결과 리포트 생성 (비개발 사용자용) |
| `__init__.py` | 공개 API exports |

### 상태 머신

- **Batch:** created → running → completed / paused / crashed / archived
- **Job:** pending → running → completed / failed / skipped
- **Step:** pending → running → completed / failed

### 포털별 배치 준비도

| 포털 | 단일 자동화 | 배치 준비도 | 비고 |
|------|-------------|-------------|------|
| NHIS EDI | 완료 (10단계 워크플로우) | ~70% | BatchAdapter 구현 필요 |
| NPS EDI | 완료 (13단계 워크플로우) | ~65% | 사업장전환 로직 재사용 |
| WEHAGO | 부분 (SWSA0101, SWER0101) | ~15% | 다중 서식 미지원 |
| Hometax | 초기 (SWTA0101) | ~10% | 기본 구조만 |

### BatchAdapter 인터페이스 (설계)

각 포털별로 구현해야 할 인터페이스:

```python
class BatchAdapter(ABC):
    @abstractmethod
    async def login(self, page) -> None: ...

    @abstractmethod
    async def select_client(self, page, client_name: str) -> None: ...

    @abstractmethod
    async def run_workflow(self, page, client_name: str,
                          state: StateManager) -> list[str]: ...

    @abstractmethod
    async def verify_result(self, page, client_name: str) -> bool: ...
```

### 수임처 설정 스키마 (YAML)

```yaml
# config/clients.yaml
nhis_edi:
  - name: "(주)ABC"
    code: "1234567890"
    active: true
  - name: "XYZ 주식회사"
    code: "0987654321"
    active: true

nps_edi:
  - name: "(주)ABC"
    search_keyword: "ABC"
    active: true

wehago:
  - name: "(주)ABC"
    business_no: "123-45-67890"
    active: true
```

### UX 설계 (비개발 사용자 관점)

1. **콘솔 진행률** — `[3/200] (주)ABC 처리 중... [=====>    ] 1.5%`
2. **크래시 후 재시작** — `이어서 진행 (3/200부터 계속)`
3. **실패 재시도** — 실패 건만 자동 재시도 (최대 3회)
4. **HTML 리포트** — 완료 후 브라우저로 결과 확인 (수임처별 성공/실패/소요시간)
5. **오류 메시지** — 한글 오류 + 복구 방법 제안

### 대규모 처리 기법 — 적용 가능성 분석 완료

대상 사이트가 Nexacro(NHIS EDI, NPS EDI)와 SPA(WEHAGO) 기반이므로,
일반 웹 크롤링 기법의 대부분이 이 프로젝트 아키텍처에 **부적합**함.

#### 영구 불가 (적용하면 자동화 자체가 고장남)

| 기법 | 이유 |
|------|------|
| Nexacro 이벤트 시퀀스 랜덤 지연 | mousedown→mouseup→click 사이 지연 = 이벤트 무시됨 |
| 워크플로우 도중 페이지 새로고침 | Nexacro MDI 탭 전부 닫힘, SPA 라우팅 리셋 |
| 자동 재로그인 | 공동인증서 로그인, 물리적 사용자 개입 필수 |
| 적응형 토큰 버킷 | 브라우저 자동화에 "요청/초" 개념 미적용 |
| rebrowser-patches | page.evaluate() 크래시 리스크, Nexacro 제어가 evaluate에 전적으로 의존 |

#### 배치 시점에 가능 (수임처 간 전환에서만 동작)

| 기법 | 적용 방식 |
|------|----------|
| Circuit Breaker | 배치 엔진 레벨 — 연속 실패 시 배치 일시정지 |
| 시간대별 속도 조절 | 수임처 간 대기 시간 가중치 (자동화 로직 무변경) |
| 수임처 전환 시 새로고침 | switch_firm/switch_workplace 직전에만 수행 |
| 세션 만료 감지 | 배치 엔진 훅 — 만료 시 일시정지 후 사용자에게 재로그인 요청 |

### 예상 소요 시간 (포털당)

- 수임처 1개당 약 30~60초 (서버 응답 시간 포함)
- 200개 수임처: **2~3시간** (포털당)
- 4개 포털 전체: **8~13시간** (순차 처리 기준)
- 병렬 처리 불가: 동일 Chrome 세션, 동일 포털 계정 사용
