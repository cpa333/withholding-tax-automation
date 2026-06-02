"""Supabase Auth 인증 코어 모듈 (stdlib 전용, Qt 비의존).

Supabase GoTrue REST API를 사용하여 로그인/세션 갱신/검증을 수행한다.
src.utils.updater와 동일한 설계 원칙:
- 네트워크/파일 함수는 예외를 절대 전파하지 않는다 (실패 시 None/False).
- Qt 의존 없음 → 콘솔에서 단위 테스트 가능.
- stdlib만 사용 (urllib, base64, json).

세션 데이터는 config.AUTH_SESSION_PATH (auth_session.json)에 저장된다.
"""

import base64
import json
import os
from datetime import datetime, timedelta, timezone

from src.config import AUTH_SESSION_PATH
from src.ui.resources.auth_config import (
    AUTH_GRACE_PERIOD_DAYS,
    BETA_EXPIRES,
    SUPABASE_ANON_KEY,
    SUPABASE_URL,
)


# ── 내부 유틸리티 ─────────────────────────────────────────────────────

def _decode_jwt_payload(token: str) -> dict:
    """JWT payload segment를 base64url 디코딩하여 dict로 반환.

    PyJWT 불필요 — payload의 exp/sub/email만 확인하면 충분.
    """
    try:
        parts = token.split(".")
        if len(parts) < 2:
            return {}
        payload = parts[1]
        # base64url 패딩 보정
        padding = 4 - len(payload) % 4
        if padding != 4:
            payload += "=" * padding
        decoded = base64.urlsafe_b64decode(payload)
        return json.loads(decoded)
    except Exception:
        return {}


def _supabase_request(method: str, path: str, body: dict = None,
                      access_token: str = None, timeout: int = 10) -> dict | None:
    """Supabase GoTrue REST API 호출 헬퍼.

    updater.fetch_version_info()와 동일한 urllib 패턴.
    실패 시 None 반환 (예외 비전파).
    """
    import urllib.request
    import urllib.parse

    try:
        url = f"{SUPABASE_URL}/auth/v1{path}"
        headers = {
            "apikey": SUPABASE_ANON_KEY,
            "Content-Type": "application/json",
        }
        if access_token:
            headers["Authorization"] = f"Bearer {access_token}"

        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")

        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
        if not raw:
            return {}
        return json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as e:
        # HTTP 에러 본문에서 오류 메시지 추출 시도
        try:
            err_body = json.loads(e.read().decode("utf-8"))
            return {"_error": True, "status": e.code,
                    "message": err_body.get("error_description", "")
                    or err_body.get("msg", "")
                    or str(e)}
        except Exception:
            return {"_error": True, "status": e.code, "message": str(e)}
    except Exception:
        return None


# ── 세션 파일 I/O ──────────────────────────────────────────────────────

def _load_session() -> dict | None:
    """저장된 세션 데이터 로드. updater._load_prefs() 패턴."""
    try:
        with open(AUTH_SESSION_PATH, encoding="utf-8") as f:
            d = json.load(f)
            return d if isinstance(d, dict) else None
    except Exception:
        return None


def _save_session(session: dict) -> bool:
    """세션 데이터를 auth_session.json에 저장. updater._save_prefs() 패턴."""
    try:
        os.makedirs(os.path.dirname(AUTH_SESSION_PATH), exist_ok=True)
        with open(AUTH_SESSION_PATH, "w", encoding="utf-8") as f:
            json.dump(session, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


def clear_session() -> None:
    """세션 파일 삭제 + 서버에 로그아웃 요청."""
    # 서버에 로그아웃 (refresh_token 무효화)
    session = _load_session()
    if session and session.get("refresh_token"):
        _supabase_request(
            "POST", "/logout",
            access_token=session.get("access_token"),
        )
    # 로컬 파일 삭제
    try:
        if os.path.exists(AUTH_SESSION_PATH):
            os.remove(AUTH_SESSION_PATH)
    except Exception:
        pass


# ── 공개 API ────────────────────────────────────────────────────────────

def login(email: str, password: str) -> dict | None:
    """이메일/비밀번호로 Supabase Auth 로그인.

    성공 시 세션 dict (access_token, refresh_token, user 등)를 반환하고
    파일에 저장한다. 실패 시 에러 정보 dict 또는 None 반환.
    """
    result = _supabase_request(
        "POST", "/token?grant_type=password",
        body={"email": email, "password": password},
    )
    if result is None:
        return {"_error": True, "message": "서버에 연결할 수 없습니다.\n인터넷 연결을 확인해 주세요."}
    if result.get("_error"):
        msg = result.get("message", "로그인에 실패했습니다.")
        # Supabase 에러 메시지 한국어 변환
        if "Invalid login credentials" in msg:
            msg = "이메일 또는 비밀번호가 올바르지 않습니다."
        elif "Email not confirmed" in msg:
            msg = "이메일 인증이 완료되지 않았습니다."
        elif "too many requests" in msg.lower():
            msg = "로그인 시도 횟수가 초과되었습니다.\n잠시 후 다시 시도해 주세요."
        return {"_error": True, "message": msg}

    # 세션에 타임스탬프 추가 후 저장
    result["last_verified_at"] = datetime.now(timezone.utc).isoformat()
    _save_session(result)
    return result


def refresh_session() -> dict | None:
    """저장된 refresh_token으로 새 access_token 발급.

    성공 시 세션 dict 갱신 + 저장. 실패 시 None.
    """
    session = _load_session()
    if not session or not session.get("refresh_token"):
        return None

    result = _supabase_request(
        "POST", "/token?grant_type=refresh_token",
        body={"refresh_token": session["refresh_token"]},
    )
    if result is None or result.get("_error"):
        return None

    result["last_verified_at"] = datetime.now(timezone.utc).isoformat()
    _save_session(result)
    return result


def validate_session() -> bool:
    """현재 세션이 유효한지 검증.

    1. 로컬 세션 파일 존재 확인
    2. access_token 만료 확인 (JWT exp 클레임)
    3. 만료 시 refresh_session() 시도
    4. 서버에 GET /user로 계정 활성 상태 확인
    5. 성공 시 last_verified_at 갱신

    Returns:
        bool: 세션이 유효하면 True.
    """
    session = _load_session()
    if not session or not session.get("access_token"):
        return False

    token = session["access_token"]

    # JWT exp 확인
    payload = _decode_jwt_payload(token)
    exp = payload.get("exp", 0)
    now = datetime.now(timezone.utc).timestamp()

    if exp and now >= exp:
        # 만료됨 → refresh 시도
        refreshed = refresh_session()
        if refreshed is None:
            return False
        token = refreshed["access_token"]
        session = refreshed

    # 서버에 계정 활성 상태 확인
    user = _supabase_request("GET", "/user", access_token=token)
    if user is None or user.get("_error"):
        # 네트워크 오류(None)는 서버 장애일 수 있으므로 유예 기간에 의존
        if user is None:
            return True  # 서버 통신 불가 → 유예 기간 판단은 호출자에게 위임
        return False  # 명시적 에러(401 등) → 세션 무효

    # 활성 계정 확인 통과 → last_verified_at 갱신
    session["last_verified_at"] = datetime.now(timezone.utc).isoformat()
    _save_session(session)
    return True


def get_current_user() -> dict | None:
    """현재 로그인된 사용자 정보 반환 (또는 None)."""
    session = _load_session()
    if not session:
        return None
    return {
        "email": (session.get("user") or {}).get("email", ""),
        "id": (session.get("user") or {}).get("id", ""),
    }


def is_within_grace_period() -> bool:
    """마지막 서버 인증 성공 후 유예 기간 내인지 확인."""
    session = _load_session()
    if not session:
        return False
    last = session.get("last_verified_at", "")
    if not last:
        return False
    try:
        last_dt = datetime.fromisoformat(last)
        if last_dt.tzinfo is None:
            last_dt = last_dt.replace(tzinfo=timezone.utc)
        elapsed = datetime.now(timezone.utc) - last_dt
        return elapsed < timedelta(days=AUTH_GRACE_PERIOD_DAYS)
    except Exception:
        return False


def is_beta_expired() -> bool:
    """베타 사용 기간이 만료되었는지 확인."""
    try:
        expires = datetime.strptime(BETA_EXPIRES, "%Y-%m-%d").date()
        return datetime.now().date() > expires
    except Exception:
        return False


# ── 콘솔 테스트 ────────────────────────────────────────────────────────

if __name__ == "__main__":
    # python -m src.utils.auth
    print(f"BETA_EXPIRES       = {BETA_EXPIRES}")
    print(f"is_beta_expired()  = {is_beta_expired()}")
    print(f"AUTH_SESSION_PATH  = {AUTH_SESSION_PATH}")
    session = _load_session()
    print(f"_load_session()    = {('present' if session else 'absent')}")
    if session:
        print(f"  email            = {(session.get('user') or {}).get('email', '?')}")
        print(f"  last_verified_at = {session.get('last_verified_at', '?')}")
        print(f"  is_within_grace  = {is_within_grace_period()}")
        print(f"  validate_session = {validate_session()}")
