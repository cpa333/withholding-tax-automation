"""홈택스 자동화 상수 모듈

URL, 선택자, 타임아웃 등 홈택스 자동화에서 사용하는 상수.
"""

# ─── URL ─────────────────────────────────────────────────────────────────────
HOMETAX_URL = "https://www.hometax.go.kr"

# ─── 메뉴 선택자 ─────────────────────────────────────────────────────────────
SELECTOR_MENU_WITHHOLDING = '#menuAtag_4106010000'
SELECTOR_BTN_CBC_MEDI_RTN = '[id*="btn_cbcMediRtn"]'
SELECTOR_BTN_CEN_STS = '[id*="btn_cenSts"]'

# ─── 타임아웃 ────────────────────────────────────────────────────────────────
DEFAULT_TIMEOUT_MS = 30000         # 기본 요소 대기 (30초)
SESSION_EXTEND_INTERVAL_S = 1200   # 세션 연장 주기 (20분)
