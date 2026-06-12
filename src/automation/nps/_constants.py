"""국민연금 EDI 자동화 상수 모듈

모든 NPS 자동화에서 공유하는 상수: URL, 엘리먼트 ID, 타임아웃, 지연.
"""

# ─── URL ──────────────────────────────────────────────────────────────────────

NPS_URL = "https://edi.nps.or.kr"
NPS_NEXACRO_URL = "https://edi.nps.or.kr/nexacro/index.html"

# ─── Nexacro 그리드 ID ────────────────────────────────────────────────────────

GRID_WORKPLACE = (
    "mainframe.VFrameSet.FrameSdi.ChangeBusi"
    ".form.divPopBg.form.divPopWork.form.grdList"
)
GRID_DECISION_LIST = (
    "mainframe.VFrameSet.FrameSdi.form.divWork_M08010000"
    ".form.divWork.form.grdList"
)
GRID_DECISION_DETAIL = (
    "mainframe.VFrameSet.FrameSdi.form.divWork_M08010200"
    ".form.divWork.form.tab00.Tabpage1.form"
)

# ─── 버튼 ID ──────────────────────────────────────────────────────────────────

BTN_CHANGE_WORKPLACE = (
    "mainframe.VFrameSet.FrameSdi.form.divHeader.form.divHeader.form.btnChangeBusi"
)
BTN_OUTPUT = (
    "mainframe.VFrameSet.FrameSdi.form.divWork_M08010200"
    ".form.divWork.form.div00.form.btn02"
)
BTN_EXCEL_SAVE = (
    "mainframe.VFrameSet.FrameSdi.form.divWork_M08010200"
    ".form.divWork.form.div01.form.btn01"
)
BTN_INTEGRATED_SAVE = (
    "mainframe.VFrameSet.FrameSdi.form.divWork_M08010200"
    ".form.divWork.form.div01.form.btn02"
)

# ─── 결정내역 상세 탭 인덱스 ──────────────────────────────────────────────────

TAB_FINAL = 0      # 최종결정내역
TAB_RECEIPT = 1    # 수납내역
TAB_MEMBER = 2     # 가입자내역
TAB_RETRO = 3      # 소급분내역
TAB_GOVT = 4       # 국고지원내역

TAB_BTN_PREFIX = (
    "mainframe.VFrameSet.FrameSdi.form.divWork_M08010200"
    ".form.divWork.form.tab00.tabbutton_"
)

# ─── 출력 모달 (PDF) ──────────────────────────────────────────────────────────

MODAL_PREFIX = (
    "mainframe.VFrameSet.FrameSdi.UHJE0002P1"
    ".form.divPopBg.form.divPopWork.form"
)
RADIO_FULL_SSN = f"{MODAL_PREFIX}.div00_01.form.div01.form.rdo06.radioitem1"
BTN_MODAL_CONFIRM = f"{MODAL_PREFIX}.div00_00.form.btn01"
BTN_MODAL_CANCEL = f"{MODAL_PREFIX}.div00_00.form.btn00"

# ─── 엑셀 모달 ────────────────────────────────────────────────────────────────

EXCEL_MODAL_PREFIX = (
    "mainframe.VFrameSet.FrameSdi.UHJE0002P3"
    ".form.divPopBg.form.divPopWork.form"
)
EXCEL_RADIO_FULL_SSN = f"{EXCEL_MODAL_PREFIX}.div00_01.form.div01.form.rdo06.radioitem1"
EXCEL_BTN_CONFIRM = f"{EXCEL_MODAL_PREFIX}.div00_00.form.btn01"
EXCEL_BTN_CANCEL = f"{EXCEL_MODAL_PREFIX}.div00_00.form.btn00"

# ─── 통합저장 모달 ────────────────────────────────────────────────────────────

INTEGRATED_MODAL_PREFIX = (
    "mainframe.VFrameSet.FrameSdi.UHJE0002P2"
    ".form.divPopBg.form.divPopWork.form"
)
INTEGRATED_RADIO_FULL_SSN = f"{INTEGRATED_MODAL_PREFIX}.div00_01.form.div01.form.rdo06.radioitem1"
INTEGRATED_BTN_CONFIRM = f"{INTEGRATED_MODAL_PREFIX}.div00_00.form.btn01"
INTEGRATED_BTN_CANCEL = f"{INTEGRATED_MODAL_PREFIX}.div00_00.form.btn00"

# ─── 타임아웃 (초) ────────────────────────────────────────────────────────────

LOGIN_TIMEOUT_S = 900              # 180 * 5s = 15분
NEXACRO_READY_TIMEOUT_S = 30
PAGE_LOAD_TIMEOUT_MS = 30000       # page.goto 타임아웃 (ms)
DOWNLOAD_TIMEOUT_S = 60            # PDF 다운로드
EXCEL_DOWNLOAD_TIMEOUT_S = 30      # 엑셀/통합 다운로드
CROWNIX_LOAD_TIMEOUT_S = 15        # Crownix 뷰어 로딩
PREVIEW_TAB_TIMEOUT_S = 10         # rdPreview 탭 탐색
MODAL_WAIT_TIMEOUT_S = 5           # 모달 출현 대기

# ─── 재시도 횟수 ───────────────────────────────────────────────────────────────

OUTPUT_CLICK_RETRIES = 3           # 출력 버튼 클릭 재시도
OUTPUT_STRATEGIES = 3              # 클릭 전략 수
