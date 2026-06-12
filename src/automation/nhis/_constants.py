"""NHIS EDI 상수 모듈

모든 NHIS EDI 자동화에서 사용하는 URL, 요소 ID, 타임아웃 등의 상수를
단일 위치에 집중 관리.
"""

# ─── URL ─────────────────────────────────────────────────────────────────────
NHIS_EDI_URL = "https://edi.nhis.or.kr/"
NHIS_EDI_MAIN = "https://edi.nhis.or.kr/homeapp/wep/m/retrieveMain.xx"

# ─── Nexacro 요소 ID ─────────────────────────────────────────────────────────
RDO_PROG_STAT = "mainframe_childframe_form_div_body_rdo_prog_stat"
RADIO_ITEMS = {0: "전체", 1: "신규", 2: "열람"}
GRID_RECEIVED = "mainframe_childframe_form_div_body_grid_list"
GRID_BODY_ID = "mainframe_childframe_form_div_body_grid_list_body"
CBO_DOCID = "mainframe_childframe_form_div_body_cbo_docid"
BTN_PRINT = "mainframe_childframe_form_div_top_img_print"

# ─── 수임사업장 ──────────────────────────────────────────────────────────────
FIRM_LIST_URL = "retrieveFirmList.do"

# ─── 타임아웃 / 리트리 ────────────────────────────────────────────────────────
LOGIN_TIMEOUT_S = 900           # 15분 (180 * 5초)
DOCS_READY_TIMEOUT_S = 20       # 받은문서 페이지 안정 대기
PRINT_PREVIEW_TIMEOUT_S = 5     # 미리보기 탭 감지 타임아웃
PRINT_CLICK_RETRIES = 3         # 인쇄 버튼 3전략 재시도 횟수
CROWNIX_LOAD_TIMEOUT_S = 15     # Crownix 뷰어 로딩 대기
PDF_DOWNLOAD_TIMEOUT_S = 60     # PDF 다운로드 완료 대기
PAGE_STABLE_TIMEOUT_S = 15      # 페이지 안정화 대기
