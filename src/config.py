"""공통 설정 — DB 경로, 포털 URL, 프로젝트 상수"""

import os

# 데이터베이스
DB_DIR = os.path.join(os.getcwd(), "data")
DB_PATH = os.path.join(DB_DIR, "withholding_tax.db")

# 포털 URL
PORTAL_URLS = {
    "wehago": "https://www.wehago.com/",
    "nhis_edi": "https://edi.nhis.or.kr/",
    "nps_edi": "https://edi.nps.or.kr/",
    "hometax": "https://www.hometax.go.kr/",
}

# WEHAGO
WEHAGO_URL = "https://www.wehago.com/"
WEHAGO_TAXAGENT_URL = "https://www.wehago.com/tedge/#/taxagent"

# NHIS EDI
NHIS_EDI_URL = "https://edi.nhis.or.kr/"
NHIS_EDI_MAIN = "https://edi.nhis.or.kr/homeapp/wep/m/retrieveMain.xx"

# 결과 저장 경로
RESULTS_DIR = os.path.join(os.getcwd(), "results")
