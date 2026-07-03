# 병렬 자동화 핸드오프 — NPS EDI + NHIS EDI 동시 실행 feasibility

> **목적:** 이 문서는 NPS(국민연금) EDI 자동화와 NHIS(건강보험) EDI 자동화를 **동시에 병렬**로 실행할 수 있는지의 feasibility를 **다른 세션에서 그대로 이어** 검토·구현할 수 있도록 정리한다. 구현을 시작하려면 먼저 이 문서 전체를 읽을 것.
>
> **작성 시점:** 2026-06-23. feasibility 평가 완료(코드 구현 전). 서브에이전트 3개(브라우저/CDP·페이지 선택 / 스레드·async·GUI / 데이터·다운로드·세션) 병렬 조사 기반.
>
> **상태:** ⏳ feasibility 완료 · 구현 미착수 · 사용자 결정 대기.

---

## 0. 한눈에 보기

| 접근 | 병렬 가능성 | 노력 | 비고 |
|---|---|---|---|
| **현재 구조 (단일 Chrome 공유)** | 🔴 LOW — 사실상 불가 | - | 치명적 블로커 5종 (§3) |
| **별도 Chrome 인스턴스 (포트+프로필 분리)** | 🟢 가능 | 🟡 MEDIUM-HIGH | 블로커 자동 해소. `chrome_cdp.py` 파라미터화 + `kill_chrome` 정밀화가 핵심 |
| 같은 Chrome + Playwright `new_context()` | 🟡 부분 | - | 권장 ❌ — 공동인증서 로그인 묶임 + setDownloadBehavior 레이스/kill_chrome 잔존 |

**한 줄 결론:** 두 자동화는 *논리적*(포털 도메인·저장경로·로그인패턴)으로 이미 분리되어 병렬에 적합하지만, **단일 Chrome + 단일 CDP 포트(9223) + `kill_chrome` 전체 종료** 구조가 물리적 병렬을 막는다. 병렬하려면 Chrome 인스턴스를 포트/프로필로 분리하는 리팩터 필요.

---

## 1. 핵심 결정 (사용자 확정 대기)

| 항목 | 상태 |
|---|---|
| **병렬 가치** | 미확정 — 두 EDI가 같은 시기에 필요한 워크로드인지 사용자 판단 필요 (그래야 절반 단축 효과) |
| **구현 경로** | 미확정 — 권장은 **CLI 2-프로세스**(최소 수정) 우선 검증 → 효용 확인 후 GUI 다중 러너 확장 |
| **동작 보존** | 각 자동화의 단독 동작은 100% 보존 필수 (병렬 도입이 직렬 경로를 깨면 안 됨) |

> 본 feasibility는 코드 수정 없이 평가만 수행했다. 구현 착수는 사용자 명시 시 별도 plan/세션에서.

---

## 2. 배경 — 현재 실행 구조

- NPS·NHIS EDI 자동화는 **GUI 메뉴 / CLI 각각 별도**로 실행되어 직렬 동작.
- GUI: `src/ui/main_window.py:35` 가 단일 `self.runner = AutomationRunner(self)` 보유 — 한 번에 한 자동화만.
- CLI: `src/automation/nps/nps_auto_cdp.py:490`, `src/automation/nhis/nhis_edi_auto_cdp.py:340` 각각 독립 `asyncio.run(main())`.
- 두 자동화 모두 **동일 Chrome CDP 세션**(포트 9223, junction real profile) 재사용 — memory `feedback_chrome-cdp-setup`(재사용 우선, force-kill 금지) 참조.

---

## 3. ❌ 같은 Chrome 공유 → 병렬 불가 (치명적 블로커)

### 3.1 `kill_chrome()` 전체 Chrome 강제 종료 ★가장 치명
`src/utils/chrome_cdp.py:143-148` — `taskkill /F /IM chrome.exe /T` 로 **시스템 전체 chrome.exe 종료**.
호출처: `automation_runner.py:487`(`_disconnect_browser`), `:496`(`cleanup_session`), `chrome_cdp.py:174`(`_attempt_launch`).
→ 한 러너의 종료/에러복구가 **다른 러너의 Chrome 세션까지 파괴**.

### 3.2 CDP 포트 9223 단일 하드코딩
`src/utils/chrome_cdp.py:12-15` — `CDP_PORT = 9223`, `CDP_URL` 전역 상수. 함수 파라미터 아님.
`connect_page()`(`chrome_cdp.py:267-287`)이 항상 `browser.contexts[0]` 사용.
→ 두 러너/프로세스가 같은 Chrome 컨텍스트에 연결 → 탭 공유.

### 3.3 `_close_edi_tabs()` 타 포털 탭 파괴
`src/automation/nhis/_doc_download.py:470-478` — NHIS가 `retrieveMain` 외 **모든 탭**을 닫음.
`src/automation/nps/_download.py:614-620` — NPS도 `context.pages` 전체 순회(`rdPreview` 필터).
→ 같은 컨텍스트면 NHIS가 NPS nexacro/rdPreview 탭을 닫아버림.

### 3.4 `Browser.setDownloadBehavior` 브라우저-레벨 레이스
`src/automation/nps/_download.py:339`, `src/automation/nhis/_doc_download.py:235` — `context.new_cdp_session().send("Browser.setDownloadBehavior", {downloadPath: ...})`.
이 설정은 **page-level이 아니라 browser-level** → 두 러너가 동시에 각자 `downloadPath` 설정 시 **나중 설정이 이전을 덮어쓰기** → NPS 파일이 NHIS 폴더로(또는 그 반대) 저장될 위험.

### 3.5 `_log_callback` 글로벌 단일
`src/utils/log.py:14` — 모듈 레벨 전역 단일 콜백. `automation_runner.py:78-79`에서 `set_log_callback(lambda msg: self.log_message.emit(msg))`.
→ 두 번째 러너가 첫 러너 콜백을 덮어씀 → 로그 한쪽으로 유실/뒤섞임.

### 3.6 (GUI 한정) 단일 러너 + 실행 중 가드 없음
`src/ui/main_window.py:35` — `MainWindow`가 러너 1개만 보유, NPS/NHIS 구분 없음.
`_on_start`(`main_window.py:419`)에 "실행 중이면 막기" 가드 없음 → 두 번째 실행이 첫 러너 명령 큐에 적재(의도치 않은 순차 처리).

### 3.7 부가 — stealth 콜백 중복 / context.pages[0] fallback
- `stealth.py:77-79` `register_auto_stealth` 가 context "page" 이벤트 핸들러를 호출마다 추가 등록(중복 방지 로직 없음). 같은 context면 핸들러 2개 → 멱등이라 치명 오류는 아니나 오버헤드/예외 경로 노출.
- `_common.py:94`, `_common_edi.py:101` 의 `context.pages[0]` fallback — 동시 실행 시 탭 순서 의존으로 불확정.

---

## 4. ✅ 이미 안전한 부분 (병렬에도 변경 불필요)

- **저장 경로 분리**: `Desktop/국민연금_YYYYMM/수임처/` vs `Desktop/국민건강보험_YYYYMM/수임처/` (`src/utils/save_path.py:60` `make_save_dir`). 충돌 0.
- **파일명 중복 없음**: `결정내역통보서_{YYYYMM}.xlsx` vs `가입자고지내역서_건강_{YYYYMM}.pdf`.
- **다운로드 경로 직접 지정**: CDP `Browser.setDownloadBehavior` 로 각자 `save_dir` 직접 저장 → Chrome 기본 Downloads 폴더 `.crdownload` 꼬임 없음 (단 §3.4 browser-level 덮어쓰기 위험은 별도).
- **도메인/쿠키 격리**: `edi.nps.or.kr` vs `edi.nhis.or.kr` — 한 프로필에 두 세션 공존 가능 (`src/config.py:34-39` PORTAL_URLS).
- **로그인 URL 패턴 분리**: NPS `nexacro` (`nps/_common.py:98`) / NHIS `retrieveMain`·`homeapp` (`nhis/_common_edi.py:105`).
- **stop/pause 이벤트**: 러너 인스턴스별 분리 (`async_bridge.py:72-74`).
- **job_id**: AUTOINCREMENT — 두 러너가 다른 job 조작 시 논리 충돌 없음 (`src/batch/state.py`).
- **SQLite 기본 방어**: WAL + `busy_timeout=5000` (`src/batch/db.py:166-173`). 단 "단일 스레드 전용" 설계 주석 — 동시 쓰기 경합은 검증 필요(§6).

---

## 5. 🔧 병렬이 가능하려면 — 별도 Chrome 인스턴스 접근

### 5.1 핵심 아이디어
**NPS = 포트 9223 + 프로필A, NHIS = 포트 9224 + 프로필B** 로 완전히 분리된 Chrome 2개.
→ §3 블로커 1~5가 자동 해소(각자 브라우저·컨텍스트·다운로드 동작·종료 격리).

### 5.2 주요 변경점 (high-level, 구현 시 별도 상세 plan)
- **`src/utils/chrome_cdp.py`** (~10곳): `CDP_PORT`/`CDP_URL`/junction 경로(`%TEMP%/chrome-cdp-link` 고정, `chrome_cdp.py:110`)/user-data-dir(`find_chrome_user_data`/`find_chrome_profile`)을 **함수 파라미터화**. `launch_chrome`/`_attempt_launch`/`check_cdp_available`/`connect_page` 계열.
- **`kill_chrome()` 정밀화**: `taskkill /F /IM chrome.exe /T`(전체 종료) → **PID/포트 기반 정밀 종료** 로 변경. ★ memory `feedback_chrome-cdp-setup`(CDP 살아있으면 force-kill 금지·재사용 우선)과 가장 충돌 — 가장 민감한 변경.
- **`src/ui/workers/automation_runner.py`** (~5곳): 생성자에 포트/profile 주입. `_ensure_browser`(`:705-789`)/`_reconnect_page`(`:807-853`)/`_handle_browser_disconnect` 가 주입받은 `CDP_URL` 사용. 러너 인스턴스 2개 허용.
- **`src/ui/main_window.py`**: 포털별 러너 보유(`self.runner_nps`, `self.runner_nhis`) + 실행 중 가드.
- **`src/utils/log.py`**: 글로벌 콜백 → **러너별 라우팅**(러너 id 또는 채널 키로 분배).
- **SQLite**: 동시 쓰기 검증(긴 트랜잭션 시 `database is locked` 가능) 또는 포털별 DB 분리 검토.

### 5.3 제3 옵션 — 같은 Chrome + Playwright `new_context()` (권장 ❌)
별도 컨텍스트는 쿠키/페이지 격리되나:
- (a) **공동인증서 로그인이 profile `contexts[0]`에 묶임** — 새 컨텍스트는 세션 없음.
- (b) `Browser.setDownloadBehavior` 레이스(§3.4)·`kill_chrome` 전체 종료(§3.1) 잔존.
→ 근본 해결 아님. 배제.

---

## 6. 노력/위험 평가

- **노력**: MEDIUM-HIGH. `chrome_cdp.py` ~10곳 파라미터화 + `automation_runner.py` ~5곳 + `kill_chrome` PID화 + `log.py` 라우팅 + `main_window.py` 다중 러너 + SQLite 동시쓰기 검증.
- **위험**: 🔴 CDP 계층은 memory에 다수 취약점 기록(재사용-우선·force-kill 금지·junction 프로필). 특히:
  - `kill_chrome` PID/포트 기반 전환 — 잘못하면 8번 홈택스 실패( memory `feedback_chrome-cdp-setup`) 같은 재사용-우선 위반 재발.
  - 2번째 Chrome 프로필 분리 — junction/인증서 경로 꼬임 위험.
  - 회귀 필수: 골든 스냅샷(`scripts/capture_golden.py`, `docs/refactoring-handoff.md` §2 참조) + 라이브 단건 검증 + `PYTHONUTF8=1 python -m pytest tests/ -q`.

---

## 7. 권장 경로 — CLI 2-프로세스 우선 (최소 수정)

GUI 다중 러너보다 **CLI 2-프로세스**가 훨씬 가벼움:

- CDP 포트만 인자화(env var)하면:
  ```bash
  WTAX_CDP_PORT=9223 python src/automation/nps/nps_auto_cdp.py     # 터미널 A
  WTAX_CDP_PORT=9224 python src/automation/nhis/nhis_edi_auto_cdp.py # 터미널 B
  ```
- 각 프로세스가 자기 Chrome(각 포트+프로필) 띄움 → §3 블로커 자연 해소 + `log.py`/SQLite 글로벌 충돌도 **프로세스 분리로 자연 해소**(각자 메모리 공간).
- 변경 범위 = `chrome_cdp.py` 포트/profile 파라미터화 + `kill_chrome` 정밀화 정도. `main_window.py`/`log.py` 다중 러너 작업은 **불필요**(프로세스가 이미 격리).
- 효용(실제 병렬 처리 시간 단축)을 먼저 검증한 뒤, 필요 시 GUI 다중 러너로 확장.

> 주의: 공동인증서 인증은 OS 레벨 리소스 — 두 프로세스가 **동시에** 인증창을 띄우면 직렬 처리될 수 있음. 사용자가 한쪽씩 순차 로그인하면 무관. 각 Chrome 프로필에 인증서가 각각 등록되어 있어야 함.

---

## 8. 이어하기 가이드 (fresh 세션 첫 단계)

1. **본 문서(`docs/parallel-automation-handoff.md`) 전체 읽기.**
2. 현재 상태 확인:
   ```bash
   git log --oneline -5
   PYTHONUTF8=1 python -m pytest tests/ -q   # 기준선 회귀
   ```
3. **사용자 결정 확인**: 병렬 가치가 있는지, 경로(CLI 2-프로세스 vs GUI 다중 러너)는 무엇인지.
4. **CLI 2-프로세스 경로 선택 시** (권장 최소):
   - a. `src/utils/chrome_cdp.py` 의 `CDP_PORT`/`CDP_URL`/junction/profile을 env var(`WTAX_CDP_PORT`) 기반 파라미터화.
   - b. `kill_chrome()` 을 포트/PID 기반 정밀 종료로 전환 (memory `feedback_chrome-cdp-setup` 준수 — 살아있는 다른 인스턴스 kill 금지).
   - c. 각 CLI `main()`이 env var 읽어 자기 포트/profile 사용.
   - d. 두 터미널에서 동시 실행 → 병렬 동작 + 데이터 정합성(다운로드/DB) 검증.
   - e. 골든 스냅샷 회귀 + `pytest` + 커밋.
5. **동작 보존 필수**: 직렬(단일) 실행 경로는 100% 유지. 병렬 도입이 기존 단독 실행을 깨면 안 됨.

### 메모리 참조
- `feedback_chrome-cdp-setup` — CDP 재사용-우선·force-kill 금지·포트9223/junction. `kill_chrome` 정밀화 시 **필수 준수**.
- `feedback_browser-launch` — subprocess.Popen Chrome 실행.
- `project_parallel-nps-nhis-feasibility` — 본 문서의 memory 요약.
- `project_parallel-notfound-report` / `feedback_nhis-firm-mgmt-verify` — 아래 §9 구현의 memory 요약.

---

## 9. 수임처 탐색 실패(not-found) 처리 + 종합 리포트 (병렬 안정화)

병렬(2번) NPS+NHIS 자동화의 **선택 신뢰성·탐색실패 처리·종합 리포트**를 안정화한
운영 개선. 모두 `run_auto_batch`(`--auto`) 경로에 한정 — 단일 워크플로/대화형 경로는
회귀 0.

### 9.1 관리번호 정확일치 행만 선택 (blind first-row 클릭 제거)
- NHIS `_firm_selector.select_firm` / NPS `_workplace.select_workplace` 모두
  관리번호 검색 후 **첫 행을 무조건 클릭**하던 버그(→ 항상 첫 수임처 것만 수집)를
  수정. 관리번호(숫자 정규화)가 정확히 일치하는 행만 클릭, 일치 없으면 **이름 fallback**.
- NPS 헬퍼 `_workplace._find_workplace_row_by_mgmt`(`nexacro_get_grid_data` 재사용).
- 회귀: `tests/test_nhis_firm_selector_mgmt_match.py`, `tests/test_nps_workplace_mgmt_match.py`.

### 9.2 stale page 방지 + 전환 검증
- NHIS `run_auto_batch`: 매 iteration `close_popups(context)`로 메인(retrieveMain) 페이지
  재확보 (이전 수임처 워크플로우가 탭을 바꿔 page 가 stale 되는 것 방지).
- NPS는 Nexacro SPA(단일 page)라 `close_popups` 불필요; 대신 `_wait_workplace_closed`
  로 상태 settle. (Nexacro 페이지 읽기 검증은 신뢰 불가 — `_current_firm_name` 실측 전부
  None. 선택 로직 자체가 정합성 보장.)

### 9.3 탐색실패(not-found) 스킵 + 종합 리포트
- 양쪽 `run_auto_batch`가 `skipped` 리스트(사유: `오픈실패`/`미발견`/`오류`) 수집 후
  **공용 `src/automation/_parallel_report.py::emit_summary`** 호출 →
  (a) 사람용 요약 블록(`log` → 패널), (b) `__WTAX_RESULT__ {json}` 마커(stdout).
- `ParallelCliRunner._pump`가 마커 라인을 가로채 `result_summary(which,json)` 시그널로
  변환(로그 패널엔 raw JSON 미출력). `main_window._show_parallel_report`가 양쪽 합쳐
  **not-found 1건 이상이면 QMessageBox로 통합 안내**(없으면 조용히 종료).
- **★Qt 순서 보장**: `ParallelCliRunner.run()`이 `_readers` 스레드를 `join` 한 뒤
  `all_finished` emit → 마커(result_summary)가 항상 all_finished 핸들러보다 먼저 처리.
- (참고) CLI 진입점은 import 시 `sys.stdout.detach()` 재래핑을 해 pytest capture 를
  깨트리므로, 요약 로직은 stdout 재래핑 없는 `_parallel_report.py`로 분리해 테스트.

### 9.4 NPS not-found 시 페이지 리셋 (멈춤 방지) ★
- NPS는 수임처 미발견 시 사업장전환 모달(`ChangeBusi`) + "조회결과 없음" Nexacro alert
  이 **백그라운드(occluded) 창에서 닫히지 않아** 다음 수임처 진행이 막히고 멈추던 버그.
  (NHIS는 HTML 팝업이라 `close_firm_popup`으로 매번 닫아 정상.)
- 시도했던 `close_workplace_modal`(Escape/`BTN_MODAL_CANCEL` 클릭)은 no-op:
  `BTN_MODAL_CANCEL`은 **출력모달**(UHJE0002P1) 버튼이라 ChangeBusi에 안 닿고,
  `page.mouse.click`은 occluded 창에서 no-op인데 `{ok:True}` 반환, 키보드 press는
  Nexacro 내부 messageBox에 도달 못 함, `_wait_workplace_closed` timeout 거짓성공.
- **해결: `_workplace.reset_workplace_page(page)` = `page.goto(NPS_URL)` +
  `wait_for_nexacro_ready`**. 네비게이션은 입력이벤트가 아니라 모달/alert/occlusion
  무관하게 강제 종료, 세션(쿠키) 유지로 재로그인 불필요(`ensure_login_page`/`main()` 패턴).
  `run_auto_batch`의 모든 실패 경로(오픈실패/미발견/오류)에서 `continue` 전 호출.
- 교훈: Nexacro 모달의 **명시적 닫기는 신뢰 어려움 → 리로드 리셋이 가장 확실**.
  정상 선택은 그리드 행 dblclick의 사이드이펙트로 모달이 자동 닫히는 것에 의존.

---

## 10. 병렬 "전체 실행"·정지 버튼·정지 시 Chrome 종료 안정화 (라이브 검증 완료, 2026-06-25)

병렬(2번) 메뉴의 "전체 실행" 버그 2종 + 정지 버튼 비활성화 + 정지 시 Chrome 잔존를
고치고 **라이브(실제 22개 수임처 NPS+NHIS 동시 실행)** 로 검증했다. 모두 `--auto`
병렬 경로에 한정 — 단일 워크플로/대화형/선택건 회귀 0.

### 10.1 "전체 실행"이 firms=None 전달 → NPS 엉뚱한 회사 / NHIS 미실행 ★
- **원인**: `_on_start` 병렬 ALL 분기가 `parallel_runner.start(firms=None)` 호출.
  `firms=None` 이면 각 CLI가 포털에서 직접 수임처를 스크랩(레거시 단일-CLI 동작).
  - NPS: `nps_auto_cdp.py::run_auto_batch` 의 `firms is None` 분기가 `list_workplaces()`
    결과에서 **이름만 취합(관리번호 `wp["number"]` 폐기)** → `select_workplace` 가
    이름 부분일치(`nexacro_find_row` 의 `includes()`, 첫 매칭) 폴백 → 다른 회사 선택.
  - NHIS: `nhis_edi_auto_cdp.py::run_auto_batch` 의 `firms is None` 분기가 팝업 열고
    2초 대기 후 DOM 스크랩 → 새 Chrome(9224)에서 미렌더 → 빈 목록 → `return`(0건).
  - 선택건(SELECTED)은 GUI 테이블에서 `firms`+`mgmts` 명시 전달해 두 경로 우회 → 정상.
- **해결**: ALL 도 테이블 전체 행에서 `firms`+`mgmts` 조립(선택건과 동일 downstream).
  - `CompanyTableModel.get_all_clients()` / `CompanyTable.get_all_clients()` 추가
    (`_update_selected_clients` 와 동일 dict 형태: name/business_number/management_number/enabled).
  - `_on_start` ALL 분기: `get_all_clients()` → 비활성(`enabled=False`) 제외 →
    `firms`/`mgmts` 조립 → 빈 목록 가드 → `parallel_runner.start(firms=, mgmts=)`.
  - 관리번호가 CLI까지 전달되어 NPS `_find_workplace_row_by_mgmt` 정확일치 경로 사용.
- 회귀: `tests/test_company_table_get_all_clients.py`.

### 10.2 정지 버튼이 비활성/숨김 → 클릭 불가 ★
- **원인**: 병렬 시작 시 `set_run_active(True)` + `set_buttons_enabled(False)` +
  `set_selected_run_mode(False)` 연달아 호출이 `full_run_btn`(=정지 버튼)을
  `setEnabled(False)` + `setVisible(False)` 로 만듦. `set_selected_run_mode` 가
  `full_run_btn`/`selected_run_btn` 가시성을 **같이 묶어** 처리하는 게 근본 원인.
  정지 시그널(`stop_requested`→`_on_stop`→`parallel_runner.stop()`) 자체는 정상이었으나
  버튼이 안 눌렸다. 비-병렬은 `pause_btn` 을 써 이 시퀀스를 안 거쳐 정상.
- **해결**: `CompanyTable.set_running(active)` 추가 — 정지 버튼(`full_run_btn`)을
  실행 중 항상 보이고 활성화('정지'/빨강)하도록 위젯별 직접 제어로 결합 우회.
  `_on_start` ALL·`_on_selected_run` SELECTED·`_on_parallel_finished` 의 3-호출
  시퀀스를 `set_running(True/False)` 로 교체. `active=False` 는 기존 idle 복원과 동등.
- **회귀 방어**: `_on_phase_selected` 맨 앞에 `parallel_runner.is_running()` 가드 추가 —
  실행 중 사이드바 클릭으로 phase 가 바뀌어 정지 버튼이 다시 숨겨지는 것 방지.
- 회귀: `tests/test_company_table_set_running.py`.

### 10.3 정지 시 Chrome 이 닫히지 않음 → 포트 기반 정밀 종료 ★
- **원인**: `ParallelCliRunner.stop()` 은 `taskkill /PID <cli> /T` 로 CLI 트리 종료.
  그러나 **재사용(reuse)되거나 분리(detached) 실행된 Chrome 은 CLI 자식 트리에 없어**
  죽지 않음(버튼은 복원되나 Chrome 창이 남음). `_launched_pids`(자식 CLI 메모리)를
  GUI 가 못 봐 `kill_chrome(port=)` 도 무력.
- **해결**: `chrome_cdp.kill_chrome_by_port(port)` 추가 — `netstat -ano` 에서 해당 포트
  LISTENING 소켓의 PID(=Chrome 브라우저 프로세스)를 찾아 `taskkill /PID /T /F`.
  `stop()` 에서 nps_port/nhis_port 각각 호출. **정지=완전중단일 때만 kill**;
  자연 완료(`_on_parallel_finished`) 시엔 Chrome 유지해 다음 실행이 세션 재사용.
- memory `feedback_chrome-cdp-setup`(재사용-우선·force-kill 금지)은 **런치 경로**에
  한정 — 정지(명시 중단) 시 kill 은 별개이며, 기존 의도(taskkill /T 로 죽이려 했던)와 일치.
- memory `feedback_chrome-kill-by-port`.

### 10.4 라이브 검증 결과 (실제 22개 수임처 NPS+NHIS 동시 실행)
- 산출물: `Desktop/국민연금_YYYYMM/<수임처>/{결정내역통보서_*.xlsx, *_출력.pdf}`,
  `Desktop/국민건강보험_YYYYMM/<수임처>/가입자고지내역서_건강_*.pdf`.
- **수임처 정합성 전수 감사**(`debug/audit_firm_match.py`, gitignore 됨): 폴더명 ↔
  DB 수임처 ↔ 파일 내 사업장관리번호+사업장명 교차검증.
  - **사업장관리번호(고유 식별자) 44/44 전부 일치** → 엉뚱한 회사 자료 0건.
    원래 NPS 엉뚱한 회사 버그(§10.1) 완전 해소 확인.
  - 사업장명(이름)은 4개 회사(8파일)에서 포털 등록명 vs DB명 표기차이
    (`주식회사`↔`(주)`, `(고양지점)`/`(박영미)` 생략, 영문 병기) — 관리번호 동일로
    모두 **같은 회사**(데이터 정확). 정합성과 무관한 라벨링 차이.
- 정지 버튼: 🔴 "정지" 클릭 → `[병렬] 정지 요청` 로그 + Chrome 2개 종료 + 버튼 복원 확인.

---

## 11. NHIS 월 선택 무시("항상 당월") 수정 (라이브 검증 완료, 2026-06-25)

다른 월 선택 시 NPS 는 해당 월을, NHIS 는 **항상 6월(당월)** 만 가져오던 버그.
병렬(2번) 메뉴에서 발생. 원인 2종(코드 교차검증 + 라이브 검증 완료).

### 11.1 병렬 NHIS year/month 풀러밍 5곳 누락 (확정)
병렬 경로는 애초에 year/month 가 연결된 적이 없었다(NPS 는 전 단계 풀러밍).
NPS 와 동일하게 미러링해 5곳 보수:
- `src/ui/workers/parallel_cli_worker.py:58-59` — NHIS `_spawn` 에 `None,None` 대신
  실제 `year, month` 전달.
- `nhis_edi_auto_cdp.py` argparse — `--year`/`--month`(int) 추가.
- `main()` --auto 분기 — `run_auto_batch(..., year=args.year, month=args.month, ...)`.
- `run_auto_batch` 시그니처 — `*, firms, year, month, mgmts=None` (+로그).
- run_auto_batch 내 `run_single_firm_workflow(..., year=year, month=month)`.
- 단독 NHIS(`nhis_edi.py`)·`automation_runner`·`gui_main.py`(이미 --year/--month 파싱)는 변경 불필요.

### 11.2 받은문서 월 매칭 정규화 (`_find_target_row`) ★
`_doc_download.py::_find_target_row` 가 `row.textContent.includes("202605")` raw 매칭이라
포털 날짜(`2026-05-15`/`2026.05`/`2026년05월`)와 안 맞아 조용히 실패. 숫자 정규화 매칭으로 교체:
`(row.textContent||'').replace(/\D+/g,'').indexOf(target) !== -1` → 구분자 무관하게 YYYYMM 매칭.
실패 메시지에 `rows seen: N` 추가. 당월 회귀 없음(기존 매칭의 상위집합).
월 계산은 `_resolve_period(year, month) -> (y, m, yyyymm)` 헬퍼로 추출(None→당월 폴백)해 테스트 가능.

### 11.3 Part 3(조회기간 선택) — 불필요 판정 (Case A)
과거월 문서가 받은문서 그리드에 없을 가능성을 라이브 dump 로 확인하려 했으나, **5월 실행에서
문서가 정상 매칭·다운로드됨** → 받은문서는 다월치를 표시하고 있었고 Part 2 정규화로 충분.
조회기간 선택 코드는 추가하지 않음.

### 11.4 라이브 검증 결과 (2026-05 병렬 실행)
- 폴더명 `국민건강보험_202605` / `국민연금_202605` (year/month 가 save_dir 도달).
- 파일명 `가입자고지내역서_건강_202605.pdf` / `결정내역통보서_202605.xlsx`.
- NHIS PDF 내용 `통 보 년 월 2026년 05월` / NPS 엑셀 고지년월(A4) `2026-05` → 실제 5월 데이터.
- 관리번호 전건 일치(엉뚱 회사 0건) → 10.1 수정과 함께 정합성 유지.
- 회귀: `tests/test_nhis_period_matching.py`(`_resolve_period` YYYYMM 생성·폴백 + 숫자정규화 매칭 계약).

---

## 12. NHIS 단독 모듈 — not-found 다음 수임처 스킵(N+1 lag) 수정 (라이브 검증 완료, 2026-06-25)

건강보험 **단독(개별) 모듈** 실행 시, 못 찾는 수임처(예: 근린건축) **바로 다음** 회사의
데이터를 받지 않고 **다다음** 회사는 정상 다운로드하던 "1-펌 래그" state-bleed 버그 수정.

### 12.1 근원 원인
`src/workflows/nhis_edi.py::NhisEdiWorkflow.run_single` 가 `select_firm` 실패(not-found) 시
`nhis_edi.py:57-60`에서 조기 `return False` → `run_single_firm_workflow` 를 건너뜀. 그 함수
끝의 `we_btn_relogin` 클릭(`_doc_download.py:468-471`)이 **retrieveMain 페이지를 리셋하는
유일한 지점**이라, not-found 시 리셋이 안 일어나 페이지가 stale → 다음 수임처(N+1)의
`select_firm` 클릭이 전환을 일으키지 못해 잘못된/없는 자료로 진행. N+1 의 run_single_firm_workflow
가 끝에 relogin 을 눌러 페이지를 리프레시 → N+2 정상(자가치유 = "1-펌 래그"의 정체).
(`open_firm_selector` 의 relogin 리셋은 `has_firm` 게이트 탓에 not-found 직후엔 동작 안 함.)
**2차 버그**: `run_single` 이 `run_single_firm_workflow` 의 False 결과를 무시하고 `True` 반환 →
다운로드 실패가 "완료"로 위장(masking) → N+1 이 스킵으로 인지됨.

### 12.2 수정 — 매 run_single 시작 시 페이지 리셋 (Part 1) ★
`reset_main_page(page)` 헬퍼(`_doc_download.py`) — `page.goto(NHIS_EDI_MAIN, domcontentloaded)`.
NPS `reset_workplace_page` 와 달리 **wait_for_nexacro_ready 없음** — NHIS Nexacro는 '받은문서'
웹EDI 탭에서만 로드되므로 retrieveMain(일반 HTML)에서 nexacro 대기 시 매번 30초 타임아웃
(속도 저하 + 시간초과 로그)됨. goto 직후 open_firm_selector 가 수임사업장선택 버튼을
폴링(최대 25s)하므로 안정성 영향 없음(2026-06-28 §13.3 참고).
`run_single` 이 `close_popups` 직후·`open_firm_selector` 직전에 매번 호출 → 이전 수임처
(성공/not-found/예외 무관)가 남긴 stale 상태를 지우고 **항상 로그인 사업장에서 시작**.
state-bleed 클래스 전체를 근본 차단(not-found 경로만 고치면 다른 조기 exit 에 재발).
`_common_edi.py` 에서 재수출.

### 12.3 다운로드 실패 masking 해소 (Part 3)
`run_single` 이 `run_single_firm_workflow` 결과를 검사해 False 면 `state.fail_step` +
`return False`(`workflow_ok` 플래그). cleanup(`_close_edi_tabs`)은 성공/실패 무관 항상 실행.
→ not-found 다음 수임처가 잘못된/없는 자료로 끝나도 이제 "실패"로 정상 보고.

### 12.4 전환 검증+retry (Part 2) — 후순위 미뤄둠
`select_firm` 후 스위치 반영 검증(`current_firm_name`/`name_match`) + 불일치 시 리셋·재시도는
주로 **병렬/백그라운드 Chrome 의 click-no-op** 방어용. 보고된 **단독(포어그라운드) 버그는
패턴이 분명해 stale-page(Part 1) 가 원인** → Part 1+3 로 해결. 추후 무작위 실패 시 추가
(헬퍼를 `_firm_selector.py` 로 이동해 공유).

### 12.5 라이브 검증 결과 (2026-06-25)
단독 NHIS 메뉴 선택건 `[오성아구뽈찜 → 근린건축(not-found) → 주식회사 더브라이트]` 실행:
- 오성아구뽈찜 ✓ 다운로드(관리번호 14543005760 일치).
- 근린건축 ✗ not-found(폴더 없음, 정상 실패).
- **주식회사 더브라이트 ✓ 정상 다운로드(관리번호 69588014640·사업장명 일치)** ← 예전엔 스킵.
→ N+1 lag 해소 + 데이터 정합성 확인. 회귀: 기존 `pytest` 71건 통과, 병렬 경로(`run_auto_batch`) 영향 없음.

---

## 13. 직렬/GUI 경로 안정화 (2026-06-28)

병렬(`--auto`)은 검증 완료 상태였으나 **직렬(GUI Phase 3)·단독 CLI 경로**에서 발견된
버그 3종 수정. 모두 직렬 경로에 한정, 병렬 회귀 0.

### 13.1 GUI 로그 2배 중복 — `log()` mutually exclusive 라우팅 ★
- **원인**: `log()` 가 `print()` 와 `_log_callback()` **둘 다** 호출. 직렬 경로에선
  `AsyncWorker.run()` 이 `sys.stdout` 을 `LogCapture` 로 교체해 `print()` 도
  `log_message.emit()` 으로 수렴 → callback emit(1) + LogCapture emit(1) = **동일 로그 2회**.
  병렬은 별도 프로세스라 callback=None → 1배(그래서 병렬이 깨끗해 보였음).
- **수정**(`src/utils/log.py`): callback 설정 시 callback 만 호출 + `sys.__stdout__` 미러,
  print 스킵(상호배제). callback None(CLI/병렬 자식) 시 print 유지. 단일 파일 변경.
- **불변**: `log.py`/`async_bridge.py`(LogCapture)/`automation_runner.py`(set_log_callback)
  3파일 맞물림 — print 재추가·callback 중복등록 시 중복 재발.

### 13.2 NHIS 로그인 "무한 새로고침 + 보안프로그램 로딩 루프" ★
- **증상**: 공동인증서 로그인 버튼 누르면 페이지가 무한 리로드, 보안프로그램 로딩 on/off.
  로그인 완료 불가 → 단건 다운로드(단독 메뉴3)·선택건/전체 실행 전부 차단.
- **원인**: 보안프로그램(Veraport/TouchEn 계열)이 `navigator.webdriver === true` 감지 →
  강제 리로드 루프. 노출 경로 2개:
  1. **커밋 `a2f9c11` 회귀** — `chrome_cdp.py:_attempt_launch` 에서
     `--disable-blink-features=AutomationControlled`(webdriver 원천 차단)를 `--test-type`
     (탐지신호라 제거 맞음)과 **함께 묶어 삭제**. stealth add_init_script 에 의존했으나
     그건 미래 네비게이션에만 적용 → 첫 로그인 페이지엔 webdriver 노출(타이밍 갭).
  2. **GUI 경로 stealth 누락** — `AutomationRunner._ensure_browser`/`_handle_browser_disconnect`
     는 `connect_over_cdp` 직후 stealth 미적용(CLI 경로는 `connect_page` 로 적용 중).
  - 병렬(포트9224 빈 프로필 + stealth)은 안 깨지고 직렬/단독(포트9223 실제 프로필)에서만 루프.
- **수정**:
  - `src/utils/chrome_cdp.py` — `--disable-blink-features=AutomationControlled` 만 복원
    (`--test-type` 은 제거 유지). 단일 실행 지점이라 모든 경로 일괄 적용, 첫 로드부터 webdriver 0.
  - `src/ui/workers/automation_runner.py` — `_ensure_browser`(2곳)·`_handle_browser_disconnect`
    에 `stealth_all_pages(context)` 추가(모듈 임포트). `register_auto_stealth` 는 핸들러 누적
    (§3.7) 위해 생략.
- **주의**: `launch_chrome(force=False)` 은 9223 Chrome 재사용 → 수정 검증 시 기존 Chrome
  완전 kill 후 fresh launch 해야 플래그 적용.
- **폴백**: 코드 수정으로도 루프가 끊기지 않으면 환경적(실제 프로필 보안프로그램 확장/락)
  → NHIS 전용 클린 프로필(병렬 `_prepare_user_data_dir` 패턴)로 전환.

### 13.3 reset_main_page 매 루프 30초 지연 — retrieveMain nexacro 대기 제거 ★
- **증상**: §12 reset 도입 후 "retrieveMain 리셋" + "Nexacro 프레임워크 로딩 시간 초과"
  로그가 매 수임처마다 뜨며 속도가 크게 저하.
- **원인**: `reset_main_page`(`_doc_download.py`)가 retrieveMain(일반 HTML)에서
  `wait_for_nexacro_ready()` 호출 → NHIS Nexacro는 '받은문서' 웹EDI 탭에만 있어 **항상 30초
  타임아웃**. 반환값 무시라 동작엔 지장 없으나 30초/루프 낭비. §12 도입 시 NPS 패턴을 그대로
  이식한 실수(NPS main 은 Nexacro, NHIS retrieveMain 은 아님).
- **수정**(`src/automation/nhis/_doc_download.py`): `wait_for_nexacro_ready` 호출 + 미사용
  임포트 제거. 핵심인 `goto(NHIS_EDI_MAIN)` 은 보존(N+1 lag 수정 유지), 이후
  open_firm_selector 버튼 폴링이 준비 보장.
- 회귀: `pytest` 71건 통과.

---

## 부록: 관련 파일 빠른 참조

- **CDP 핵심**: `src/utils/chrome_cdp.py`(`CDP_PORT`:12, `kill_chrome`:143, `connect_page`:267, `launch_chrome`:198)
- **러너**: `src/ui/workers/automation_runner.py`(`_ensure_browser`:705, `_reconnect_page`:807, `_disconnect_browser`:477, `cleanup_session`:494)
- **페이지 선택**: `nps/_common.py:87`, `nhis/_common_edi.py:94`, `chrome_cdp.py:278`
- **탭 정리 충돌**: `nhis/_doc_download.py:470`(`_close_edi_tabs`), `nps/_download.py:614`
- **다운로드 레이스**: `nps/_download.py:336`(`_setup_cdp_download`), `nhis/_doc_download.py:234`(`_setup_crownix_download`)
- **로그 글로벌**: `src/utils/log.py:14`
- **설정**: `src/config.py:27`(DB_PATH), `:34`(PORTAL_URLS)
- **GUI 진입**: `src/ui/main_window.py:35`(단일 runner), `:419`(`_on_start`)
- **세션/핸드오프**: `docs/refactoring-handoff.md`(골든 스냅샷 회귀 기법 — 병렬 도입 후 회귀에 재사용)
- **§10 (전체실행/정지/Chrome종료)**:
  - `src/ui/widgets/company_table.py` — `CompanyTableModel.get_all_clients`, `CompanyTable.get_all_clients`(forwarder), `CompanyTable.set_running`
  - `src/ui/main_window.py` — `_on_start` ALL 분기(firms/mgmts 조립), `_on_selected_run`/`_on_parallel_finished`(`set_running` 교체), `_on_phase_selected`(is_running 가드)
  - `src/ui/workers/parallel_cli_worker.py` — `ParallelCliRunner.stop`(`kill_chrome_by_port` 호출)
  - `src/utils/chrome_cdp.py` — `kill_chrome_by_port`(netstat → 포트 LISTEN PID → taskkill /T /F)
  - 회귀: `tests/test_company_table_get_all_clients.py`, `tests/test_company_table_set_running.py`
- **§11 (NHIS 월 선택)**:
  - `src/ui/workers/parallel_cli_worker.py` — NHIS `_spawn` 에 year/month 전달(58-59)
  - `src/automation/nhis/nhis_edi_auto_cdp.py` — `--year/--month` argparse·main·`run_auto_batch(*,firms,year,month,mgmts=None)`·`run_single_firm_workflow` 호출
  - `src/automation/nhis/_doc_download.py` — `_find_target_row` 숫자정규화 매칭, `_resolve_period` 헬퍼
  - 회귀: `tests/test_nhis_period_matching.py`
- **§12 (NHIS 단독 not-found N+1 lag)**:
  - `src/automation/nhis/_doc_download.py` — `reset_main_page(page)` 헬퍼(goto NHIS_EDI_MAIN; nexacro 대기는 2026-06-28 §13.3 제거)
  - `src/automation/nhis/_common_edi.py` — `reset_main_page` 재수출
  - `src/workflows/nhis_edi.py` — `run_single` 시작 시 리셋(Part 1) + 다운로드 실패 시 `return False`(Part 3, workflow_ok)

## 14. 병렬(2번) EDI 다운로드 누락 안정화 (2026-07-03)

병렬 전체 실행에서 **(BUG1) 순서상 앞 수임처 몇 개 엑셀 누락** + **(BUG2) 순서 무관 NPS raw(통합엑셀) 간헐 누락** 수정. 6-에이전트 조사 + 코드/PDF 검증으로 규명.

### 14.1 공단EDI 공유 폴더 파일 레이스 (회귀: 커밋 5ebc6b4) ★두 버그 공통
5ebc6b4가 NPS·NHIS를 **같은 `공단EDI_{YYYYMM}/{수임처}/` 폴더**로 통합. 두 Chrome이 동시 수임처를 같은 폴더에 쓰는데, 다운로드 완료 감지가 `os.listdir()` set-diff(`done[0]`, 파일 소유권 무관)라 — (1) NHIS `_wait_and_rename_pdf`가 PDF 저장 후 **non-`.pdf` 파일 전부 삭제** → NPS `.xlsx` 삭제, (2) NPS `_wait_for_download`가 NHIS PDF를 `done[0]`로 grab 해 잘못 리네임. 두 프로세스가 같은 firms 순서로 동시 출발해 앞 1~3번 수임처에서 overlap 최대(BUG1), 이후 재동기화마다 간헐(BUG2).
- **Fix 1(해결)**: `make_save_dir(site, client, …, subdir=)` 추가 — 병렬(`--save-site`) 시 포털별 하위폴더 `공단EDI_{YYYYMM}/{수임처}/{국민연금|국민건강보험}/` 로 분리. NPS `_SAVE_SUBDIR`/NHIS `_doc_download._SAVE_SUBDIR` 전역(단독 시 None). 두 Chrome이 다른 폴더에 써 레이스 원천 제거.

### 14.2 NPS 시작 준비 게이트 부재 (BUG1, NPS)
NPS `main()`이 로그인 직후 `run_auto_batch` 진입, `wait_for_nexacro_ready`(_common.py, 존재) 호출 안 함 → 콜드 프로필 시 첫 수임처 no-op 클릭. NHIS는 `wait_firm_selector_ready` 게이트(주석이 BUG1 증상).
- **Fix 2**: NPS `main()`에 `await wait_for_nexacro_ready(page)` 추가(NHIS 게이트와 대칭). `is_first` 파라미터는 데드코드.

### 14.3 NPS 다운로드 실패 마스킹 (BUG2, NPS)
`run_single_workplace`가 `download_final_integrated` 반환값 버리고 `run_auto_batch`가 무조건 `completed+=1` → NPS 누락이 항상 '완료'로 마스킹. NHIS는 ok 검사→skipped(비대칭 → BUG2가 NPS-only).
- **Fix 3**: `run_single_workplace`가 `bool(integ.get("excel"))` 반환; `run_auto_batch`(+`run_full_auto`)가 `if not ok: skipped.append({reason:"다운로드실패"})`. emit_summary 가 skipped 자동 직렬화 → 리포트에 드러남.

### 14.4 NPS 엑셀 경로 강화 + CDP 세션 정리 (방어·2차)
- **Fix 4**: `_save_with_modal` 모달 출현 검증 + `EXCEL_CLICK_RETRIES=3`; 리네임 후 `_is_valid_xlsx`(zip `PK\x03\x04`+size≥2048) 검증(PDF `%PDF-` 게이트와 동일 구조).
- **Fix 5**: `_setup_cdp_download`가 `(before, cdp)` 반환; `_save_with_modal`/`download_pdf_from_preview` try/finally `cdp.detach()`(NHIS 패턴. 예전엔 세션 누수 ~44/22clients).
- 회귀: `tests/test_save_path_subdir.py`, `tests/test_nps_download_validation.py`, `tests/test_nps_masking.py`. pytest 94/94. 라이브(6월 22개 전부 정상, 사업자번호 교차검증 22/22 일치) 확인.
- **★교훈**: "함께 보관" 목적의 공통 폴더 통합은, 다운로드 감지가 파일 소유권 기반(또는 CDP 이벤트)이 아니라 listdir diff 면 **레이스**. 통합 폴더 내 쓰기 주체별 하위폴더 분리 필수.

### 14.5 CLI 진입점 detach `__main__` 이동 (보조)
NPS/NHIS CLI 진입점이 module-level `sys.stdout.detach()` 재래핑을 해 import 시 pytest capture 파괴(test_parallel_notfound_report 주석). SWTA 패턴대로 `if __name__=="__main__":` 블록으로 이동 → import-safe + NPS 제어흐름 테스트(test_nps_masking) 가능.

## 15. management_number override 보존 + 병렬 자가방어 (2026-07-03)

2번 병렬에서 근린건축·해윤컴퍼니 미발견 원인 조사 → **management_number 컬럼이 자동 경로로 단 한 번도 채워진 적 없음** 발견(get_management_number 의 auto-calc `biz+'0'`가 가림). §10.4 "44/44 일치"도 DB 컬럼이 아니라 line 432 주입 auto-calc 측정값.

### 15.1 새로가져오기 management_number wipe (핵심 데이터 결함)
`_handle_refresh_clients`(automation_runner.py)가 `DELETE FROM clients` 후 INSERT. INSERT(db.py)가 management_number 컬럼 안 넣어 DEFAULT '' → **매 새로가져오기마다 override 전부 wipe**. DB 증거: 24개 행 created_at 전부 2026-07-02 22:53:29(일괄재삽입). `upsert` UPDATE 분기는 mgmt 보존하지만 새로가져오기가 pre-delete 해 UPDATE 분기 도달 불가.
- **Fix A(해결)**: `ClientRepository.replace_clients_preserving_mgmt`(db.py) — DELETE 직전 {name: management_number} snapshot → INSERT 후 같은 name에 `update_management_number` 로 restore. `_handle_refresh_clients`가 호출. `_reset_batch`(:710)의 client DELETE 는 list phase 전용인데 run 메서드가 list phase 진입 즉시 return 시켜 **사실상 닿지 않음** → 유일 wipe는 새로가져오기.
- 회귀: `tests/test_refresh_preserve_mgmt.py`(보존·누락행삭제·report_cycle 갱신·biz_to_mgmt_no·override 우선).

### 15.2 biz+'0' 유효성 (필요충분조건 아님)
정상 단일사업장은 NPS xlsx 8/8·NHIS PDF 22/22로 `biz+'0'`가 실제 사업장관리번호. **하지만 지점/추가사업장은 끝이 1,2,…** 로 `biz+'0'` 틀림 → override 필수. `biz+'0'` auto-calc 는 필요충분조건 아님.
- **Fix B(방어)**: 병렬 mgmts 소비(`main_window._on_start` ALL/SELECTED)가 `c.get("management_number") or biz_to_mgmt_no(biz)` 로 자가방어(line 432 의존 제거, :730 비병렬 패턴과 동일). 현재 동작 변화 없음(방어).

### 15.3 미발견 수임처 판별 (라이브)
- **해윤컴퍼니**: 포털 자체 미검색 → 정당 미발견(등록 확인 필요).
- **행복이지**: 데이터 정상 + 단건(선택건) 실행 OK → 전체 병렬 실패는 **간헐적 타이밍**(BUG1/BUG2 계열), mgmt 문제 아님. 전체 병렬은 단건 보충 운영.
- **근린건축**: 단건 실행 + 포털 확인으로 판별(단건 OK→간헐, 단건도 실패+미검색→정당).
- 회귀: pytest 99/99(94+5). 라이브(6월 22개 정상, 행복이지 단건 OK) 확인.

### 15.4 고용보험 EDI(phase 5) — 단독 + 병렬 3-way 완료

엑셀 v3(C86~H106)에 정의된 근로복지공단 고용보험 EDI 자동화. **단독(phase 5)** 및
**병렬(phase 2, 3-way NPS+NHIS+고용보험)** 모두 라이브 검증 완료.

- **식별자**: `comwel_edi`, 패키지 `src/automation/comwel/`, 어댑터 `src/workflows/comwel_edi.py`
- **상태**: 라이브 검증 완료 — ClipReport 리포트 뷰어(`ifr_Report` 프레임)를 통한
  PDF+엑셀 다운로드, 병렬 3-way 동시 실행 모두 검증. 핵심 셀렉터/흐름:
  - 로그인 감지: `header_btn_logout` 가시 여부 (URL 고정, 라이브 검증)
  - 20209 진입: 메인 대시보드 퀵메뉴 (대시보드 로딩 대기 30초 폴링)
  - 사업장 전환: 관리번호 입력 → 사업장조회 → WZ0101_P01 팝업 선택
  - **본 화면 조회(btnSearch) 필수** — 사업장 선택 후 데이터 로드 (라이브 발견)
  - 고용 탭: `w2tabcontrol_active` 체크 후 클릭 (중복 클릭 방지)
  - 지원금 팝업: "지원금" 키워드 매칭 (라벨/동적 id 가변)
  - 인쇄: "인쇄하기" → WZ0203 모달 → ClipReport 전용 버튼(PDF/엑셀) 직접 다운로드
- **주의**: 버튼 id(`wq_uuid_XXXX`)는 동적 → 텍스트/키워드 매칭 사용.
- **viewport 필수**: 근로복지공단 반응형 헤더는 viewport 좁으면 GNB 숨김.
  `--window-size=1920,1080`(Chrome 실행 인자) + `set_viewport_size`(Playwright) 이중 방어.
- **병렬 편입 완료** (3-way NPS+NHIS+고용보험):
  - `parallel_cli_worker.py`: `_comwel_port=9225`, `_spawn("comwel", ...)`, `_pump` prefix `[고용]`, `stop()`에 `kill_chrome_by_port(9225)`
  - `main_window.py`: `parallel_runner.start(..., comwel_port=9225)`, 리포트/라벨 3-way 대응
  - `_download.py`: `_SAVE_SITE/_SAVE_SUBDIR` 모듈 변수화 → 병렬 시 `공단EDI/.../고용보험/` 하위폴더
- **저장 경로**: 단독 `고용보험_{YYYYMM}/{수임처}/` / 병렬 `공단EDI_{YYYYMM}/{수임처}/고용보험/`
- **관리번호**: 사업자번호+`'0'`(`biz_to_mgmt_no`) — NPS와 동일 규칙, 별도 DB 컬럼 불필요
- **위하고 병합**: Phase 6(급여자료입력)에서 `.xls` 파싱 → 고용보험 컬럼에 `-지원금+환수금` 반영
