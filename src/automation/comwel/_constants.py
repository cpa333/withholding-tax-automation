"""근로복지공단(고용보험) EDI 자동화 상수 모듈

엑셀 v3 워크플로우(C86~H106) + 라이브 DOM 검증(2026-07) 기반.
근로복지공단 토탈서비스(total.comwel.or.kr)는 w2 프레임워크 기반 SPA.

주의: '인쇄하기'/'엑셀저장' 버튼의 id(wq_uuid_XXXX)는 매 렌더링마다 동적 생성되어
고정 id로 잡을 수 없으므로, 텍스트 매칭 + 팝업 컨테이너 범위로 클릭해야 한다.
"""

# ─── URL ──────────────────────────────────────────────────────────────────────

COMWEL_URL = "https://total.comwel.or.kr"
COMWEL_MAIN = "https://total.comwel.or.kr"

# ─── 메뉴 id (라이브 검증) ─────────────────────────────────────────────────────
# 상단 GNB 메뉴. 정보조회 클릭으로 2단계 펼침 → 다시 클릭으로 접음(토글).

# 1단계: 정보조회 (클릭으로 서브메뉴 토글)
MENU_INFO_INQUIRY_ID = "mf_wfm_header_gen_firstGenerator_1_menu1_Label"
# 2단계: 보험료정보 조회
MENU_PREMIUM_INQUIRY_ID = "mf_wfm_header_gen_firstGenerator_1_gen_SecondGenerator_2_menu2_Label"
# 3단계: 부과고지 보험료 조회(20209)
MENU_PREMIUM_20209_ID = "mf_wfm_header_gen_firstGenerator_1_gen_thirdGenerator_7_menu3_Label"
# 본문 퀵메뉴: 부과고지 보험료 조회(20209) — 메인 대시보드에서 바로 진입
QUICKMENU_20209_ID = "mf_wfm_content_gen_firstGenerator_1_quickMenu"

# ─── 사업장 검색/선택 id (라이브 검증) ──────────────────────────────────────────

# 메인 화면 관리번호 입력란
INPUT_MGMT_NO_ID = "mf_wfm_content_maeGwanriNo"
# 사업장조회 버튼 (관리번호 입력란 바로 오른쪽 "검색/사업장관리번호 찾기")
BTN_WORKPLACE_SEARCH_ID = "mf_wfm_content_btnSaeopjangSearch"
# 부과년도 select
SELECT_YEAR_ID = "mf_wfm_content_comYear_input_0"
# 부과월 select
SELECT_MONTH_ID = "mf_wfm_content_comMM_input_0"

# 사업장 정보조회 팝업(WZ0101_P01)
POPUP_WORKPLACE_ID = "mf_wfm_content_WZ0101_P01"
POPUP_WORKPLACE_CLOSE_ID = "mf_wfm_content_WZ0101_P01_close"
POPUP_WORKPLACE_MGMT_NO_ID = "mf_wfm_content_WZ0101_P01_wframe_maeGwanriNo"
POPUP_WORKPLACE_SEARCH_BTN_ID = "mf_wfm_content_WZ0101_P01_wframe_btnSearch"
# 검색 결과 행의 '선택' 버튼 (첫 행: button_0_0)
POPUP_WORKPLACE_SELECT_BTN_PREFIX = "mf_wfm_content_WZ0101_P01_wframe_GridMain_button_"
# 검색 결과 행 클래스 (grid_body_row)
WORKPLACE_GRID_ROW_CLASS = "grid_body_row"

# ─── 탭 / 다운로드 id (라이브 검증) ─────────────────────────────────────────────

# 산재/고용 하단 탭
TAB_SANJEONG_ID = "mf_wfm_content_tabcont_tab_btnTabSj_tabHTML"   # 산재
TAB_EMPLOYMENT_ID = "mf_wfm_content_tabcont_tab_btnTabGy_tabHTML"  # 고용
# 사회보험료 지원금정보 버튼 (고용 탭 하위)
BTN_SUPPORT_INFO_ID = "mf_wfm_content_wq_uuid_1191"

# 사회보험료지원금 조회 팝업(WL0502_P02)
POPUP_SUPPORT_ID = "mf_wfm_content_WL0502_P02"
POPUP_SUPPORT_CLOSE_ID = "mf_wfm_content_WL0502_P02_close"
# 주의: 인쇄하기/엑셀저장 버튼 id(wq_uuid_XXXX)는 동적 → 텍스트 매칭 사용
BTN_PRINT_TEXT = "인쇄하기"      # 엑셀 E102
BTN_EXCEL_TEXT = "엑셀저장"

# ─── 로그인/팝업 id (라이브 검증) ───────────────────────────────────────────────

# 로그인 전용 가시 요소 (이들이 사라지면 로그인 완료)
PRELOGIN_BTN_LOGIN_ID = "mf_wfm_content_btnLogin"
PRELOGIN_GUEST_VIEW_ID = "mf_wfm_content_guestView"
# 로그인 후 사무대행기관 정보 확인 팝업 닫기
SAMU_POPUP_CLOSE_ID = "mf_wfm_content_samuInfoPopup_close"

# ─── 버튼 텍스트 ──────────────────────────────────────────────────────────────

BTN_INQUIRY = "조회"      # 팝업 내 조회 버튼

# ─── 타임아웃 (초) ────────────────────────────────────────────────────────────

LOGIN_TIMEOUT_S = 900              # 180 * 5s = 15분
PAGE_LOAD_TIMEOUT_MS = 30000       # page.goto 타임아웃 (ms)
DOWNLOAD_TIMEOUT_S = 60            # 인쇄물 다운로드
MENU_NAV_DELAY_S = 2               # 메뉴 이동 후 안정화 대기
POPUP_TIMEOUT_S = 15               # 팝업 출현 대기
WORKPLACE_SEARCH_DELAY_S = 3       # 사업장조회/선택 후 대기

# ─── 재시도 횟수 ───────────────────────────────────────────────────────────────

PRINT_CLICK_RETRIES = 3            # 인쇄 버튼 클릭 재시도
