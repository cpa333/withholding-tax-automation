# 기술 부채 레지스터 (Tech Debt Register)

> **목적:** 원천징수세 자동화 프로젝트의 기술 부채·결함·로드맵을 **단일 진실표**로 통합 관리.
> 산재해 있던 부채 관련 내용(핸드오프·도메인 PROGRESS·GUIDE 임베디드 리스크)을 한곳에서 우선순위화한다.
>
> **기준 시점:** 2026-07-16 · **버전:** `1.0.3` (`src/version.py`) · **HEAD:** `ad483f8`
> **관점:** GUI 프로그램(`gui_main.py` → `MainWindow` → Workers → Workflows → Automation → Utils → Chrome CDP) 기준.
> 코드를 수정하기 전, 본 문서의 해당 항목과 [§1 산재 문서 관계]를 함께 읽을 것.

---

## 0. 범례

| 기호 | 의미 |
|---|---|
| **우선순위** | 🔴 HIGH(즉시/사용자 영향) · 🟡 MED(구조·정확성) · 🟢 LOW(정리) |
| **검증** | ✅ 코드 직접 확인 · 👁 관찰·문서 인용 · ⚠ 라이브 미검증 |
| **출처** | 사용자표(사용자 정리) · 분석(아키텍처 파악) · 둘 다 |
| **카테고리** | 런타임결함 · 구조 · 데이터결함 · correctness · 빌드 · 문서 · 레거시 · 로깅 |

---

## 1. 기존 산재 문서와의 관계 (중복 회피)

본 레지스터는 **단일 진신표**이나, 세부 실행계획·기술 배경은 다음 기존 문서가 원천이다. 본 문서는 우선순위·상태·위치만 추적하고 중복 기술을 피한다.

| 기존 문서 | 본 레지스터와의 관계 |
|---|---|
| `docs/refactoring-handoff.md` | **Wave 3**(engine↔runner 통합 + 크래시복구)·**Wave 4**(메뉴정리) = 본 문서 **TD-02 / TD-05 / TD-13 / TD-04** 와 동일 영역. 세부 계획·골든스냅샷 회귀 기법은 handoff가 원천. |
| `docs/parallel-automation-handoff.md` | 병렬 안정화·open items. 본 문서 **TD-07 / LV-4 / LV-5** 참조. |
| `src/automation/wehago/PROGRESS.md` | 도메인 진행 + `## 다음 단계 TODO`(대부분 MVP 시절, 상당수 완료). 미완료만 **LV-5**로 인용. |
| `src/automation/hometax/PROGRESS.md` | 제출 플로우 완료·라이브 검증(2026-07-17, real click 전환). **Phase 10 `enabled=True`**(이전 문서의 `=False` 기재는 stale). 남은 TODO: 접수증 저장·신고내역 다운로드(Phase 11 연계). |
| `GUIDE.md` (§risk 계열) | 기술 문서 내 임베디드 리스크. 본 문서가 상위 레지스터. |

---

## 2. 단일 우선순위 매트릭스

| ID | Pri | 카테고리 | 항목 | 위치 | 영향 | 검증 | 출처 |
|---|---|---|---|---|---|---|---|
| **TD-01** | 🔴 | 빌드 | installer_output/ 정합성 깨짐 — `whta_setup.exe`(ASCII)=6/15 구빌드, 최신(7/3·166MB)은 한글명, `version.json`=6/15 | `installer_output/` | 게시 시 sha256/size 검증 실패, 자동업데이트 중단 | ✅ | 사용자 |
| **TD-02** | 🔴 | 런타임결함 | `_reset_batch` 매 실행마다 해당 포털 steps/jobs/batches 전체 DELETE → 크래시 복구·이어하기 무력화 | `automation_runner.py:197,687-716` | BatchEngine '배치 재사용' 설계와 충돌, 러너 경로에서 체크포인트 의미 상실 | ✅ | 분석 |
| **TD-03** | 🔴 | 구조 | db.py 1,210줄 — CRUD 반복 + duration 계산 3곳 중복 + 카운터 동기화 2경로 | `db.py:857/905/1107` | 유지보수성, 카운터 불일치 위험 | ✅ | 둘 다 |
| **TD-04** | 🔴 | 구조 | automation_runner.py 1,239줄 — Playwright 생명주기 + 5포털 로그인 + 엔진 연동 + 브라우저 복구 혼재 | `automation_runner.py` | 책임 분리 필요 (Wave 3 영역) | ✅ | 사용자 |
| **TD-05** | 🔴 | 데이터결함 | `replace_clients_preserving_mgmt`가 `DELETE FROM clients` (WHERE 없음) → **전 포털 wipe** + 이름 매칭 실패 시 override 영구 손실 | `db.py:427` (421-435) | 수임처 DB 손실, FK 충돌 가능 | ✅ | 둘 다 |
| **TD-06** | 🟡 | 구조 | MainWindow 1,077줄 + UI↔DB 직결 (raw `sqlite3` + 4개 Repository 직접 호출) | `main_window.py:401,504,809` | 계층 분리 약화 | ✅ | 둘 다 |
| **TD-07** | 🟡 | 런타임 | 병렬(Phase 2)이 SQLite 영속상태 미사용 → 체크포인트·재시도 불가 | `parallel_cli_worker.py` + `_parallel_report.py` | 크래시 시 result_summary 1회성만, 복구 불가 | 👁 | 분석 |
| **TD-08** | 🟡 | correctness | `Portal` enum에 `COMWEL_EDI` 누락 — Phase 5가 `comwel_edi` 사용 중 | `models.py:18-31` | `Portal("comwel_edi")` 시 ValueError 위험, 표시명 누락 | ✅ | 분석 |
| **TD-09** | 🟡 | 구조 | `auth.py`가 `src.ui.resources.auth_config` 역참조 (utils→ui) | `auth.py:18` | 계층 의존 방향 위반 (역방향 간선) | ✅ | 분석 |
| **TD-10** | 🟡 | correctness | `mark_crashed_as_recoverable` 포털 필터 없이 전체 running/paused → crashed | `db.py:613-616` | 다중 포털 동시 실행 시 타 포털 배치까지 crashed 처리 | ✅ | 분석 |
| **TD-11** | 🟡 | 빌드 | Qt6 네이티브 DLL 잔존(Multimedia/Qml/Quick/PDF) — Python 바인딩만 exclude | `build.py:30-49` | 번들 383MB (목표 315MB) | 👁 | 사용자 |
| **TD-12** | 🟡 | 문서 | 문서 노후/중복 — PRD(MVP), GEMINI(NHIS 섹션), PROGRESS(포트 9222↔실제 9223), 사용자 가이드 3종 중복 | 다수 | 신규 작업자 혼란, 포트 오판 | ✅ | 둘 다 |
| **TD-13** | 🟡 | 구조·문서 | `engine.run()` 사실상 데드코드(러너가 인라인 재구현) + `run_single` 시그니처 문서 오기 | `engine.py` / `base.py:37-40` | Wave 3 통합 영역, 문서-코드 불일치 | ✅ | 분석 |
| **TD-14** | 🟢 | 레거시 | `sys.path.insert(0, PROJECT_ROOT)` 남발 | `_*.py` 대부분 | 패키지 정비 시 제거 가능 | 👁 | 사용자 |
| **TD-15** | 🟢 | 로깅 | `print()` 기반 로깅 (logging 모듈 미사용) | `engine.py` 등 | 파일 로깅/레벨 제어 불가 | 👁 | 사용자 |
| **TD-16** | 🟢 | 데드코드 | `settings_dialog.py` 잠재 데드코드 / 포털 호스트 dict 중복 | UI 계층 | 정리 필요 | 👁 | 사용자 |

> 참고(구조 일관성): TD-02·TD-04·TD-05·TD-13 은 모두 **러너↔엔진↔DB 실행 경로**에 묶여 있어 Wave 3(`refactoring-handoff`)에서 함께 다루는 것이 효율적이다.

---

## 3. HIGH 상세

### TD-01 — installer_output/ 정합성 깨짐 🔴 [빌드] ✅
- **현상(검증값):** `installer_output/`에 3 파일 — `version.json`(2026-06-15), `whta_setup.exe`(6/15, 233MB, 구 LZMA), `원천징수자동화_설치.exe`(7/3, 166MB, 최신 zip). release.py가 기대하는 ASCII명 `whta_setup.exe` + 최신 `version.json` 쌍이 **아님**(최신 빌드가 한글명으로만 존재).
- **근원:** 빌드 산출물을 ASCII명으로 복사/갱신하는 단계 누락 + `version.json`이 release.py가 아닌 수동 생성으로 방치.
- **영향:** `release.py`의 sha256/size 검증이 구빌드 기준으로 통과하거나 실패 → 게시된 `version.json`이 실제 에셋과 불일치 → `updater.py` 자동업데이트 중단/잘못된 바이너리 배포.
- **수정 방향:** release 파이프라인에 `원천징수자동화_설치.exe` → `whta_setup.exe` 복사(또는 빌드 직후 ASCII명으로 산출) + `version.json`을 동일 커밋에서 빌드 결과 기준 재생성. 게이트: 복사 후 sha256 재계산 후에만 version.json 확정.
- **재현:** `ls -la installer_output/` + 각 파일 mtime/size 대조.

### TD-02 — `_reset_batch` 매 실행 portal 전체 wipe 🔴 [런타임결함] ✅
- **현상:** `AutomationRunner`가 `start_phase` 진입 시(`automation_runner.py:197`) `_reset_batch(db_path, portal, phase_id)` 호출. 일반 포털 분기(`:703-716`)가 `WHERE portal=?` 로 해당 포털의 steps/jobs/batches를 **전부 삭제**. 리스트 phase(1) 분기(`:698-701`)는 clients까지 전체 wipe(이것은 '새로가져오기' 의도적).
- **근원:** 러너가 '항상 깨끗한 상태에서 시작' 전략을 취해, `BatchEngine.prepare_batch`의 batch_key UNIQUE 재사용·`StateManager` 체크포인트·`mark_crashed_as_recoverable`/`get_resume_index` 크래시 복구 경로를 **사전에 무력화**.
- **영향:** GUI(러너) 경로에서는 크래시 후 '이어서 실행'이 동작하지 않음(매번 처음부터). 설계(DB 영속 회복)과 구현(러너 wipe)이 충돌.
- **수정 방향:** Wave 3(`refactoring-handoff` §3) — `_reset_batch`를 '포털 활성 배치만 재사용 가능 상태로 정리'로 변경하거나, 아예 제거하고 `prepare_batch`에 맡김. **선행 조건: 골든 스냅샷 기준선 캡처**(handoff §2.6, Wave 3는 실행경로 변경이라 골든 필수).
- **검증:** `git show` + dry-run 전후 DB 덤프 비교(`scripts/capture_golden.py`).

### TD-03 — db.py 1,210줄 과대 + 내부 중복 🔴 [구조] ✅
- **현상:** `db.py` 1,210줄에 4개 Repository CRUD가 반복. duration 계산 `(t1-t2).total_seconds()` 패턴이 `:857-863`(job 완료)·`:905-911`(job 갱신)·`:1107-1113`(step 완료) **3곳 동일**. 카운터 동기화 2경로 혼재.
- **영향:** 유지보수 비용, duration/카운터 로직 수정 시 누락 분기 → 통계 불일치.
- **수정 방향:** duration 헬퍼(`_compute_duration(start,end)`) 추출, Repository별 mixin 또는 분할. 동작 보존 필수.

### TD-04 — automation_runner.py 1,239줄 다중 책임 🔴 [구조] ✅
- **현상:** Playwright 생명주기(`_ensure_browser`/`_disconnect_browser`) + 5포털 로그인 대기 + BatchEngine 연동 + 브라우저 복구 + 단발 phase(새로가져오기) 직접 처리가 한 클래스에 혼재.
- **수정 방향:** Wave 3 — 브라우저 세션 관리 / 로그인 대기 / 배치 구동을 분리. TD-02·TD-13 과 동일 영역이므로 함께.

### TD-05 — `DELETE FROM clients` WHERE 없음 (전 포털 wipe) 🔴 [데이터결함] ✅
- **현상:** `replace_clients_preserving_mgmt`(`db.py:427`)가 `self.db.conn.execute("DELETE FROM clients")` — **WHERE 절 없음**, `portal` 파라미터(default "wehago")가 DELETE에 반영되지 않음. override snapshot은 `WHERE management_number != ''`(`:421-426`)만 잡고 이름 매칭으로 복원(`:434-435`).
- **영향:** ① '새로가져오기' 시 wehago뿐 아니라 **NHIS/NPS/COMWEL 수임처까지 전부 삭제 후 wehago 데이터로 재삽입**(타 포털 row 소실). ② 수임처명이 바뀌면 override(수동 관리번호) 영구 손실. ③ `foreign_keys=ON` 하에서 jobs/steps FK 충돌 가능성(현재는 FK 미연결로 동작 중).
- **수정 방향:** DELETE를 `WHERE portal=?`(또는 client id in (스냅샷 대상))로 스코프. upsert INSERT 분기에 management_number 컬럼 포함 검토(스냅샷/복원 자체가 불필요해질 수 있음). TD-03 분할 시 함께.

---

## 4. MED 상세

- **TD-06** MainWindow가 raw `sqlite3` + 4개 Repository 직접 호출. ViewModel/Service 계층 도입으로 UI↔DB 분리. ✅
- **TD-07** 병렬(Phase 2)은 subprocess CLI + `__WTAX_RESULT__` result_summary 1회성 반환만. SQLite 배치/체크포인트 미사용 → 병렬 크래시 시 재개 불가. (직렬 러너 경로와 비대칭) 👁
- **TD-08** `Portal` enum(`models.py:18-31`) = WEHAGO/NHIS_EDI/NPS_EDI/HOMETAX. `COMWEL_EDI` 없음에도 Phase 5·`PORTAL_URLS`·`display_name`이 comwel_edi 문자열 사용. `Portal("comwel_edi")` 호출 시 ValueError. **1줄 수정 후 즉시 효과.** ✅
- **TD-09** `src/utils/auth.py:18` → `from src.ui.resources.auth_config import ...`. utils 계층이 ui 계층을 역참조(순환 위험). auth_config의 상수를 `src/config.py` 등 비-UI 위치로 이동. ✅
- **TD-10** `mark_crashed_as_recoverable`(`db.py:613-616`)가 `WHERE status IN ('running','paused')` — 포털 필터 없음. 재시작 시 타 포털 실행 중 배치까지 crashed 처리. `WHERE portal=?` 추가. ✅
- **TD-11** `_QT_EXCLUDE_MODULES`(`build.py:30-49`)가 Python 바인딩만 exclude하고 Qt6 네이티브 DLL(Multimedia/Qml/Quick/PDF)은 잔존 → 383MB(목표 315MB). PyInstaller `--exclude-module` 또는 post-build DLL 제거 스크립트 검토. 👁
- **TD-12** PRD(MVP 시절, 자체 "GUIDE 기준" 명시)·`wehago_automation_guide.md`(canvas 전제 틀림, 폐기)·`GEMINI.md` NHIS 섹션(구식)·`PROGRESS.md`(CDP 9222 ↔ 실제 9223)·사용자 가이드 3종(`USER_GUIDE.md`/`docs/user-guide.md`/`docs/설치안내서.md`) 중복. 진실은 `GUIDE.md`+코드+두 handoff. 폐기/병합 정리. ✅
- **TD-13** `engine.run()`이 사실상 데드코드(러너가 인라인 재구현). `run_single` 실제 시그니처 `(self, page, context, client_name: str, job_id: int, state, **kwargs)`(`base.py:37-40`)가 문서/일부 주석에 `(page, context, job, state)`로 오기. Wave 3 통합 시 정리. ✅

---

## 5. LOW

- **TD-14** `sys.path.insert(0, PROJECT_ROOT)`가 `_*​.py` 대부분에 남발. 패키지 구조 정비 시 제거 가능. 👁
- **TD-15** `print()` 기반 로깅, `logging` 미사용. 파일 로깅/레벨 제어 불가. 단, `log.py` 듀얼패스 불변(callback+stdout 미러)이 의도적 설계이므로 변경 시 불변 유지 주의. 👁
- **TD-16** `settings_dialog.py`(현재 `VerificationDialog` 용도) 잠재 데드코드, 포털 호스트 dict 중복. 정리. 👁

---

## 6. 라이브 검증 대기 (위험 게이트 — 부채 아님)

코드상 구현됐으나 실기기/실사이트 미검증 분기. 출하 전 반드시 스모크 필요.

| ID | 항목 | 위치 | 비고 |
|---|---|---|---|
| **LV-1** | NPS 국고지원금 col24 분기 등가 가정(통합엑셀 경로 vs 구 govt 엑셀 //2) | `data_merger._apply_nps_row` | 수식 col10+col16−col24 |
| **LV-2** | Defender 무서명 빌드 스모크 1·2단계 (0x800700E1 오탐 회귀) | `build.py` Tier0+1 | MEMORY 명시 미검증 |
| **LV-3** | EI v3 조정분(adjustment==0 → 0.9% 보존 자동산정) | `data_merger._apply_ei_row` | 라이브 검증 필요 |
| **LV-4** | 병렬 영속 프로필(빈 프로필 → 보안프로그램 재설치 오탐 해결) | `chrome_cdp._prepare_user_data_dir` | 구현 완료, 라이브 대기 |
| **LV-5** | 병렬 → WEHAGO 급여자료입력 E2E(공단EDI raw → SWSA 반영) | `wehago_swsa._resolve_insurance_dir` | handoff §16.3 권장 |

---

## 7. 권장 실행 순서 (제안)

1. **TD-08** — `Portal` enum `COMWEM_EDI` 추가 (1줄, correctness, 즉시, 리스크 최소)
2. **TD-01** — release 파이프라인 ASCII명 복사 + version.json 동기화 (게시 즉시 실패 차단)
3. **[골든 선행]** Wave 3 골든 스냅샷 기준선 캡처 (TD-02/05/13 작업 전 필수 — `refactoring-handoff` §2.6)
4. **TD-05 + TD-02 + TD-10** — DB/러너 실행경로 결함 (같은 영역, 함께) → 크래시 복구·데이터 손실 해소
5. **TD-03 / TD-04 / TD-06 / TD-13** — 구조 분할 (Wave 3/4 정렬, 동작 보존)
6. **TD-09** — auth_config 상수 이동 (역참조 해소)
7. **TD-12** — 문서 폐기/병합 정리
8. **TD-11 / TD-14 / TD-15 / TD-16** — LOW 정리
9. **LV-1 ~ LV-5** — 출하 전 라이브 스모크 (부채 아님, 게이트)

---

*본 레지스터는 살아있는 문서. 항목 해결 시 **삭제하지 말고** 상태를 `✅ 해결(커밋)`로 표시하고 아래 변경 이력에 기록.*
