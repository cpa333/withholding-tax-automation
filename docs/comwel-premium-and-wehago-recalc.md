# COMWEL 당월보험료 부과내역 다운로드 + WEHAGO 급여재계산 (2026-07-16)

이 문서는 2026-07-16 세션에서 추가한 두 기능을 정리한다.
- COMWEL 20209 당월보험료 부과내역(산재/고용) 다운로드 — commit `af0b795`
- WEHAGO SWSA0101 급여재계산 단계 — commit `600c9b7`

---

## 1. COMWEL 20209 당월보험료 부과내역 다운로드 (`af0b795`)

20209(부과고지 보험료 조회) 화면에 **당월보험료 부과내역조회(WL0502_P04)** 인쇄물 다운로드를
산재·고용 양 탭으로 추가. 수임처당 3단계 순서로 실행:

1. **산재** 탭 → 당월보험료 부과내역 PDF+엑셀
2. **고용** 탭 → 당월보험료 부과내역 PDF+엑셀
3. **고용** 탭 → 고용보험료 지원금 PDF+엑셀 (기존 흐름)

### 핵심 구현
- `download_premium_detail_printout` (`src/automation/comwel/_download.py`)
  - 텍스트 매칭 런처(당월보험료 부과내역, 동적 `wq_uuid` id 의존 금지) → WL0502_P04 팝업
  - 0건 스킵 + 폴더 미생성 → 인쇄하기 → ClipReport(`report_menu_pdf_download_button` / `report_menu_excel_download_button`)
  - WL0502_P02(지원금) 흐름과 동일 → 공유 헬퍼를 `popup_id` 매개변수화로 재사용(지원금 회귀 不變)
- `click_sanjeong_tab` / `click_employment_tab` (active-guard 토글 방지)
- `run_single_workplace` (`src/automation/comwel/comwel_auto_cdp.py`) — 3단계 try/except 격리(한 단계 예외 시 나머지 계속)

### 파일명 규칙
`당월보험료부과내역_{산재|고용}_{YYYYMM}.{pdf,xls}` — 탭별 충돌 회피.
기존 지원금명(`고용보험료지원금정보_{YYYYMM}`)은 유지.

---

## 2. WEHAGO SWSA0101 급여재계산 단계 (`600c9b7`)

급여자료입력 흐름에 **사원 전체 재계산** 단계를 엑셀 다운로드 직전에 삽입.

흐름: 메뉴이동 → **(재계산)** → 엑셀다운로드 → 변환(EI 병합) → 업로드 → PDF

### `recalculate_salary(page, *, category="고용보험 재계산")` (`src/automation/wehago/_swsa_excel.py`)
사원 전체 선택 → 재계산 버튼 → 지정 항목 체크 → 확인(2회) → 결과 모달 처리.

**★ 해상도 무관 (다른 PC 모니터와 무관):**
- **전체 선택** = RealGrid JS API (`window.Grids.getActiveGrid().checkAll(true)`) — 좌표 없음.
  Left_grid 포커스는 Playwright `locator('#Left_grid canvas')` 클릭(요소 live geometry 기반).
- **LUX 버튼/체크박스/확인** = real mouse click (`getBoundingClientRect` 중심) — JS `.click()` 무반응.
- **결과 모달** = `#confirm` (안정 id) 최대 15s 폴링 후 real click.

### 통합 지점
- `run_swsa0101()` (`src/automation/wehago/run_swsa0101.py`) — `recalculate=True`/`recalculate_category` 파라미터(기본 True). navigate 직후, download 직전 호출.
- `WehagoSwsaWorkflow` (`src/workflows/wehago_swsa.py`) — `recalculate` 스텝(step 3) 추가, download→4/convert→5/upload→6 리인덱스.

---

## 3. 핵심 gotcha (구현·운용 시 주의)

| 영역 | gotcha |
|---|---|
| COMWEL wq_uuid | 버튼 id `wq_uuid_XXXX`는 동적 → 항상 **텍스트 매칭** + 팝업 컨테이너 범위. |
| COMWEL 탭 | 조회 후 **산재**가 기본 활성. 탭 클릭은 **active-guard**(이미 활성 탭 재클릭 → 토글 → 데이터 소실). |
| COMWEL 엑셀저장 버튼 | WL0502_P04의 전용 엑셀저장 버튼은 암호 팝업(`excelPwd_popup`)을 거치고 **CDP로 파일 미포착** → 인쇄하기→ClipReport 경로로 PDF+엑셀 모두 확보(엑셀저장 직접버튼 미사용). |
| WEHAGO RealGrid | 사원 그리드(`#Left_grid`)는 canvas 렌더링. 전체선택은 DOM 체크박스가 아닌 **RealGrid JS API**(`Grids.getActiveGrid().checkAll`) + Playwright locator 포커스. `getActiveGrid()`는 포커스 그리드 기준이라 포커스 누락 주의. |
| WEHAGO LUX | 체크박스/버튼/확인은 **real mouse click** 필수(JS `.click()` 무반응, Playwright locator도 비가시 요소 잡으면 실패 → `getBoundingClientRect` 중심 `mouse.click`). |
| WEHAGO 재계산 결과 | "재계산할 사원이 없습니다" 가능(중도정산/연맹정산 완료 자) → `#confirm`으로 닫고 흐름 계속. |

---

## 4. 검증

- **pytest**: 129 passed(COMWEL 추가 시) → 153 passed(WEHAGO 재계산 추가 후). 회귀 없음.
- **라이브 CDP 검증**(리드플렉스 2026-06):
  - COMWEL: 산재 6건·고용·지원금 1건 각 PDF+엑셀 정상 다운로드. 산재/고용 데이터 상이 확인.
  - WEHAGO: 프로덕션 `recalculate_salary` 정상 동작(9명 선택→고용보험 재계산→확인×2→결과모달, True).
  - 전체 흐름 1-connection 완주: 재계산→다운로드→convert(EI 병합: 이민희 고용보험 **−16,450**)→upload(dry_run).

### EI 병합 공식 (참고)
고용지원금 raw(`고용보험료지원금정보_{YYYYMM}.xls`)의 실업급여지원금/환수금(근로자)이
WEHAGO 업로드 엑셀 "고용보험" 컬럼에 반영:
`adjustment = -abs(실업급여지원금) + abs(실업급여환수금)`, `adjustment != 0` 일 때만 기록
(0이면 WEHAGO 자동산정 0.9% 보존). 구현: `_apply_ei_row` (`src/utils/data_merger.py`).
