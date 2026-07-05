# 원천징수 자동화 시스템 — 기술 문서

## 1. 개요

세무법인에서 사용하는 원천징수 업무 자동화 Windows 데스크톱 애플리케이션. 4개 포털(WEHAGO/NHIS EDI/NPS EDI/홈택스)에 걸친 8개 Phase 워크플로우를 하나의 GUI에서 관리하고, 수임처별 진행 상황을 실시간으로 추적한다.

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
│  BaseWorkflow → 각 포털별 어댑터 (8개 Phase)               │
│  ↕ 기존 함수 호출만                                      │
├─────────────────────────────────────────────────────────┤
│  Layer 1: 기존 자동화 코드 (수정 없음)                    │
│  src/automation/ (Playwright) + src/batch/ (SQLite)      │
└─────────────────────────────────────────────────────────┘
```

## 3. 단계별 워크플로우

> phase_id는 코드 레지스트리(`src/workflows/registry.py`) 기준. 사이드바에
> 표시되는 번호 = phase_id. phase 2는 병렬(NPS+NHIS+고용보험 동시) 전용 메타데이터.

| Phase | 포털 | 기능 | 상태 |
|-------|------|------|------|
| 1 | WEHAGO | 수임처 리스트 확보 | 완료 |
| 2 | (병렬) | 공단 EDI 병렬 자동화 (NPS+NHIS+고용보험) | 완료 |
| 3 | 국민건강보험 EDI | 결정내역 PDF/Excel 다운로드 | 완료 |
| 4 | 국민연금 EDI | 결정내역 PDF/Excel 다운로드 | 완료 |
| 5 | 고용보험 EDI | 고용보험료 지원금 정보 인쇄물 다운로드 | 완료 |
| 6 | WEHAGO | 급여자료입력 (SWSA0101) | 완료 |
| 7 | WEHAGO | 급여명세 PDF | 완료 |
| 8 | WEHAGO | 원천이행상황신고서 (SWTA0101) | 완료 |
| 9 | WEHAGO | 원천전자신고 (SWER0101) | 완료 |
| 10 | 홈택스 | 원천세 신고 | 비활성 |

### Phase 1: 수임처 리스트 확보 (WEHAGO)

기존 방식과 다르게 Phase 1은 독립적으로 동작한다:
- **DB 영속화:** 한 번 가져온 리스트는 SQLite에 저장되어 프로그램 재시작 시 즉시 표시
- **새로 가져오기 버튼:** WEHAGO에 접속하여 최신 수임처 목록을 스크래핑 후 DB 교체
- **담당자 필터링:** 툴바의 "담당자" 입력란에 이름을 입력하면 해당 담당자의 수임처만 조회. 비워두면 전체 수임처 조회
- **모두 삭제 버튼:** 등록된 수임처 전체 삭제 (확인 다이얼로그 포함)
- "전체실행" 버튼은 Phase 1에서 숨김 처리됨

담당자 필터링 동작 (`search_clients_by_name`):
1. `wait_for_selector`로 검색 입력란이 SPA 렌더링될 때까지 대기 (10초 타임아웃)
2. XPath 기반으로 검색 입력란(`#mainCard/div[2]/div/div[1]/div/span/input`)에 담당자 이름 입력
3. XPath 기반으로 조회 버튼(`#mainCard/div[1]/div[3]/button`) 클릭 → 필터링된 결과 대기
4. 이름이 비어있으면 이 단계를 건너뛰고 전체 수임처 조회

> **참고:** CSS 셀렉터(`#mainCard input`)는 hidden input 37개가 포함되어 부정확하므로 XPath 우선 사용.

스크래핑 동작 (`get_clients_with_biz_from_taxagent`):
1. 수임처관리 페이지(`tedge/#/taxagent`)로 이동 → 모달 닫기 → 리스트 로딩 대기
2. (선택) 담당자 이름 필터링 수행
3. 스크롤 컨테이너를 끝까지 스크롤하여 전체 카드 로드
4. 각 카드를 순차 클릭(0.8초 대기) → `div.cl_basicinfo_section` 상세 영역에서 사업자등록번호(`\d{3}-\d{2}-\d{5}`) 추출
5. **사업자번호 누락 시 재시도:** 이름은 있고 사업자번호만 비어있으면 상세 영역 로딩 지연으로 판단, 0.5초 간격 최대 3회 재시도
6. 수임처명은 `li.is_linkbtn.selected > span.company_name_text`에서 추출
7. **원천징수 신고주기 태그 추출:** 각 카드의 태그(`div.tag_bx.is_tag button.btn_tag span`, 텍스트는 콤마 구분 예: `테스트1,원천,매월`)에서 `매월`/`반기` 세그먼트를 찾아 `report_cycle`로 수집
8. `[테스트]` 접두사 제거 후 DB에 wehago 포털로 저장 (수임처명 + 사업자등록번호 + 신고주기)
9. 레거시: `get_all_clients_from_management()` (이름만 수집)은 별도 유지

> **신고주기(report_cycle):** `clients.report_cycle` 컬럼(SCHEMA v3). "새로 가져오기" 시 스크램값으로 채워지며, GUI 수임처 테이블의 **주기 컬럼 드롭다운**(매월/반기/빈)으로 수동 보정 가능(`update_report_cycle`). 반기 수임처는 원천징수를 1·7월에만 신고하므로 향후 월별 배치에서 처리 대상 필터링에 활용 가능.

> **참고:** 메인 페이지(`#/main`)의 카드 UI는 SPA 가상 스크롤로 인해 항상 20개만 DOM에 렌더링되어 전체 수임처를 보장하지 않음. 단, 메인 검색창(`search_company_by_biz`)에 사업자번호를 `keyboard.type`+`Enter`로 입력하면 해당 수임처로 필터링되어 20개 밖 수임처도 SmartA 진입 가능 (Phase 4~7 공통). `fill()`+버튼클릭은 React onChange 가 타지 않아 필터링이 안 되므로 주의.

### Phase 2: 국민건강보험 EDI

1. Chrome 실행 → edi.nhis.or.kr 접속
2. 사용자가 공동인증서로 수동 로그인 (최대 15분 대기)
3. BatchEngine이 WEHAGO 수임처를 nhis_edi 포털에 자동 복사
4. 수임처별로 순차 처리:
   - **수임사업장선택**: `img[src*="we_btn_suim"]` 클릭 → 팝업에서 사업장 검색/선택
   - **받은문서 → 웹EDI 탭 열기**: `pageLinkPopup1('201')` 호출
   - **서식명 필터링**: "전체" 라디오 + "가입자 고지(산출) 내역서" 콤보박스 선택
   - **YYYYMM 매칭 행 검색**: 그리드에서 `고지년월: {YYYYMM}` 포함 행 탐색 → 첫 매칭 행의 서식명 셀(col=3) 더블클릭
   - **인쇄 → PDF 다운로드**: 인쇄 버튼 → Crownix 미리보기 → PDF 저장
5. 저장 경로: `~/Desktop/국민건강보험_{YYYYMM}/{수임처명}/`
6. 파일명: `가입자고지내역서_건강_{YYYYMM}.pdf`

> **날짜 의존성:** GUI에서 선택한 연도/월로 YYYYMM을 계산하여 그리드에서 매칭 행을 찾는다.
> 이전에는 항상 첫 행(gridrow_0)만 처리했으나, 이제 사용자가 설정한 기간에 해당하는 문서만 정확히 다운로드한다.

### Phase 3: 국민연금 EDI

Nexacro 기반 웹 프레임워크로 일반 DOM click이 동작하지 않음:

1. Chrome 실행 → edi.nps.or.kr 접속
2. 사용자 공동인증서 수동 로그인
3. 수임처별 순차 처리:
   - **사업장관리번호로 검색**: 콤보박스를 "사업장관리번호"(`item_1`)로 변경 후 숫자만 입력
   - 사업장 전환 → 결정내역 이동 → 사용자 설정 월의 결정내역 상세 진입
   - 가입자내역(`grdList2`), 소급분내역(`grdList3`), 국고지원내역(`grdList4`) 탭 순회
4. Nexacro 이벤트: `dispatchEvent(new MouseEvent(...))` 로 mousedown → mouseup → click 순차 발생
5. 저장 경로: `~/Desktop/국민연금_{YYYYMM}/{수임처명}/`
6. 파일명: `국민연금보험료_결정내역_{YYYYMM}_{탭명}.pdf` / `.xlsx`

> **공단 EDI 병렬 자동화(2번) 저장 경로:** 병렬 실행 시 세 기관 자료를 **공통 최상위 아래 포털별 하위폴더로 분리** — `~/Desktop/공단EDI_{YYYYMM}/{수임처명}/{국민연금|국민건강보험|고용보험}/`. 세 CLI 에 `--save-site 공단EDI` 를 전달(상수 `PARALLEL_SAVE_SITE` 단일 소스 = `src/utils/save_path.py` — `parallel_cli_worker.py`·`wehago_swsa.py` 가 import)하고 `make_save_dir(site, client, …, subdir=_SAVE_SUBDIR)` 로 포털명을 하위폴더로 넘겨 분리. 세 Chrome 이 서로 다른 하위폴더에 써서 listdir/cleanup 파일 레이스를 원천 차단. 단독(NHIS/NPS/고용보험 개별) 실행은 `subdir=None` 으로 기존대로 각 사이트 최상위 폴더 사용. Phase 6(급여자료입력)의 `_locate_raw_data` 는 단독·병렬 양쪽 경로를 모두 리졸브(`_resolve_insurance_dir` 헬퍼) → 어느 쪽으로 다운로드하든 원천데이터 반영(§16 참조).

> **날짜 의존성 (2026-06-12 업데이트):**
> - GUI에서 선택한 연도/월로 결정내역 그리드의 내용 컬럼(col=3)에서 `{YYYY}.{MM}` 매칭
> - **2차 우선 탐색**: 해당 월의 `2차` 통보서를 먼저 찾고, 없으면 해당 월의 첫 아이템 선택
> - 매칭 실패 시 첫 행으로 폴백 (WARN 로그 출력)
> - `nps_auto_cdp.py` 대화형 메뉴에서도 year/month 입력 지원

#### 사업장관리번호 변환 규칙

사업자등록번호(`XXX-XX-XXXXX`)에서:
1. 하이픈 제거: `XXXXXXXXXX`
2. 끝에 `0` 추가: `XXXXXXXXXX0`

例: `515-86-01709` → `51586017090`

> **override & 보존:** `biz+'0'`는 단일 사업장 표준값. **지점/추가사업장**은 끝이 `1,2,…` 로 `biz+'0'`와 달라 → Phase1 표(관리번호 컬럼 col2)에 실제 번호를 직접 입력(override)해야 함. `get_management_number`(models.py)가 override 우선, 없으면 `biz+'0'` 자동계산. **새로가져오기가 override 를 보존**(`ClientRepository.replace_clients_preserving_mgmt`, db.py — DELETE+INSERT 전 {name:mgmt} snapshot → INSERT 후 같은 name에 restore; 예전엔 매번 wipe). 병렬 mgmts 조립(`main_window._on_start` ALL/SELECTED)도 동일 auto-calc 로 자가방어.

#### 선택건 실행

Phase 2/3에서 수임처 테이블의 특정 행을 Ctrl/Shift 클릭으로 다중 선택한 후 "선택건 실행" 버튼으로 해당 수임처만 즉시 실행 가능. BatchEngine 없이 직접 워크플로우를 실행한다.

### Phase 5: 급여명세 PDF (WEHAGO)

수임처별로 SWSA0101(급여자료입력) 페이지에서 **Duzon PrintDialog**(OS 수준, pywinauto 제어)로 PDF를 발급. 인쇄형태를 전환해가며 **2종 PDF**를 같은 수임처 폴더에 저장(`download_multi_pdf`).

1. 수임처 SmartA 진입(사업자번호 검색) → SWSA0101 이동(귀속연월/드롭다운 설정)
2. `#print` 버튼 → "일괄출력" 메뉴 → Duzon PrintDialog 실행
3. 인쇄형태(cbContents 콤보박스)를 순회하며 각각 PDF 저장:
   - **급여대장** (cbContents 상단)
   - **급여명세(사원당 한장)** (그 아래)
   - ★cbContents 드롭다운 **상단→하단 순서**로 받아야 함★ — 역순(하단→상단) 선택 시 드롭다운 스크롤 업이 꼬여 잘못된 항목이 클릭된다. `SALARY_PDF_FORMATS` 참고.
4. 저장 경로: `~/Desktop/위하고급여명세PDF_{YYYYMM}/{수임처명}/` — 급여대장·급여명세 PDF 각각.

> **인쇄형태 옵션**(cbContents, 15종): 급여명세(구)·급여대장·급여대장(부서별)·급여대장(비과세계)·창봉투·**급여명세(사원당 한장)**·급여명세(전체항목)·... 현재 **급여대장 + 급여명세(사원당 한장)**만 다운로드. 추가 시 `SALARY_PDF_FORMATS`에 상단→하단 순서로 기재.

### Phase 6: 원천이행상황신고서 (WEHAGO — SWTA0101)

Phase 1-5와 완전히 독립적으로 동작한다. NHIS/NPS 원천데이터나 급여 엑셀 없이도 실행 가능.

1. Chrome 실행 → WEHAGO 접속 (Phase 1, 4, 5와 포털 공유)
2. 사용자 공동인증서 수동 로그인
3. 수임처별 순차 처리:
   - **WEHAGO 메인 복귀** → 사업자번호 검색 → 수임처명 fallback
   - **SWSA0101 사이드바 클릭** (SPA 라우팅 초기화)
   - **SWTA0101 메뉴 이동** → 신고주기 결정
   - **신고주기 결정**: DB `clients.report_cycle`(매월/반기) 우선. 비어있으면 위하고 라디오를
     **읽기 전용 ground truth**로 읽어 결정 → 어댑터가 DB에 **역충전**(1번 메뉴 DB와 동일 테이블).
     (라디오는 시스템 고정이라 클릭 불가 → `get_report_period_type`은 읽기 전용)
   - **라디오 판별 신뢰성**: 매월은 "반기 미체크"라는 부정형 신호라 단일 읽기로는 로딩 중과
     확정을 구분할 수 없어 반기를 매월로 오판하는 버그가 있었다. `get_report_period_type`이
     라디오 렌더 대기 후 **5초 정착 창 폴링**으로 보강 — 반기 관측 시 즉시 확정, 정착 창 내내
     미관측 시 매월 확정, 판별 불가 시 매월 폴백(역충전 안 함).
   - **기간 설정**:
     - **매월** → GUI 선택 연/월 (미선택 시 직전월 자동 계산)
     - **반기** → **실행일 기준** (GUI 연/월 무시). `compute_half_period()`: 7~12월 실행→당해 1~6월(상반기) / 1~6월 실행→전년 7~12월(하반기). 반기 신고는 연 2회(7월·1월).
   - **조회 → 마감/마감해제**: 미마감이면 마감 적용(2단계 모달: 유의사항 → 마감완료). 이미 마감이면 **마감을 자동 해제** — 동일한 확인 모달 패턴 처리 후 버튼이 "마감해제" → "마감" 으로 전환되었는지 검증. 전환되지 않으면 `RuntimeError` 로 해당 잡을 실패 처리(어댑터 `wehago_swta.py`의 try/except 경유).

### Phase 7: 원천전자신고 (WEHAGO — SWER0101)

Phase 1-6과 완전히 독립적으로 동작한다. 전자신고 파일 비밀번호와 **WehagoNTS 프로그램 설치**가 필요.

1. Chrome 실행 → WEHAGO 접속 (Phase 1, 4, 5, 6과 포털 공유)
2. 사용자 공동인증서 수동 로그인
3. **사전 요구: WehagoNTS 프로그램 설치** — 전자신고 파일 저장 시 COM UIAutomation으로 WehagoNTS 제어. 미설치 시 파일 저장 단계에서 실패.
3. **"전체실행" 클릭 시 툴바 비밀번호 필드에서 읽기** (Phase 7/8 선택 시 툴바에 표시)
4. 수임처별 순차 처리:
   - **WEHAGO 메인 복귀** → 사업자번호 검색 → 수임처명 fallback
   - **SWSA0101 사이드바 클릭** (SPA 라우팅 초기화) → **SWER0101 이동**
   - **지급기간 설정**: GUI 연도/월 반영 (미선택 시 전월 자동 계산)
   - **수임처 선택** → 코드도움 확인 모달 처리
   - **제작(F4)** → 참고사항 모달 닫기 → 비밀번호 입력 → 전자신고 파일 제작
   - **WehagoNTS 폴더 선택**: COM UIAutomation으로 `원천전자신고_YYYYMM/{수임처명}/`에 `.01` 파일 저장

### Phase 8: 홈택스 원천세 신고

Phase 7에서 생성된 `.01` 파일을 홈택스에 업로드하여 파일변환신고 수행. Phase 7과 포털이 다르므로(WEHAGO → 홈택스) 독립 세션에서 실행.

1. Chrome 실행 → 홈택스 접속 (Phase 8 전용 포털)
2. 사용자 공동인증서 수동 로그인
3. 수임처별 순차 처리:
   - **Phase 7 결과물 검색**: `~/Desktop/원천전자신고_YYYYMM/{수임처명}/*.01`에서 최신 파일 탐색
   - **원천세 신고 > 일반신고 이동**: `#menuAtag_4106010000` 메뉴 클릭
   - **파일변환신고 이동**: `btn_cbcMediRtn` 버튼 클릭 + 모달 닫기
   - **파일 선택**: iframe 내 hidden `<input type="file">`에 `.01` 파일 설정
   - **파일검증**: `btn_cenSts` 클릭 후 모달 자동 처리
4. 세션 연장: 20분 주기 `$c.pp.sessionXtn($p)` + `sessionTimer("Y")` 자동 호출

### Phase 5: 고용보험 EDI (근로복지공단)

엑셀 v3 (C86~H106) 워크플로우 기반. 본 phase는 **raw data(고용보험료 지원금 정보 인쇄물)
다운로드**를 담당. 단독(직렬) 메뉴로도 실행 가능하며, phase 2 병렬 자동화에도 편입되어
NPS+NHIS와 동시 실행된다.

**상태: 라이브 검증 완료** — 3개 수임처 연속 테스트 PASS (데이터 1건 PDF 저장 +
0건 2건 인쇄 생략). ClipReport 리포트 뷰어를 통한 PDF 다운로드까지 검증됨.

1. Chrome 실행 → 근로복지공단 접속 (`total.comwel.or.kr`)
2. 사용자 공동인증서 수동 로그인 (사무대행 151-86-01316)
3. 수임처별 순차 처리 (라이브 검증 흐름):
   - **로그인 감지**: URL 고정이므로 `btnLogin`/`guestView` 가시 요소 사라짐으로 판별
   - **사무대행 팝업 닫기**: 로그인 직후 `samuInfoPopup` 자동 닫기
   - **20209 진입** (`navigate_to_premium_20209`): 메인 대시보드 퀵메뉴 → 부과고지 보험료 조회(20209)
   - **부과기간 설정** (`set_period`): 부과년도/부과월 select (`comYear_input_0`/`comMM_input_0`)
   - **사업장 전환** (`select_workplace`): 관리번호(사업자번호+`'0'`) 입력 → 사업장조회(`btnSaeopjangSearch`)
     → WZ0101_P01 팝업 → 관리번호 정확일치 행 선택. blind row=0 금지.
   - **본 화면 조회** (`search_main`): `btnSearch` 클릭 — 데이터 로드 필수 (라이브 발견)
   - **고용 탭** (`click_employment_tab`): `w2tabcontrol_active` 체크 후 클릭 (중복 클릭 방지)
   - **지원금 팝업** (`open_support_popup`): "지원금" 키워드 매칭 (라벨/동적 id 가변 대응)
   - **0건 처리**: 데이터 0건이면 인쇄 생략 (정상)
   - **인쇄물 다운로드** (`download_support_info_printout`): "인쇄하기" → WZ0203 모달 +
     ClipReport(`ifr_Report` 프레임) → `report_menu_save_button` → PDF 형식 선택 →
     `download_main_option_download_button` → `고용보험료지원금정보_{YYYYMM}.pdf` 저장
4. 저장: `~/Desktop/고용보험_{YYYYMM}/{수임처}/` (국민연금/건강보험과 동일 구조)

> 주의: 버튼 id(`wq_uuid_XXXX`)는 매 렌더링마다 동적이므로 텍스트/키워드 매칭 사용.
> 지원금 버튼 라벨도 사업장에 따라 다름 ("사회보험료 지원금정보" / "고용보험료 지원금 정보").

## 4. UI 레이아웃

```
+------------------------------------------------------------------+
|  Toolbar: [2026][05] [☑ dry-run] [담당자: 이름입력]    [⏸일시정지] |
|                        ↑ Phase 1 시 표시                              |
|                 Phase 7/8 시 → [비밀번호: ••••••••]                   |
+------------------------------------------------------------------+
| Phase Sidebar       |  수임처 테이블                               |
|                     |  [▶전체실행] [선택건 실행]                   |
| 1 수임처리스트      |  수임처명       | 사업자등록번호 | 포털 | 활성 |
|   (24건)            |  ──────────────────────────────────────────  |
|                     |  (주)제이에스    | 515-86-01709 | wehago | O    |
| 2 건강보험     ✓   |  삼성전자(주)    | ...          | wehago | O    |
|   (12/24)           |  ...                                        |
|                     |  ── 세부 단계 ──                            |
| ▶ 3 국민연금        |  [✓] 1. 사업장 선택                         |
|   (5/24 진행중)     |  [▶] 2. 결정내역 이동                       |
|                     |  [ ] 3. 2차 상세 진입                       |
| 4 WEHAGO 급여입력   |                                             |
| 5 WEHAGO 급여PDF    |                                             |
| ▶ 6 WEHAGO 이행     |                                             |
| 7 WEHAGO 전자신고   |                                             |
| 8 홈택스 신고       |                                             |
+---------------------+---------------------------------------------+
|  [14:32:11] [국민연금] 삼성전자 - 결정내역 이동...                 |
|  [14:32:15] [국민연금] 삼성전자 - 2차 행 발견 (row=3)              |
+------------------------------------------------------------------+
```

### Phase 1 선택 시
- "새로 가져오기" / "모두 삭제" 버튼 표시
- 수임처 목록 테이블에 포털/활성 컬럼 표시

### Phase 2+ 선택 시
- "전체실행" / "선택건 실행" 버튼 표시
- "전체실행" 클릭 시 버튼이 "정지"(빨강)로 토글되어 실행 중 중단 가능
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
│   │   ├── wehago_salary_pdf.py    # Phase 5
│   │   ├── wehago_swta.py          # Phase 6
│   │   ├── wehago_swer.py          # Phase 7
│   │   └── hometax.py              # Phase 8
│   │
│   ├── automation/                 # 포털별 자동화 (수정 없이 재사용)
│   │   ├── wehago/                 # WEHAGO 포털
│   │   │   ├── _common.py          # 공통 함수 (로그인, 수임처 검색 등)
│   │   │   ├── _nts.py             # WehagoNTS (Windows Forms) COM 제어
│   │   │   ├── run_swsa0101.py     # 급여자료입력
│   │   │   ├── run_swta0101.py     # 원천이행상황신고서
│   │   │   └── run_swer0101.py     # 원천전자신고
│   │   ├── nhis/                   # 국민건강보험 EDI
│   │   │   ├── _common_edi.py      # 재export 허브 (import 호환성 유지)
│   │   │   ├── _nexacro.py         # Nexacro 초기화/라디오/그리드 제어 + 상수
│   │   │   ├── _firm_selector.py   # 수임사업장 선택/검색/페이징
│   │   │   ├── _doc_download.py    # 받은문서 열기, 서식 선택, PDF 다운로드
│   │   │   └── nhis_edi_auto_cdp.py# 전체 워크플로우
│   │   ├── nps/                    # 국민연금 EDI (Nexacro)
│   │   │   ├── _common.py          # 재export 허브 + 연결/네비/사업장전환
│   │   │   ├── _output.py          # 출력/PDF/Excel 다운로드, 탭 제어
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
│       ├── save_path.py            # 다운로드 저장 경로 생성 (사이트명_연월/수임처)
│       ├── nexacro.py              # Nexacro 공통 이벤트 dispatch (click/dblclick/combo/radio)
│       └── polling.py              # 비동기 폴링 (wait_for_element, wait_for_new_tab)
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
| 1, 4, 5, 6, 7 | WEHAGO | https://www.wehago.com/ |
| 2 | 국민건강보험 EDI | https://edi.nhis.or.kr/ |
| 3 | 국민연금 EDI | https://edi.nps.or.kr/ |
| 8 | 홈택스 | https://www.hometax.go.kr/ |

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

### 배포 방식 (최종 사용자 PC)

최종 사용자는 **인스톨러(`원천징수자동화_설치.exe`, Inno Setup)** 로 설치합니다. **Python이나 패키지 설치 불필요** — PyInstaller onedir 번들에 Python 인터프리터·모든 의존·Playwright node 드라이버·Qt 플러그인·VC++ 런타임이 모두 포함됩니다. 관리자 권한도 불필요(`%LOCALAPPDATA%` per-user 설치).

> **중요**: 인스톨러/본 exe 모두 **코드 서명이 없어** 최초 실행 시 Windows SmartScreen 파란 차단 화면이 뜹니다. 사용자가 "추가 정보 → 실행"으로 우회해야 합니다. (USB/공유폴더 직접 전달 시 SmartScreen 비발생.)

실행 전제 조건(최종 사용자):
- **Google Chrome**(공식 stable) 설치 — 인스톨러가 미설치 시 설치를 차단
- 프로그램 계정(Supabase) — 첫 실행 로그인. 담당자 발급

### 개발 환경 설정 (개발자 PC)

`setup.bat`를 **관리자 권한으로 실행** (우클릭 → 관리자 권한으로 실행) — **개발자 전용**:

1. 관리자 권한 확인
2. Python 3.10+ 설치 여부 및 버전 확인
3. pip 업그레이드
4. `requirements.txt` 패키지 일괄 설치 (PySide6, Playwright, pywinauto, PyMuPDF, pdfplumber 등)
5. Playwright node 드라이버 설치 (`playwright install chromium` — **개발용**)
6. Google Chrome 설치 여부 확인

사전 요구:
- **Python 3.10+**: 미설치 시 python.org 또는 Microsoft Store에서 설치 (PATH 추가 필수)
- **Google Chrome**: 미설치 시 google.com/chrome에서 설치

### 개발 모드

```bash
# 의존성 설치
pip install -r requirements.txt
playwright install chromium   # 개발용 드라이버. 배포 exe에는 포함되지 않음(아래 참고)

# GUI 실행
python gui_main.py

# CLI 실행 (기존)
python main.py
```

### EXE 빌드 + 인스톨러

```bash
python build.py
# 산출물:
#   dist/원천징수자동화/             (PyInstaller onedir: 원천징수자동화.exe + _internal/)
#   installer_output/원천징수자동화_설치.exe  (Inno Setup 인스톨러, ~233MB)
```

빌드 설정 (`build.py`):
- `--windowed` + `--noupx`: 콘솔 없는 GUI, 압축 없음(안정성)
- **onedir** (onefile 아님) — `dist/원천징수자동화/` 폴더 + `_internal/`
- `--collect-submodules`: PySide6, playwright, playwright_stealth, comtypes, pywinauto, **pdfplumber, PyMuPDF, src** (함수 내부 import 누락 방지)
- `--add-data`: Playwright node 드라이버(`playwright/driver/node.exe`), `style.qss`
- **`verify_bundle()`**: 빌드 후 PYZ(순수-Python) + `_internal`(네이티브) 핵심 의존 실제 포함 여부 검증 (릴리스 전 필수)

> **Playwright 브라우저 바이너리는 배포에 필요 없음**: production 코드는 `chromium.launch()` 대신 **`connect_over_cdp`** 로 사용자의 실제 Chrome(포트 9223)에 연결합니다. 따라서 `playwright install chromium`의 결과물(수백 MB)을 번들에 포함하지 않습니다. `playwright install`은 개발용 드라이버 확보 목적으로만 사용합니다.

실행 전제 조건(배포 exe):
- Chrome이 시스템에 설치되어 있어야 함 (인스톨러가 검사)
- **Playwright 브라우저 바이너리 설치 불필요** (`connect_over_cdp` 사용)

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
| pdfplumber | NHIS 가입자고지내역서 PDF 파싱 (raw_data_reader) |
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
| 사업장관리번호로 수임처 검색 | 동명 수임처 구분 및 정확한 매칭. 사업자등록번호에서 `-` 제거 후 `0` 추가. |
| 단건 실행에 NoopStateManager 사용 | BatchEngine 오버헤드 없이 단일 수임처 즉시 실행. |

## 12. 안티디텍션 (Anti-Bot Detection)

자동화 세션이 서버 측 행동 분석에 탐지되는 것을 방지하기 위해 다계층 방어 적용.

### 12.1 브라우저 핑거프린트 보호

`src/utils/stealth.py` — playwright-stealth 기반, 핑거프린트 불일치를 최소화하는 보수적 설정:

| 항목 | 처리 |
|------|------|
| `navigator.webdriver` | 패치 (자동화 탐지 1순위 지표) |
| `navigator.plugins`, `permissions`, `vendor` | 패치 |
| `chrome.app`, `chrome.csi`, `chrome.loadTimes` | 패치 |
| `hairline`, `iframe contentWindow`, `Error.prototype` | 패치 |
| GPU/CPU/플랫폼/UA/Language | **실제값 유지** (스푸핑 시 불일치로 역탐지 위험) |
| Chrome 프로필 | **실제 사용자 프로필** 사용 (junction 링크) |

핵심 철학: 핑거프린트를 위조하지 않고 **실제 브라우저 환경을 그대로 사용**하면서 자동화 흔적(`navigator.webdriver` 등)만 제거.

### 12.2 타이밍 패턴 위장

`src/utils/human.py` → 전체 자동화 모듈 적용:

| 기법 | 설명 |
|------|------|
| **랜덤 지터 (±30%)** | 행동 sleep 48개를 `human_delay()`로 교체. `sleep(3)` → 2.1~3.9초 랜덤 |
| 짧은 딜레이 보호 | `base < 1s`면 jitter를 15%로 자동 축소 (기능 유지) |
| 폴링 sleep 유지 | 로그인/다운로드/Nexacro 대기 등 21개는 고정 간격 유지 (불규칙 폴링 자체가 탐지 대상) |
| **수임처 간 휴식** | 5~8건 처리 후 5~15초 무작위 휴식 (`human_break()`). stop 이벤트로 중단 가능 |

적용 파일: `_common.py`(NPS), `_common_edi.py`(NHIS), `nps_auto_cdp.py`, `nhis_auto_cdp.py`, `nps_edi.py`, `nhis_edi.py`, `automation_runner.py`

### 12.3 마우스 이벤트 시뮬레이션

Nexacro 그리드/버튼 클릭 시 `dispatchEvent`로 발생시키는 마우스 이벤트에 3가지 인간적 패턴 적용. NPS 2개 + NHIS 8개 JS 블록.

| 기법 | 설명 |
|------|------|
| **mousemove 선행** | mousedown 전에 커서 도착 시뮬레이션 (`buttons: 0`) |
| **좌표 랜덤 오프셋** | 요소 중앙에서 ±2px 무작위 편차 (정밀 클릭 탐지 회피) |
| **클릭 간 인간적 지연** | mousedown↔mouseup 사이 30~80ms busy-wait (`performance.now()`) |

이벤트 시퀀스 (단일 클릭):
```
mousemove(detail=0, buttons=0) → [30~80ms] → mousedown(1) → mouseup(1) → click(1)
```

이벤트 시퀀스 (더블클릭):
```
mousemove(detail=0, buttons=0) → [30~80ms] → click(1) → [30~80ms] → click(2) + dblclick(2)
```

### 12.4 세션/인증 관리

| 기법 | 설명 |
|------|------|
| **수동 로그인** | 공동인증서 인증은 사용자가 직접 수행 (가장 강력한 방어선) |
| 세션 연장 자동 처리 | NHIS 25분 비활동 시 연장 팝업 자동 클릭 |
| Chrome `--start-maximized` | 최대화 창으로 실행 (인간 사용 패턴) |
| 단계별 체크포인트 | StateManager로 진행 상황 저장 → 재시작 시 이어서 진행 (중복 요청 방지) |

### 12.5 방어 계층도

```
서버 측 탐지 벡터              방어 기법
────────────────────────     ────────────────────────
 navigator.webdriver       →  playwright-stealth 패치
 핑거프린트 불일치          →  실제 Chrome 프로필 + 실제 하드웨어
 규칙적 요청 간격           →  human_delay ±30% 랜덤 지터
 연속 처리 패턴             →  5~8건마다 5~15초 무작위 휴식
 완벽한 클릭 좌표           →  ±2px 랜덤 오프셋
 마우스 이동 없는 클릭       →  mousemove 선행 이벤트
 일정한 클릭 간격           →  30~80ms 랜덤 지연
 인증서 없는 로그인         →  수동 공동인증서 (Human-in-the-loop)
```

## 10. 리팩토링 TODO

> 2026-06-12 commit `6d428ec`에서 Step 1~5, 8 완료. 아래 항목은 별도 PR로 진행 예정.

### TODO-1: `batch/db.py` 분할 (1,112줄)
- `db.py` → `queries.py`(~500줄) + 슬림 `db.py`(~400줄 + 재export)
- DB 레이어 전체에 영향 → 별도 검증 필요

### TODO-2: `sys.path.insert` import 정리
- 여러 파일에서 반복: `sys.path.insert(0, os.path.abspath(...))`
- `pyproject.toml` 또는 `src/__init__.py`에서 중앙화
- 전체 모듈에 분산되어 있어 광범위 테스트 필요
