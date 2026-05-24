# WEHAGO 자동화 진행 상황

## 파일 위치
- `src/automation/wehago/wehago_auto_cdp.py` — 메인 자동화 스크립트
- `src/automation/nhis/` — 기존 NHIS 자동화 (참고용)
- `results/` — 다운로드/변환된 엑셀 파일 저장 위치

## 기술 스택
- **Playwright + CDP** (Chrome DevTools Protocol)
- Chrome을 `--remote-debugging-port=9223`로 실행 후 Playwright로 연결
- **openpyxl** — 엑셀 파일 다운로드/업로드 양식 변환
- **pywinauto** — WEHAGO PrintDialog (OS 레벨 Windows Forms 앱) 제어
- **Human-in-the-loop**: 복잡한 인증은 사용자가 수동 로그인, 이후 자동화가 제어권 이어받음

## 현재 수임처 (테스트 대상)
| 수임처 | Company ID | 비고 |
|--------|-----------|------|
| 근린건축 | company_5603386 | cNum=5603386 |
| 근린커피 | company_5599115 | |
| 근린커피 상암 | company_5603395 | cNum=5603395, **현재 타겟** |

## 자동화된 프로세스 (15단계)

### [1/15] Chrome 디버깅 모드 실행
- `launch_chrome()`: Chrome을 `--remote-debugging-port=9223` + 전용 user-data-dir로 실행
- 이미 CDP 포트가 열려있으면 기존 Chrome에 연결

### [2/15] 로그인 + 랜딩 팝업 닫기
- `wait_for_login()`: 수동 로그인 대기 (Enter 입력)
- `dismiss_dialogs()`: `_isDialog`, `LUX_basic_dialog` 타입 팝업 자동 탐지 후 닫기
  - 닫기 순서: 닫기 → X → 확인(btnbx) → 확인 → 취소

### [3/15] 수임처 급여(SmartA) 페이지 이동
- `goto_salary_page()`: window.open 인터셉트 방식으로 URL 캡처 후 이동
- **핵심 트릭**: Playwright click이 타임아웃되므로 `window.open`을 가로채서 URL만 가져온 뒤 `page.goto()`로 직접 이동
- 카드 구조: `company_[id]` → 3단계 상위 = `divtbl_bx` (카드 하나의 범위)

### [4/15] 급여자료입력 메뉴 이동
- `click_menu("SWSA0101")`: 사이드 메뉴의 `a#SWSA0101.text_link` 클릭
- SPA 내부 라우팅 (페이지 리로드 없이 URL 해시 변경)

### [5/15] 구분 드롭다운 → 급여+상여 선택
- `select_dropdown(0, "급여+상여")`: 커스텀 드롭다운(LS_ngh_select2) 조작
  - `.LSbutton` 클릭으로 열기 → `.LSselectResult li`에서 텍스트 매치 후 클릭
  - 드롭다운 인덱스 0 = 첫 번째 드롭다운 (구분)

### [6-7/15] 복사후 재계산 모달 (조건부)
- 구분 변경 시 모달이 뜨는지 먼저 감지
- **모달 있으면**: "복사후 재계산" 클릭 → "취소" 클릭
- **모달 없으면**: 스킵하고 다음 단계로

### [8/15] 엑셀 다운로드
- `download_excel()`: `#collect` 버튼 → 드롭다운 → "엑셀 내려받기" 클릭
- 다운로드된 파일을 `results/` 디렉토리에 저장
- 파일명 예: `근린커피 상암-202605.xlsx`

### [9/15] 업로드 양식 변환
- `convert_for_upload()`: 다운로드 파일을 WEHAGO 업로드 양식으로 변환
- 변환 규칙:
  1. 행1(대분류) + 행2(세부항목) 헤더를 단일 행으로 평탄화 (행2 우선, 없으면 행1)
  2. **모든 열을 동적으로 보존** (수당/공제 항목 수가 회사마다 다름)
  3. 마지막 합계 행 제거
  4. 사원코드: 4자리 0-pad 문자열 (예: `"0005"`)
- 출력 파일: `{원본명}_업로드.xlsx`

### [10/15] 엑셀 업로드
- `upload_excel()`: `#collect` 버튼 → 드롭다운 → "엑셀 불러오기" → file chooser로 파일 선택
- 업로드 후 모달 6단계 처리:
  1. **① 엑셀내역**: 헤더 행(행1)을 CDP 마우스 이벤트로 클릭하여 선택 (JS click은 동작하지 않음)
  2. **② 엑셀제목설정**: 버튼 클릭 → 열 매핑 확인 (자동 매핑됨)
  3. **확인 버튼**: 모달 하단 확인 클릭으로 업로드 확정 (`WSC_LUXButton`, rect.top > 700)
  4. **후속 모달 1/3**: `#confirm` 셀렉터로 확인 클릭 (항상 — 데이터 저장)
  5. **후속 모달 2/3**: dry_run=True → 취소, False → 확인 (재계산 여부)
  6. **후속 모달 3/3**: 확인 (항상 — 완료 확인)
- 에러 모달 감지 후 결과 반환

### [11/15] #print 버튼 → 일괄출력 실행
- `open_print_dialog(page)`: 브라우저에서 `#print` 버튼 클릭 → 드롭다운에서 "일괄출력" 클릭
- WEHAGO PrintDialog (Windows Forms 앱, `Duzon - PrintDialog`) 가 별도 프로세스로 실행됨
- PrintDialog 경로: `C:\Douzone\Wehago\WehagoPrint`
- pywinauto로 OS 레벨에서 제어 (Playwright가 아닌 Windows UI Automation)

### [12/15] 인쇄형태 선택
- `_select_print_format(target_text)`: PrintDialog의 인쇄형태 ComboBox (`auto_id="cbContents"`) 에서 항목 선택
- `auto_id` + `control_type` + `CurrentName` 기반 탐색 (좌표 독립)
- 인쇄형태 옵션: 급여명세(구), 급여대장, 급여대장(부서별), 급여대장(비과세계), 창봉투, **급여명세(사원당 한장)**, 급여명세(전체항목), 급여대장(부서별비과세계), 급여대장(근로기준법), 급여대장(주민번호출력), 급여명세서(근로기준1~5)

### [13/15] PDF 저장
- `_click_save_pdf()`: PrintDialog의 PDF 버튼 (`auto_id="btnSavePDF"`) 클릭
- Windows "다른 이름으로 저장" 대화상자 (`#32770`) 등장
- `_handle_save_dialog(save_path)`: 파일 경로 입력 → 저장 버튼 (`저장(&S)`) 클릭
- 저장 위치: `results/` 디렉토리

### [14/15] PrintDialog 종료
- `_close_print_dialog()`: 닫기 버튼 (`auto_id="btnClose"`) 클릭

### [15/15] 원천징수이행상황신고서 페이지 이동
- `goto_menu_page(page, "SWTA0101")`: 현재 SmartA URL의 메뉴 ID 해시를 `SWTA0101`로 교체하여 이동
- 사이드 메뉴에 보이지 않는 메뉴도 URL 직접 교체로 접근 가능
- 메뉴 ID: `SWSA0101` (급여자료입력) → `SWTA0101` (원천징수이행상황신고서)

### [15-1] 매월/반기 → 귀속기간/지급기간 설정
- `get_report_period_type(page)`: 표 내 라디오 버튼(`input.LSinput[type=radio]`)에서 매월/반기 체크 상태 읽기
- `set_period_fields(page, year, start_month, end_month)`: `#SearchMain` 상단 기간 설정 영역 조작
- **기간 계산 로직**:
  - **매월**: 현 시점 기준 저번달 (예: 2026년 5월 → `2026년 04월 ~ 04월`)
  - **반기**: 올해 `01월 ~ 06월`
- **페이지 구조** (`#SearchMain > .item[]`):
  | idx | 항목 | 컨트롤 |
  |-----|------|--------|
  | 0 | 귀속기간 | `div[tabindex=0]` × 4 (시작년도, 시작월표시, 종료년도, 종료월표시) |
  | 1 | 지급기간 | 동일 |
  | 2 | 신고구분 | `"0. 정기신고"` 커스텀 드롭다운 |
  | 3 | 신고리스트 | 버튼 |
  | 4 | 수정차수 | `"1"` 커스텀 드롭다운 |
- **연도 설정**: `div[tabindex=0]` 클릭 → Ctrl+A → Delete → 연도 타이핑 → Enter
- **월 설정**: 화살표 버튼(`button .WSC_LUXSpriteIcon` → `closest("button")`) 클릭 → React 드롭다운에서 `li div` 텍스트 매치 후 클릭 (`01`~`12`)

### [15-2] 조회 버튼 클릭
- `#Search button` 중 텍스트 `"조회"`인 버튼을 JS `btn.click()`으로 클릭
- `mouse.click` 좌표 방식은 불안정 → JS 직접 클릭 사용

### [15-3] 마감/마감해제 버튼 처리
- 조회 후 `.sao_head_menu button.WSC_LUXButton` 첫 번째 버튼 텍스트 확인
- **"마감"** → 클릭하여 마감해제 (잠금 상태이므로 해제 필요)
- **"마감해제"** → 스킵 (이미 해제된 상태)

---

## 주요 함수 레퍼런스

| 함수 | 용도 |
|------|------|
| `launch_chrome()` | Chrome 디버깅 모드 실행 |
| `connect_browser()` | CDP 연결, page 객체 반환 |
| `wait_for_login()` | 수동 로그인 대기 |
| `dismiss_dialogs()` | 모든 팝업/다이얼로그 닫기 |
| `get_client_salary_url()` | window.open 인터셉트로 SmartA URL 캡처 |
| `goto_salary_page()` | 수임처 급여 페이지 이동 |
| `click_menu(menu_id)` | 사이드 메뉴 클릭 (SPA 라우팅) |
| `select_dropdown(idx, text)` | 커스텀 드롭다운 옵션 선택 |
| `click_dialog_button(text)` | 현재 모달에서 특정 버튼 클릭 |
| `open_collect_menu()` | 우측 끝 #collect 드롭다운 열기 |
| `click_menu_item(text)` | 드롭다운에서 특정 메뉴 항목 클릭 |
| `download_excel(page, save_dir)` | 엑셀 내려받기 → 파일 저장 |
| `convert_for_upload(download_path)` | 다운로드 → 업로드 양식 변환 |
| `upload_excel(page, file_path)` | 엑셀 불러오기로 파일 업로드 |
| `download_pdf(page, save_dir, print_format)` | PrintDialog 통해 PDF 다운로드 (11-14단계 통합) |
| `_close_existing_print_dialog()` | 기존 PrintDialog + 경고 모달 정리 (pywinauto) |
| `_print_dialog_exists()` | PrintDialog 떠 있는지 확인 (pywinauto) |
| `open_print_dialog(page)` | #print → 일괄출력 클릭 (브라우저) |
| `_select_print_format(target_text)` | PrintDialog 인쇄형태 드롭다운 선택 (pywinauto) |
| `_click_save_pdf()` | PrintDialog PDF 저장 버튼 클릭 (pywinauto) |
| `_handle_save_dialog(save_path)` | Windows 저장 대화상자 처리 (pywinauto) |
| `_close_print_dialog()` | PrintDialog 종료 (pywinauto) |
| `goto_menu_page(page, menu_id)` | SmartA 내 메뉴 URL 해시 교체 이동 |
| `get_report_period_type(page)` | 매월/반기 라디오 상태 반환 |
| `set_period_fields(page, year, start_month, end_month)` | 귀속기간/지급기간 설정 (연도+월) |

## 엑셀 다운로드/업로드 구조

### 다운로드 엑셀 (RAW)
- 2행 헤더 (행1: 대분류, 행2: 세부항목)
- 마지막 행: 합계
- 열 수는 회사마다 다름 (수당/공제 항목 수에 따라 19열~29열+)
- 예: 공임나라김천모임점 19열, 근린커피 상암 29열

### 업로드 엑셀 (변환 후)
- 1행 헤더 (행2 세부항목 우선, 없으면 행1 대분류 사용)
- 합계 행 제거
- **다운로드와 동일한 열 수** 보장 (모든 수당/공제 항목 보존)
- 사원코드: 4자리 0-pad 문자열 (예: `"0005"`)

## 알려진 이슈 & 해결 방법

| 이슈 | 원인 | 해결 |
|------|------|------|
| Playwright click 타임아웃 | 급여 버튼이 window.open으로 새 창을 열려고 함 | window.open 인터셉트 후 page.goto() |
| 잘못된 회사 URL 캡처 | parent 5단계 위로 올라가 전체 카드 리스트를 잡음 | parent 3단계로 수정 (divtbl_bx) |
| LUX_basic_dialog 미탐지 | _isDialog만 탐지하던 초기 코드 | selectors 배열에 .LUX_basic_dialog 추가 |
| 팝업 허용 안됨 | Chrome 기본 팝업 차단 | Preferences 파일에 [*.]wehago.com setting:1 추가 |
| 엑셀 내려받기 클릭 안됨 | li가 아닌 a 태그를 클릭해야 함 | li.querySelector('a').click() 사용 |
| pywinauto 한국어 title 인코딩 | `child_window(title='급여명세...')` 시 UnicodeError | `element_info.element.CurrentName` 직접 비교 |
| PrintDialog ListItem 탐색 | 드롭다운 닫힌 상태에서 ListItem 미노출 | 열기 버튼 클릭 후 `cb.descendants(control_type='ListItem')` 사용 |
| PrintDialog expand() 불가 | WindowsForms 커스텀 ComboBox | 자식 Button(열기) 클릭으로 드롭다운 열기 |
| 기존 PrintDialog 중복 실행 | 이미 떠 있으면 "이미 인쇄함이 있습니다" 경고 모달 | `_close_existing_print_dialog()` 로 경고 모달 닫기 후 종료 |
| Windows 저장 대화상자 탐지 | pywinauto uia backend에 미표시 | win32 backend로 `#32770` 클래스 탐색 |
| LSinput 비밀번호 1회 입력 실패 | keyboard type만으로 fakeinput(placeholder) 미갱신 | native setter + fakeinput 직접 조작 (`classList.remove('placeholder')`) |
| 지급기간 설정 불안정 | 연도/월 드롭다운이 간헐적으로 이전 값 유지 | 3회 재시도 + 4개 값(시작년/월, 종료년/월) 전체 검증 |
| WehagoNTS 폴더 선택 | pywinauto `find_elements` 불안정 (RemoteMemoryBlock 오류) | COM UIAutomation (`comtypes.client`) 직접 사용 |
| "이미 기록된 파일" 무한 루프 | 덮어쓰기 질의에서 예(Y) 눌러도 같은 질의 반복 | `select_nts_folder()`에서 질의/안내 모달 자동 분기 처리 |
| 전자신고 제출 후 에러 오감지 | '전자신고 파일 제작' 성공 메시지를 에러로 분류 | 에러 감지에서 성공/안내 키워드 제외 |

### [16] 원천징수 전자신고(SWER0101) 이동
- `page.reload()`로 페이지 새로고침 (URL 해시 교체 불필요, 이미 SWER0101에 위치)
- 제출자등록 안내 모달, z-index overlay 자동 닫기

### [16-1] 지급기간 설정 (검증 포함)
- `set_period_fields(page, year, start_month, end_month)` 사용
- **3회 재시도 + 전체 값 검증**: 시작년도, 시작월, 종료년도, 종료월 4개 값이 모두 일치해야 통과
- 기간 계산: 현재 기준 저번달 (1월이면 전년 12월)

### [17] 수임처 아이콘 → 코드도움 확인
- `#SearchMain .item`에서 '수임처' 포함 항목 찾기
- 빈 텍스트 `button.WSC_LUXButton` 클릭 → 코드도움 모달 오픈
- `click_codehelp_confirm()`: iframe 포함 모든 frame에서 '코드도움' → '확인(enter)' 클릭

### [18] 제작(F4) 버튼 클릭
- `button.WSC_LUXButton` 중 '제작(F4)' 텍스트, y < 200, visible 조건

### [19] 모달 대기
- `._isDialog`에서 '변환파일 비밀번호'(pwd) 또는 '참고사항'(ref) 감지
- 참고사항 모달은 `dismiss_dialogs()`로 닫고 비밀번호 모달 대기

### [20] 비밀번호 입력 + 전자신고 파일 제작
- **LSinput 컴포넌트 특성**: keyboard type만으로는 `.fakeinput.placeholder`가 갱신 안 됨
- **해결**: native setter로 `input.value` 설정 + `.fakeinput` 직접 조작
  ```js
  setter.call(inp, pwd);         // input.value 설정
  fake.classList.remove('placeholder');  // placeholder 클래스 제거
  fake.textContent = pwd;         // fakeinput 텍스트 설정
  ```
- 검증: `input.value` + `fakeinput.textContent` 모두 일치해야 제출
- 에러 감지: 성공/안내 메시지('전자신고 파일 제작', '홈택스 ID', '비밀번호는 최소')는 에러에서 제외
- '전자신고 파일 제작(Enter)' 버튼 클릭

### [21] WehagoNTS 폴더 선택 + 파일 저장
- WehagoNTS.exe는 브라우저에서 전자신고 파일 제작 시 자동 실행되는 Windows Forms 프로그램
- **COM UIAutomation** (`comtypes.client`)으로 제어 (pywinauto 불안정)
- **처리 흐름**:
  1. WehagoNTS 프로세스 대기 (최대 20초)
  2. "이미 기록된 파일" 질의 → 예(Y) 자동 클릭 (분기 처리)
  3. `FormSelectFolder` 창에서 `treeDir` 트리 탐색
  4. 바탕화면(`TreeItem`) 확장 → 지정 폴더 선택
  5. `btnOK` Invoke 패턴으로 확인 클릭
  6. 후속 모달 루프: "질의"(예(Y)) / "안내"(확인) 자동 처리
  7. 바탕화면에 남은 `.01` 파일 → 폴더로 이동

- **NTS 창 구조** (`auto_id`):
  | auto_id | 컨트롤 | 용도 |
  |---------|--------|------|
  | `FormSelectFolder` | Window | 폴더 선택 다이얼로그 |
  | `treeDir` | Tree | 폴더 트리 뷰 |
  | `lblSelectNode` | Text | 현재 선택 경로 표시 |
  | `btnOK` | Button | 확인 |
  | `btnCancel` | Button | 취소 |
  | `6` | Button | 예(Y) (질의 모달) |
  | `7` | Button | 아니요(N) (질의 모달) |
  | `2` | Button | 확인 (안내 모달) |

- **저장 결과**: `Desktop/원천징수전자신고/YYYYMMDDCXXXXXX.01`

### 실행 스크립트
- `_run_swer.py`: SWER0101 전체 자동화 (16~22단계)

---

## 다음 단계 (TODO)
- 엑셀 변환 시 특정 셀 값 수정 로직 (수당/공제 항목 변경)
- 근로소득원천징수영수증 발급
- 다른 수임처 반복 처리 로직
- 재계산 → 완료 처리 자동화
- Hometax 원천세 신고 자동화

## 실행 방법
```bash
python src/automation/wehago/wehago_auto_cdp.py
```
