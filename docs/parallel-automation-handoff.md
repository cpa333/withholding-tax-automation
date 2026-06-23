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
