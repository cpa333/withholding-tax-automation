# 리팩토링 핸드오프 — 골든 스냅샷 회귀 + Wave 3/4 이어하기

> **목적:** 이 문서는 원천징수자동화 리팩토링을 **다른 세션에서 그대로 이어**할 수 있도록, 현재 위치·핵심 결정·남은 작업(Wave 3/4)·골든 스냅샷 회귀 방법을 자립적으로 정리한다. 코드를 수정하려면 먼저 이 문서 전체를 읽을 것.
>
> **작성 시점:** 2026-06-20. Wave 0-2 완료·push·E2E 검증 완료. Wave 3/4 pending.

---

## 0. 한눈에 보기

| Wave | 상태 | 내용 | 위험 |
|---|---|---|---|
| 0 | ✅ 완료(push) | pytest 인프라 + BatchEngine 단위테스트 + 골든 스냅샷 스캐폴드 | - |
| 1 | ✅ 완료(push) | 데드코드 7종 제거(−2,488줄) + 위생 + 문서 동기화 | - |
| 2 | ✅ 완료(push) | phase_id 매직넘버 → PhaseCapability 메타데이터화 | - |
| **3** | ⏳ pending | **engine↔runner 통합 + 크래시 복구 DB 복원** | 🔴 높음 (실행 경로 변경) |
| **4** | ⏳ pending | 메뉴별 구조 정리(동작 보존) | 🟡 중간 (자동화 코드 수정) |

- Wave 0-2는 서브에이전트 E2E 검증(4에이전트 전원 PASS)으로 **기능 무결 확정**. 결정적 증거: `git diff 8560743..HEAD --stat src/automation/ src/batch/` = 자동화 플로우/데이터 레이어 **0행 수정**.
- Phase 4-8은 현재 UI 잠금 상태(`ui_locked=True`). 잠금 해제는 사용자 별도 지시 전까지 유지.

---

## 1. 핵심 결정 (사용자 확정 — 변경 금지)

| 항목 | 결정 |
|---|---|
| **범위** | 구조 통합까지 (동작 보존). 동작 변경 픽스(데이터 정확성·보안·견고성)는 **별도 후속**(§5 Out of Scope) |
| **CLI/GUI** | 둘 다 현상 유지 — 경로 통합 안 함, 차이는 문서로 명확화 |
| **검증** | 골든 스냅샷(DB/로그) + 핵심 경로 단위테스트(`tests/` 신규) |
| **크래시 복구** | DB 한정 복원 — 보이는 흐름 유지, traceback/partial-reset DB 기록만 추가 |

**원칙:** 동작 보존 최우선. 모든 항목은 `[동작보존]` / `[지연:동작변경]` 태그. `[지연]`은 본 리팩토링에서 수정하지 않음.

---

## 2. 골든 스냅샷 회귀 (회귀 검증 기법)

### 2.1 개념
"정답(golden) 기준선"을 찍어두고, 코드 변경 후 같은 dry-run의 **결과 상태**를 재캡처해 diff. 차이가 없으면(휘발성 필드 제외) 동작 보존 확정.

### 2.2 현재 구현 — `scripts/capture_golden.py` (Wave 0에서 작성, 정확한 CLI)

**서브커맨드:**
- `capture --db <DB> --label <이름> [--out tests/golden]` — DB 상태를 정규화 JSON으로 캡처
- `compare --base <base.json> --curr <curr.json>` — 두 스냅샷 diff. 종료코드 0=동일, 1=차이

**캡처 대상:** `batches` / `jobs` / `steps` / `clients` 4개 테이블 전 컬럼(`SELECT * ORDER BY id`).
**정규화(휘발성 → `<volatile>`):** `started_at`, `completed_at`, `created_at`, `updated_at`, `duration_secs`.
**compare 출력:** 테이블별 행수 + `jobs_by_status`/`steps_by_status` 분포 + jobs/steps 행 단위 정밀 diff(`[추가]/[제거]/[행 변경]`).

### 2.3 워크플로
```bash
# 1) 기준선(변경 전) — 사용자가 실제 dry-run 후
PYTHONUTF8=1 python scripts/capture_golden.py capture --db data/withholding_tax.db --label baseline --out tests/golden
# 2) [리팩토링 수행]
# 3) 동일 dry-run 재실행 후 재캡처
PYTHONUTF8=1 python scripts/capture_golden.py capture --db data/withholding_tax.db --label wave3 --out tests/golden
# 4) 비교
PYTHONUTF8=1 python scripts/capture_golden.py compare --base tests/golden/baseline.json --curr tests/golden/wave3.json
```
- **DB 경로:** dev 모드 `data/withholding_tax.db`(repo 루트 기준) / frozen `%LOCALAPPDATA%\원천징수자동화-data\data\withholding_tax.db` (`src/config.py:17-28`).
- `tests/golden/`은 `.gitignore` 처리(스냅샷에 실제 수임처 PII 포함 가능).

### 2.4 현재 상태 (중요)
- **골든 기준선은 아직 캡처되지 않음.** Wave 0은 스크립트만 만들었고, 실제 dry-run은 **사용자가 실행**해야 함(로그인/브라우저 필요 → 자동 불가).
- **현재 dry-run 가능 phase = 1, 2, 3만.** Phase 4-8은 `ui_locked=True`로 사이드바 버튼 비활성 → GUI dry-run 불가(잠금 해제 전까지).

| Phase | ui_locked | GUI dry-run(골든 캡처) |
|---|---|---|
| 1 (수임처 리스트) | False | ✅ 가능 |
| 2 (국민건강보험 EDI) | False | ✅ 가능 |
| 3 (국민연금 EDI) | False | ✅ 가능 |
| 4-8 | **True** | ❌ 잠금 |

### 2.5 잡히는 것 / 안 잡히는 것
- ✅ job/step 상태 전이, 실행된 step 목록, 완료/실패/스킵 건수, DB output 파일 — **오케스트레이션 수준 동작**.
- ❌ 실제 다운로드 파일 내용, 라이브 브라우저 상호작용, 모달 처리 성공 여부(step 결과에 영향 안 줬으면), 타이밍.

### 2.6 먼저 vs 병행 — **먼저(선행) 권장, 특히 Wave 3는 필수**
- 기준선은 "변경 전" 상태이므로 **본질적으로 리팩토링보다 먼저**여야 함(병행 불가).
- Wave 3는 job 루프/step 실행 **경로 자체**를 바꾸므로 골든이 정확히 탐지하는 영역.

### 2.7 가벼운 대안 (골든 dry-run이 부담일 때) — 단위테스트 확장
- 골든은 매번 dry-run(로그인)이 필요해 무거움. `tests/` 확장으로 회귀를 자동화하면 사람 개입 최소화.
- **가벼운 대안 시 사람(사용자) 역할:** 평소 0, 위험 Wave(Wave 3 등) 끝에 **실제 GUI 스모크 1회(10~20분, Phase 1-3 dry-run)** 만. mock은 통과했어도 리얼 사이트에서 깨지는 것은 사람만 잡을 수 있음.
- (선택) NHIS PDF/NPS 엑셀/WEHAGO 엑셀 샘플 제공 시 `raw_data_reader`/`data_merger` 테스트 강화 가능.

---

## 3. Wave 3 — engine↔runner 통합 + 크래시 복구 DB 복원 🔴

### 3.1 왜 골든이 필요한가
Wave 3는 **실행 경로 자체**를 변경 → DB 상태(jobs/steps 전이)로만 회귀 확정 가능.

### 3.2 현재 구조 (변경 전)
- `src/batch/engine.py:181-244` `BatchEngine.run()` + `:246-289` `_run_job()` — **프로덕션에서 단 한 곳도 호출 안 됨(데드코드)**.
- `src/ui/workers/automation_runner.py:131-326` `_handle_run_phase()` — engine.run()을 **우회**하고 동일 잡 루프를 인라인 재구현.
- **runner가 누락한 engine 기능:** `detect_partial_execution`/`reset_partial_steps`(engine.py:266-269), traceback DB 저장(engine.py:289 → runner는 `mark_failed(id, msg)`만, tb 누락).
- **runner에만 있는 기능:** `_stop_event`/`_pause_event`(일시정지·정지), `_is_page_alive`(브라우저 종료 감지), `human_break`(간격 휴식), `_emit_progress`(Qt 시그널).
- `engine.initialize()`+`prepare_batch()`까지만 runner가 사용(automation_runner.py:194-216).

### 3.3 작업 내용 (동작 보존 목표)
1. `engine.run()`에 **선택적 콜백 훅** 추가(기본 no-op): `pause_check/stop_check/browser_alive_check -> bool`, `on_job_done(job)`, `on_progress(batch)`, `human_break_hook()`. 시그니처 `run(workflow_func, *, page, context, hooks=None)`.
2. `_run_job` 내 `detect_partial_execution`/`reset_partial_steps` + traceback 저장 **유지 → 크래시 복구 DB 한정 복원**(결정: DB 한정, 보이는 흐름 유지).
3. `_handle_run_phase` 인라인 루프(229-305) **제거** → `engine.run(workflow_func, page, context, hooks=dict(...))` 호출. 기존 stop/pause/page_alive/human_break/emit_progress를 훅으로 주입.
4. `_handle_run_selected_clients`(520-671, `NoopStateManager` 경로)는 **건드리지 않음**(별도 경로).

### 3.4 골든 비교 대상 DB 상태 (Wave 3 회귀)
- **batches:** status 전이(CREATED→RUNNING→COMPLETED/PAUSED) + 집계(total/completed/failed/skipped_count).
- **jobs:** status, `retry_count`(재시도 유지), `error_message`(통합 후 traceback 포함 여부 — 현재 runner는 누락), `current_step`.
- **steps:** status, **partial reset**(통합 후 running step이 pending으로 reset되는지 — 현재 runner는 미수행), `step_data`.
- **clients:** 마스터 데이터(안정적).

### 3.5 파일
`src/batch/engine.py`, `src/ui/workers/automation_runner.py`.

---

## 4. Wave 4 — 메뉴별 구조 정리 (동작 보존) 🟡

**주의:** Wave 0-2와 달리 `src/automation/*`(실제 자동화 코드)를 수정함. 동작 보존이 목표지만 Wave 3보단 위험 낮고 Wave 0-2보단 높음. Phase 2/3 항목은 골든/dry-run 검증 가능, Phase 4-8 항목은 잠금 해제 전까지 단위테스트(mock) 보완.

### 4.1 WEHAGO 공통 프리앰블 추출 `[동작보존]` — Phase 4/5/6/7
step 0(`navigate_to_wehago_main`) + step 1(`goto_salary_page`)이 4개 워크플로우에 **동일 반복**.
- 중복 위치: `wehago_swsa.py:58-73`, `wehago_salary_pdf.py:52-67`, `wehago_swta.py:44-59`, `wehago_swer.py:53-68`.
- 호출: `_common.ensure_wehago_main` + `_common.goto_salary_page_with_fallback`.
- **제안:** `src/workflows/base.py` `BaseWorkflow`에 `_run_wehago_preamble(page, state, job_id, client_name, management_number)` 추가 → 4곳에서 호출. (save_dir 생성은 phase별로 남김.)
- **동작보존:** step 이름(`navigate_to_wehago_main`/`goto_salary_page`), `fail_step` 메시지, `human_delay(2)` 타이밍, import 출처 동일.

### 4.2 Nexacro 3전략 클릭 공통화 `[동작보존]` — Phase 2(NHIS)·3(NPS)
- NHIS `src/automation/nhis/_doc_download.py:44-118` `_click_print_button(edi_page, context, pages_before) -> Page|None` — 3전략(JS MouseEvent / Playwright locator.force / DOM focus+click), 검증=`find_preview_tab`.
- NPS `src/automation/nps/_download.py:137-197` `_click_output_button(page, button_id=BTN_OUTPUT) -> int` — 4전략(nexacro_click / scroll+nexacro_click_button / locator.force / DOM), 검증=`_wait_for_modal`.
- **제안:** `src/utils/nexacro.py`에 `nexacro_3strategy_click(page, button_id, *, validate_fn, retries, retry_delay)` 추가(전략 2-3 locator+DOM 공통 core + 외부 retry 루프). 단, NPS 전략0(nexacro_click)/전략1(scroll)은 caller 고유라 그대로.
- **동작보존:** 클릭 이벤트 시퀀스·검증 호출 인자·반환 의미 동일.

### 4.3 `_nts.py` `print()`→`log()` `[동작보존]` — Phase 7
`src/automation/wehago/_nts.py`의 **print() 26곳**(L55,58,65,79,95,99,101,107,110,126,131,151,164,185,200,220,229,243,259,286,300,303,326,329,334,361) → `log()` 전환, `from src.utils.log import log` 추가.
- **동작보존:** 메시지 내용/들여쓰기 동일. 본 모듈은 thread executor(COM)에서 동작 → `log()` 스레드 안전성 사전 확인(`src/utils/log.py`).

### 4.4 `connect_hometax` no-op step 정리 `[동작보존]` — Phase 8
`src/workflows/hometax.py:64-67` — 본문 없는(주석만) step. `wehago_swer.py`에는 없음(확인).
- **제안:** 체크포인트 호환성을 위해 step 정의는 유지하되, 의도(no-op)를 명시하는 한 줄 주석으로 정리. (제거 시 기존 batch state JSON의 `connect_hometax` 참조가 깨질 수 있어 보수적으로.)
- **동작보존:** `before_step`/`after_step` 호출 유지.

### 4.5 WehagoNTS 플랫폼 가드 `[동작보존]` — Phase 7
`src/automation/wehago/_nts.py:13` `import comtypes.client`가 모듈 레벨에 가드 없음 → 비Windows에서 `ImportError`로 import 체인 크래시.
- **제안:** `select_nts_folder` 진입 시 `sys.platform != "win32"` 가드(명확한 메시지+우회) 또는 모듈 가드. Windows에서는 동일.
- **동작보존:** Windows 동일; 비Windows는 크래시 대신 우회.

### 4.6 re-export 정리 `[동작보존]` — Phase 4/5
- `wehago_swsa.py:49-51` `from ...run_swsa0101 import (download_excel, convert_for_upload, upload_excel)` → `from ..._swsa_excel import (...)`.
- `wehago_salary_pdf.py:46` `from ...run_swsa0101 import download_pdf` → `from ..._swsa_pdf import download_pdf`.
- `_common.py:1321-1339` `__getattr__` lazy re-export(`_READ_SWSA_YM_JS`/`set_swsa_ym` 등) 제거 후 호출자를 `_swsa_constants`/`_swsa_calendar` 직접 import로 변경.
- **CLI 유지 결정:** `run_swsa0101()` 함수 자체 + `main.py` import는 그대로(CLI/GUI 현상 유지).
- **동작보존:** 동일 함수 객체(단순 re-export)라 런타임 변화 없음.

### 4.7 NPS 탭 루프 하드코딩 상수화 `[동작보존]` — Phase 3
동일 `tabs` 튜플이 3곳에 중복: `nps_edi.py:78-82`, `nps_auto_cdp.py:292-296`(`run_single_workplace`), `nps_auto_cdp.py:449-453`(`run_interactive`). 소스: `nps/_constants.py:54-56`(TAB_MEMBER/RETRO/GOVT).
- **제안:** `_constants.py`에 `DECISION_DETAIL_TABS = [...]` 추가 → `_common.py` 재수출 → 3곳에서 사용.
- **동작보존:** 순서/튜플 내용 동일, 읽기 전용.

### 4.8 NHIS 팝업 닫기 (검토 후 변경 최소) `[동작보존]` — Phase 2
`nhis_edi.py`의 `close_firm_popup` 호출이 L59(에러 정리)·L66(정상 step)에 존재. → 서로 다른 제어흐름(에러 정리 vs 정상)이므로 **중복이 의도적**, 변경 불필요. 다만 L37 `close_popups(context)`가 step 등록 전이라 state manager에 안 보임 → (선택) pre-step 체크포인트 래핑.

---

## 5. Out of Scope — 별도 후속 (동작 변경 필요, 본 리팩토링에서 수정 ❌)

우선순위 순(모두 **동작을 바꾸는 수정**이라 별도 계획 필요):

1. ⭐ **보안** — SWER 변환파일 비밀번호 평문 로그 마스킹(`run_swer0101.py:77`, `log.py` 민감값 마스킹 헬퍼). PRD §6 위반. **권장 최우선 후속**.
2. **보안** — `auth_session.json` Git 히스토리 purge(운영: Supabase 토큰 철회 + filter-repo force-push) + 세션 DPAPI 암호화.
3. **데이터 정확성** — `raw_data_reader` 삼킴 전파, NHIS PDF 동적 컬럼 매핑, NPS 음수 가드(`max(0,…)`), batch 카운터 통일, `biz_to_mgmt_no` 검증. (세금 정확성 직결.)
4. **견고성** — `querySelectorAll('*')` 최적화, `goto_salary_page` `window.open`→`context.expect_page`, nexacro 합성이벤트 검증, CDP 단절 복구.
5. **빌드** — `.spec` 절대경로 동적화 + build.py 단일화, 자동업데이트 인증게이트 전 확인, 코드서명 도입.

> 상세는 초기 심층 검토 결과(7영역) 참조. 각 항목의 정확한 file:line과 권고는 검토 보고서에 있음.

---

## 6. 이어하기 가이드 (fresh 세션 첫 단계)

1. **본 문서(`docs/refactoring-handoff.md`) 전체 읽기.**
2. 현재 상태 확인:
   ```bash
   git log --oneline -7                      # Wave 0-2 커밋 확인
   PYTHONUTF8=1 python -m pytest tests/ -q   # 8/8 통과 확인(기준선)
   ```
3. **진행 분기 선택:**
   - **안전 경로:** Wave 4(§4)부터 — 동작 보존, 단위테스트/mock + Phase 2·3 dry-run으로 검증. 각 항목별 커밋.
   - **구조 통합:** Wave 3(§3) — **반드시 골든 기준선(§2.3) 먼저 캡처**(사용자 dry-run, Phase 1-3) 후 진행.
4. 각 Wave 후: `pytest` + (Wave 3/4는) dry-run 재캡처→`compare` 회귀 확인 + 서브에이전트 E2E 재검증 + 커밋.
5. **기능 절대 건드리지 말 것**(결정: 동작 보존). 동작 변경은 §5 별도 후속으로만.

### 메모리 참조 (CLAUDE memory 관련)
- `feedback_chrome-cdp-setup`, `feedback_swer0101-flow`, `project_wehago-workflow-spec-xlsx`, `reference_nps-govt-column-structure` 등이 자동화 세부사항에 관련. NPS 음수 가드 등 데이터 정확성 작업 시 `reference_nps-govt-column-structure`(국고지원 분할 sub-column 함정) 필수 참조.

---

## 부록: 관련 파일/커밋 빠른 참조

- **테스트:** `tests/test_engine.py`, `tests/test_registry.py`, `tests/conftest.py`, `pytest.ini`
- **골든:** `scripts/capture_golden.py`
- **Wave 2 핵심:** `src/workflows/registry.py`(capability), `src/workflows/base.py`, `src/ui/main_window.py`(`_is_list_phase`/`_needs_password` 헬퍼), `src/ui/workers/automation_runner.py`
- **Wave 3 대상:** `src/batch/engine.py`, `src/ui/workers/automation_runner.py`
- **커밋:** Wave 0 `ba702f7`, Wave 1 `07df6f8`·`49a0027`, Wave 2 `fda4069` (rebase 후 해시; `git log`로 최종 확인)
