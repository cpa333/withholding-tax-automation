# 원천징수 자동화 시스템 — 기술 문서

## 1. 개요

세무법인에서 사용하는 원천징수 업무 자동화 Windows 데스크톱 애플리케이션. 7개 포털에 걸친 전체 워크플로우를 하나의 GUI에서 관리하고, 수임처별 진행 상황을 실시간으로 추적한다.

**핵심 원칙:**
- 기존 콘솔 자동화 스크립트를 수정 없이 어댑터로 래핑하여 재사용
- 수동 로그인(Human-in-the-loop) 방식 — 공동인증서 인증은 사용자가 직접 수행
- 모든 진행 상태를 SQLite에 저장하여 프로그램 재시작 후에도 복구 가능

## 2. 아키텍처

```
┌─────────────────────────────────────────────────────────┐
│  Layer 3: PySide6 GUI                                   │
│  main_window / widgets / workers                         │
│  ↕ Qt Signal/Slot + asyncio-in-QThread                  │
├─────────────────────────────────────────────────────────┤
│  Layer 2: Workflow Adapter                               │
│  BaseWorkflow → 각 포털별 어댑터 (7개)                    │
│  ↕ 기존 함수 호출만                                      │
├─────────────────────────────────────────────────────────┤
│  Layer 1: 기존 자동화 코드 (수정 없음)                    │
│  src/automation/ (Playwright) + src/batch/ (SQLite)      │
└─────────────────────────────────────────────────────────┘
```

## 3. 7단계 워크플로우

| Phase | 포털 | 기능 | 상태 |
|-------|------|------|------|
| 1 | WEHAGO | 수임처 리스트 확보 | 완료 |
| 2 | 국민건강보험 EDI | 결정내역 PDF/Excel 다운로드 | 완료 |
| 3 | 국민연금 EDI | 결정내역 PDF/Excel 다운로드 | 완료 |
| 4 | WEHAGO | 급여자료입력 (SWSA0101) | 구현 |
| 5 | WEHAGO | 원천이행상황신고서 (SWTA0101) | 구현 |
| 6 | WEHAGO | 원천전자신고 (SWER0101) | 구현 |
| 7 | 홈택스 | 종합소득세 신고 | 구현 |

### Phase 1: 수임처 리스트 확보 (WEHAGO)

기존 방식과 다르게 Phase 1은 독립적으로 동작한다:
- **DB 영속화:** 한 번 가져온 리스트는 SQLite에 저장되어 프로그램 재시작 시 즉시 표시
- **새로 가져오기 버튼:** WEHAGO에 접속하여 최신 수임처 목록을 스크래핑 후 DB 교체
- **모두 삭제 버튼:** 등록된 수임처 전체 삭제 (확인 다이얼로그 포함)
- "시작" 버튼은 Phase 1에서 비활성화됨

스크래핑 동작 (`get_clients_with_biz_from_taxagent`):
1. 수임처관리 페이지(`tedge/#/taxagent`)로 이동 → 모달 닫기 → 리스트 로딩 대기
2. 스크롤 컨테이너를 끝까지 스크롤하여 전체 카드(24개) 로드
3. 각 카드를 순차 클릭 → `div.cl_basicinfo_section` 상세 영역에서 사업자등록번호(`\d{3}-\d{2}-\d{5}`) 추출
4. 수임처명은 `li.is_linkbtn.selected > span.company_name_text`에서 추출
5. `[테스트]` 접두사 제거 후 DB에 wehago 포털로 저장 (수임처명 + 사업자등록번호)
6. 레거시: `get_all_clients_from_management()` (이름만 수집)은 별도 유지

> **참고:** 메인 페이지(`#/main`)의 카드 UI는 SPA 가상 스크롤로 인해 항상 20개만 DOM에 렌더링되어 전체 수임처를 보장하지 않음.

### Phase 2: 국민건강보험 EDI

1. Chrome 실행 → edi.nhis.or.kr 접속
2. 사용자가 공동인증서로 수동 로그인 (최대 15분 대기)
3. BatchEngine이 WEHAGO 수임처를 nhis_edi 포털에 자동 복사
4. 수임처별로 순차 처리:
   - 사업장 선택 → 결정내역 이동 → 2차 상세 진입
   - 각 탭(PDF/Excel) 다운로드
5. 저장 경로: `~/Desktop/{수임처명}_국민건강보험/`

### Phase 3: 국민연금 EDI

Nexacro 기반 웹 프레임워크로 일반 DOM click이 동작하지 않음:

1. Chrome 실행 → edi.nps.or.kr 접속
2. 사용자 공동인증서 수동 로그인
3. 수임처별 순차 처리:
   - 사업장 전환 → 결정내역 이동 → 2차 상세 진입
   - 가입자내역(`grdList2`), 소급분내역(`grdList3`), 국고지원내역(`grdList4`) 탭 처리
4. Nexacro 이벤트: `dispatchEvent(new MouseEvent(...))` 로 mousedown → mouseup → click 순차 발생
5. 저장 경로: `~/Desktop/{수임처명}_국민연금/`

## 4. UI 레이아웃

```
+------------------------------------------------------------------+
|  Toolbar: [2026][05] [☑ dry-run]          [▶시작] [⏸일시정지] [⏹정지] |
+------------------------------------------------------------------+
| Phase Sidebar       |  수임처 테이블                               |
|                     |  [새로 가져오기] [모두 삭제]  ← Phase 1 시    |
| 1 수임처리스트      |  수임처명        | 포털   | 활성              |
|   (24건)            |  ──────────────────────────────────────────  |
|                     |  (주)제이에스     | wehago | O                 |
| 2 건강보험     ✓   |  삼성전자(주)     | wehago | O                 |
|   (12/24)           |  ...                                        |
|                     |  ── 세부 단계 ──                            |
| ▶ 3 국민연금        |  [✓] 1. 사업장 선택                         |
|   (5/24 진행중)     |  [▶] 2. 결정내역 이동                       |
|                     |  [ ] 3. 2차 상세 진입                       |
| 4 WEHAGO 급여  ⏳   |                                             |
| 5 WEHAGO 이행  ⏳   |                                             |
| 6 WEHAGO 신고  ⏳   |                                             |
| 7 홈택스 신고  ⏳   |                                             |
+---------------------+---------------------------------------------+
|  [14:32:11] [국민연금] 삼성전자 - 결정내역 이동...                 |
|  [14:32:15] [국민연금] 삼성전자 - 2차 행 발견 (row=3)              |
+------------------------------------------------------------------+
```

### Phase 1 선택 시
- "시작" 버튼 비활성화
- "새로 가져오기" / "모두 삭제" 버튼 표시
- 수임처 목록 테이블에 포털/활성 컬럼 표시

### Phase 2+ 선택 시
- "시작" 버튼 활성화
- 수임처 관리 버튼 숨김
- Job 상태 테이블로 전환 (수임처명/상태/현재단계/소요시간/에러)

## 5. 프로젝트 구조

```
withholding-tax-automation/
├── gui_main.py                     # GUI 진입점
├── build.py                        # PyInstaller 빌드 스크립트
├── main.py                         # CLI 진입점 (기존)
├── requirements.txt
│
├── src/
│   ├── ui/                         # PySide6 GUI
│   │   ├── main_window.py          # 메인 윈도우 (전체 레이아웃)
│   │   ├── widgets/
│   │   │   ├── phase_sidebar.py    # 7개 페이즈 버튼 + 상태
│   │   │   ├── company_table.py    # 수임처 테이블 + 관리 버튼
│   │   │   ├── step_detail.py      # 수임처별 세부 단계
│   │   │   └── log_panel.py        # 로그 출력
│   │   ├── workers/
│   │   │   ├── async_bridge.py     # QThread + asyncio 브릿지
│   │   │   └── automation_runner.py# 페이즈 실행 오케스트레이터
│   │   └── resources/
│   │       └── style.qss           # Qt 스타일시트
│   │
│   ├── workflows/                  # 어댑터 레이어
│   │   ├── base.py                 # BaseWorkflow ABC
│   │   ├── registry.py             # phase_id → 클래스 매핑
│   │   ├── wehago_list_clients.py  # Phase 1
│   │   ├── nhis_edi.py             # Phase 2
│   │   ├── nps_edi.py              # Phase 3
│   │   ├── wehago_swsa.py          # Phase 4
│   │   ├── wehago_swta.py          # Phase 5
│   │   ├── wehago_swer.py          # Phase 6
│   │   └── hometax.py              # Phase 7
│   │
│   ├── automation/                 # 포털별 자동화 (수정 없이 재사용)
│   │   ├── wehago/                 # WEHAGO 포털
│   │   │   ├── _common.py          # 공통 함수 (로그인, 수임처 검색 등)
│   │   │   ├── run_swsa0101.py     # 급여자료입력
│   │   │   ├── run_swta0101.py     # 원천이행상황신고서
│   │   │   └── run_swer0101.py     # 원천전자신고
│   │   ├── nhis/                   # 국민건강보험 EDI
│   │   │   ├── _common_edi.py      # 공통 함수
│   │   │   └── nhis_auto_cdp.py    # 전체 워크플로우
│   │   ├── nps/                    # 국민연금 EDI (Nexacro)
│   │   │   ├── _common.py          # 공통 함수
│   │   │   └── nps_auto_cdp.py     # 전체 워크플로우
│   │   └── hometax/                # 홈택스
│   │       └── hometax_auto_cdp.py # 전체 워크플로우
│   │
│   ├── batch/                      # 배치 처리 엔진
│   │   ├── engine.py               # BatchEngine (수임처별 순차 실행)
│   │   ├── state.py                # StateManager (단계 체크포인트)
│   │   ├── models.py               # Client, Job, Step 데이터클래스
│   │   └── db.py                   # SQLite Repository
│   │
│   └── utils/
│       ├── chrome_cdp.py           # Chrome CDP 실행/연결
│       ├── stealth.py              # Playwright 안티디텍션
│       └── pdf_reader.py           # PDF 텍스트 추출
│
├── data/
│   └── withholding_tax.db          # SQLite DB (런타임 생성)
│
└── dist/
    └── 원천징수자동화.exe           # 빌드 산출물
```

## 6. Worker 아키텍처

Playwright(asyncio)와 PySide6(Qt 이벤트루프)를 분리하기 위해 QThread 내부에서 별도 asyncio 이벤트루프를 실행한다.

```
AutomationRunner (AsyncWorker)
  ├── QThread에서 asyncio 이벤트루프 실행
  ├── Playwright browser 연결 관리 (Chrome CDP)
  ├── 명령 큐로 제어: run_phase / refresh_clients / stop
  ├── 일시정지/재개 이벤트
  └── Qt Signal로 UI 업데이트:
       log_message(str)
       phase_changed(int, str)
       job_changed(int, str, str, str, str)
       batch_progress(dict)
       error_occurred(str)
```

## 7. Chrome 세션 관리

포털 전환 시 Chrome을 재시작한다:

| Phase | 포털 | URL |
|-------|------|-----|
| 1, 4, 5, 6 | WEHAGO | https://www.wehago.com/ |
| 2 | 국민건강보험 EDI | https://edi.nhis.or.kr/ |
| 3 | 국민연금 EDI | https://edi.nps.or.kr/ |
| 7 | 홈택스 | https://www.hometax.go.kr/ |

모든 포털에서 CDP 포트 9223을 사용한다. Chrome은 `subprocess.Popen`으로 실행하며, Playwright는 `connect_over_cdp`로 연결한다.

## 8. 데이터베이스 스키마

SQLite (`data/withholding_tax.db`), FK 제약조건 활성화:

```
clients   (id, name, portal, business_number, enabled, priority, notes)
    ↑ FK
batches   (id, batch_key UNIQUE, portal, status, created_at)
    ↑ FK
jobs      (id, batch_id, client_id, client_name, status, current_step, ...)
    ↑ FK
steps     (id, job_id, step_name, step_index, status, started_at, ...)
```

- Phase 1 실행 시: clients만 사용 (jobs/batches/steps 미사용)
- Phase 2+ 실행 시: batches → jobs → steps 계층 구조로 진행 추적
- Phase 2+ 시작 시 해당 포털의 배치 데이터만 초기화, clients는 유지

## 9. 빌드 및 실행

### 초기 환경 설정 (처음 실행하는 PC)

`setup.bat`를 **관리자 권한으로 실행** (우클릭 → 관리자 권한으로 실행):

1. 관리자 권한 확인
2. Python 3.10+ 설치 여부 및 버전 확인
3. pip 업그레이드
4. `requirements.txt` 패키지 일괄 설치 (PySide6, Playwright, pywinauto, PyMuPDF 등)
5. Playwright Chromium 브라우저 바이너리 설치 (~150MB)
6. Google Chrome 설치 여부 확인

사전 요구:
- **Python 3.10+**: 미설치 시 python.org 또는 Microsoft Store에서 설치 (PATH 추가 필수)
- **Google Chrome**: 미설치 시 google.com/chrome에서 설치

### 개발 모드

```bash
# 의존성 설치
pip install -r requirements.txt
playwright install chromium

# GUI 실행
python gui_main.py

# CLI 실행 (기존)
python main.py
```

### EXE 빌드

```bash
python build.py
# 산출물: dist/원천징수자동화.exe (~294 MB)
```

빌드 설정:
- `--windowed`: 콘솔 창 없이 GUI만 표시
- `--onefile`: 단일 exe 파일
- PySide6, Playwright, pywinauto, comtypes 서브모듈 전체 수집
- `style.qss` 리소스 파일 번들
- `gui_main.py`에서 `sys._MEIPASS`로 리소스 경로 처리

실행 전제 조건:
- Chrome이 시스템에 설치되어 있어야 함
- Playwright 브라우저 바이너리 설치 필요 (`playwright install chromium`)

## 10. 의존성

| 패키지 | 용도 |
|--------|------|
| PySide6 | GUI 프레임워크 |
| playwright | 브라우저 자동화 |
| playwright-stealth | 안티디텍션 |
| pywinauto | Windows GUI 자동화 |
| openpyxl | Excel 파일 처리 |
| comtypes | COM 인터페이스 |
| PyMuPDF | PDF 텍스트/표 추출 |
| pyinstaller | exe 빌드 |

## 11. 핵심 설계 결정

| 결정 | 이유 |
|------|------|
| Phase 1을 BatchEngine에서 분리 | 수임처 리스트는 배치 작업이 아닌 마스터 데이터. DB 영속화 필요. |
| WEHAGO SPA에 `domcontentloaded` 사용 | `networkidle` 대기 시 WEHAGO가 항상 네트워크 연결을 유지하여 30초 타임아웃 발생. |
| Nexacro에 dispatchEvent 사용 | 일반 DOM click을 Nexacro가 무시함. mousedown→mouseup→click 순차 이벤트 필요. |
| CDP 포트 9223 통일 | 포트별 Chrome 인스턴스 관리 복잡도 감소. 포털 전환 시 kill 후 재시작. |
| 수동 로그인 방식 | 공동인증서/보안모듈 자동화의 법적/기술적 리스크 회피. |
| QThread + asyncio 분리 | Playwright(asyncio)와 Qt 이벤트루프를 직접 섞을 수 없음. |
