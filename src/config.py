"""공통 설정 — DB 경로, 포털 URL, 프로젝트 상수.

사용자 데이터(SQLite DB, 발급 결과파일)는 설치 폴더가 아니라
%LOCALAPPDATA%\\원천징수자동화-data 에 저장한다. 이렇게 하면 자동 업데이트
(설치 폴더 덮어쓰기)나 프로그램 제거 시에도 데이터가 보존된다.

개발 모드(소스 실행)에서는 기존과 동일하게 작업 디렉터리(repo) 하위를 사용한다.
"""

import os
import sys
import shutil

APP_NAME = "원천징수자동화"

# ── 사용자 데이터 베이스 경로 ──────────────────────────────────────────
#  - 패키징(frozen) 실행: %LOCALAPPDATA%\원천징수자동화-data
#       설치 폴더({localappdata}\원천징수자동화) 밖이므로 업데이트/제거에도 보존됨
#  - 개발 실행: 현재 작업 디렉터리 (repo) — 기존 동작 유지
if getattr(sys, "frozen", False):
    _LOCAL = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    APP_DATA_DIR = os.path.join(_LOCAL, f"{APP_NAME}-data")
else:
    APP_DATA_DIR = os.getcwd()

# 데이터베이스
DB_DIR = os.path.join(APP_DATA_DIR, "data")
DB_PATH = os.path.join(DB_DIR, "withholding_tax.db")

# 결과 저장 경로
RESULTS_DIR = os.path.join(APP_DATA_DIR, "results")

# 포털 URL
PORTAL_URLS = {
    "wehago": "https://www.wehago.com/",
    "nhis_edi": "https://edi.nhis.or.kr/",
    "nps_edi": "https://edi.nps.or.kr/",
    "hometax": "https://www.hometax.go.kr/",
}

# 인증 세션 파일
AUTH_SESSION_PATH = os.path.join(APP_DATA_DIR, "auth_session.json")

# WEHAGO
WEHAGO_URL = "https://www.wehago.com/"
WEHAGO_TAXAGENT_URL = "https://www.wehago.com/tedge/#/taxagent"

# NHIS EDI
NHIS_EDI_URL = "https://edi.nhis.or.kr/"
NHIS_EDI_MAIN = "https://edi.nhis.or.kr/homeapp/wep/m/retrieveMain.xx"


def migrate_legacy_data():
    """구버전 데이터(설치 폴더 내 data/, results/)를 새 위치로 1회 이전.

    1.0.0 이하 버전은 데이터를 설치 폴더({app}\\data, {app}\\results)에 저장했다.
    새 위치(%LOCALAPPDATA%\\원천징수자동화-data)로 한 번 옮긴다.

    - frozen(패키징) 실행에서만 동작 (개발 모드는 경로가 동일하므로 불필요).
    - 새 위치에 이미 데이터가 있으면 건너뛴다 (중복 이전 방지).
    - 어떤 예외도 앱 실행을 막지 않는다.

    Returns:
        bool: 실제로 이전이 일어났으면 True.
    """
    if not getattr(sys, "frozen", False):
        return False
    try:
        legacy_base = os.getcwd()  # gui_main이 os.chdir(설치 폴더) 수행한 상태
        if os.path.normcase(os.path.abspath(legacy_base)) == \
           os.path.normcase(os.path.abspath(APP_DATA_DIR)):
            return False  # 동일 경로면 이전 불필요

        moved = False
        os.makedirs(APP_DATA_DIR, exist_ok=True)
        for sub in ("data", "results"):
            old = os.path.join(legacy_base, sub)
            new = os.path.join(APP_DATA_DIR, sub)
            if os.path.isdir(old) and not os.path.exists(new):
                shutil.move(old, new)
                moved = True
        return moved
    except Exception:
        return False
