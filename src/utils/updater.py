"""자동 업데이트 코어 (stdlib 전용, Qt 비의존).

공개 릴리스 저장소에 게시된 version.json 을 조회하여 최신 버전을 탐지하고,
설치파일(.exe)을 내려받아 검증한 뒤, '앱 종료 → 무인설치 → 재실행' 시퀀스를
시작하는 cmd 래퍼를 분리(detached) 실행한다.

설계 원칙:
- 네트워크/파일 함수는 **예외를 절대 전파하지 않는다** (실패 시 None/False).
  업데이트 서버 장애가 앱 실행을 막아서는 안 된다.
- 클라이언트에 어떤 비밀키도 두지 않는다 (공개 URL만 사용).
- Qt 의존 없음 → 콘솔에서 단위 테스트 가능.

버전 비교 기준은 src.version.__version__ (단일 소스).
사용자 환경설정(건너뛴 버전, 마지막 확인 시각)과 다운로드 파일은
config.APP_DATA_DIR (= 패키징 시 %LOCALAPPDATA%\\원천징수자동화-data) 하위에 저장 →
설치 폴더 덮어쓰기/제거에도 보존된다.
"""

import os
import re
import sys
import json
import hashlib
import shutil
import subprocess
import urllib.request
import urllib.parse
from datetime import datetime, timedelta

from src.version import __version__
from src.config import APP_DATA_DIR, APP_NAME


# ── 상수 ───────────────────────────────────────────────────────────────
# 소스 저장소(비공개)와 별개인 '공개' 릴리스 저장소.
RELEASES_OWNER = "cobaetoo"
RELEASES_REPO = "withholding-tax-releases"
# version.json 은 공개 저장소 루트에 두고 raw URL로 조회 (API 레이트리밋/구조 결합 회피).
VERSION_JSON_URL = (
    f"https://raw.githubusercontent.com/{RELEASES_OWNER}/{RELEASES_REPO}/main/version.json"
)
USER_AGENT = f"WithholdingTaxAutomation/{__version__}"
# installer.iss 의 AppMutex 와 반드시 일치해야 함 (Inno가 실행 중 인스턴스 감지).
APP_MUTEX_NAME = "WithholdingTaxAutomation_SingleInstance"

_DOWNLOAD_DIR = os.path.join(APP_DATA_DIR, "downloads")
_PREFS_PATH = os.path.join(APP_DATA_DIR, "update_prefs.json")
_CHECK_INTERVAL = timedelta(hours=20)  # 하루 1회 정도 자동 확인

# ── 보안 유틸리티 ────────────────────────────────────────────────────────
_CMD_META = re.compile(r'[&|><^%"!]')
_ALLOWED_DOMAINS = (
    "github.com",
    "objects.githubusercontent.com",
    "raw.githubusercontent.com",
)


def _validate_path_for_cmd(path: str, label: str = "") -> str:
    """cmd.exe 문자열에 안전한 경로인지 검증. 아니면 ValueError."""
    if not path:
        raise ValueError(f"{label or 'path'} is empty")
    if _CMD_META.search(path):
        raise ValueError(f"{label or 'path'} contains unsafe characters")
    return path


def current_version() -> str:
    return __version__


# ── 버전 비교 (semver, 관용) ────────────────────────────────────────────

def parse(v: str) -> tuple:
    """'v1.2.3', '1.2.3-beta+build' 등을 숫자 튜플로. pre-release는 정식보다 낮음."""
    v = (v or "").strip().lstrip("vV")
    # pre-release 분리: "1.2.3-alpha" → pre=-1, "1.2.3" → pre=0
    pre = 0
    if "-" in v:
        main_v, _ = v.split("-", 1)
        pre = -1
    else:
        main_v = v.split("+")[0]
    parts = (main_v.split(".") + ["0", "0", "0"])[:3]
    out = []
    for p in parts:
        try:
            out.append(int(p))
        except ValueError:
            out.append(0)
    out.append(pre)
    return tuple(out)


def is_newer(remote: str, local: str) -> bool:
    """remote 가 local 보다 '엄격히' 높을 때만 True (다운그레이드 방지)."""
    return parse(remote) > parse(local)


# ── version.json 조회 + 판정 ────────────────────────────────────────────

def fetch_version_info(timeout: int = 6):
    """공개 저장소의 version.json 조회. 실패 시 None (예외 비전파)."""
    try:
        req = urllib.request.Request(
            VERSION_JSON_URL,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
        info = json.loads(raw.decode("utf-8"))
        if not isinstance(info, dict) or "version" not in info:
            return None
        return info
    except Exception:
        return None


def decide(info: dict, local: str = None) -> dict:
    """version.json + 로컬 버전으로 업데이트 동작 판정.

    Returns:
        {"action": "none"|"optional"|"mandatory", "version", "url",
         "size", "sha256", "notes"}
    """
    local = local or __version__
    if not info:
        return {"action": "none"}

    remote = str(info.get("version", "")).strip()
    if not remote or not is_newer(remote, local):
        return {"action": "none", "version": remote}

    mandatory = bool(info.get("mandatory", False))
    min_sup = str(info.get("min_supported", "") or "").strip()
    if min_sup and is_newer(min_sup, local):
        # 로컬이 최소 지원 버전보다 낮음 → 강제 업데이트
        mandatory = True

    return {
        "action": "mandatory" if mandatory else "optional",
        "version": remote,
        "url": info.get("url", "") or "",
        "size": int(info.get("size", 0) or 0),
        "sha256": (info.get("sha256", "") or "").lower(),
        "notes": info.get("notes", "") or "",
    }


def check() -> dict:
    """version.json 조회 + 판정을 한 번에. 실패 시 {"action": "none"}."""
    return decide(fetch_version_info(), __version__)


# ── 다운로드 + 검증 ─────────────────────────────────────────────────────

class _Cancelled(Exception):
    pass


def _safe_remove(path):
    try:
        os.remove(path)
    except OSError:
        pass


def _sha256_file(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(262144), b""):
            h.update(chunk)
    return h.hexdigest()


def validate_installer(path: str, expected_size: int = 0,
                       sha256: str = "", _precomputed_sha: str = None) -> bool:
    """설치파일 무결성 검증: 크기·PE 매직(MZ)·sha256(필수)."""
    if not sha256:
        return False                    # sha256 없으면 검증 불가
    try:
        size = os.path.getsize(path)
    except OSError:
        return False
    if size < 1_000_000:            # 정상 설치파일은 ~200MB; 1MB 미만이면 손상/오류 본문
        return False
    if expected_size and size != expected_size:
        return False
    try:
        with open(path, "rb") as f:
            if f.read(2) != b"MZ":  # Windows PE 실행 파일 서명
                return False
    except OSError:
        return False
    actual = _precomputed_sha or _sha256_file(path)
    if actual.lower() != sha256.lower():
        return False
    return True


def download_installer(url: str, expected_size: int = 0, sha256: str = "",
                       progress_cb=None, cancel_cb=None):
    """설치파일을 다운로드 폴더로 스트리밍 후 검증. 성공 시 경로, 실패/취소 시 None.

    Args:
        progress_cb: callable(done_bytes, total_bytes) — 진행률 콜백.
        cancel_cb:   callable() -> bool — True 반환 시 취소.
    """
    if not url:
        return None
    # URL 도메인 허용 목록 검증 (GitHub 공식 도메인만 허용)
    try:
        host = urllib.parse.urlparse(url).hostname or ""
        if not any(host == d or host.endswith("." + d) for d in _ALLOWED_DOMAINS):
            return None
    except Exception:
        return None
    try:
        os.makedirs(_DOWNLOAD_DIR, exist_ok=True)
    except Exception:
        return None

    final = os.path.join(_DOWNLOAD_DIR, f"{APP_NAME}_설치.exe")
    part = final + ".part"
    _safe_remove(part)

    h = hashlib.sha256()
    done = 0
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        # 공개 release 에셋은 objects.githubusercontent.com 으로 302 → urllib 자동 추적, 무인증.
        with urllib.request.urlopen(req, timeout=30) as resp, open(part, "wb") as out:
            total = expected_size or int(resp.headers.get("Content-Length") or 0)
            while True:
                if cancel_cb and cancel_cb():
                    raise _Cancelled()
                chunk = resp.read(262144)
                if not chunk:
                    break
                out.write(chunk)
                h.update(chunk)
                done += len(chunk)
                if progress_cb:
                    progress_cb(done, total)
    except _Cancelled:
        _safe_remove(part)
        return None
    except Exception:
        _safe_remove(part)
        return None

    if not validate_installer(part, expected_size, sha256, _precomputed_sha=h.hexdigest()):
        _safe_remove(part)
        return None

    try:
        _safe_remove(final)
        os.replace(part, final)
    except Exception:
        _safe_remove(part)
        return None
    return final


def has_enough_disk(needed_bytes: int) -> bool:
    """다운로드+설치 압축해제에 필요한 여유 공간 확인. 확인 불가 시 True(진행)."""
    try:
        os.makedirs(APP_DATA_DIR, exist_ok=True)
        return shutil.disk_usage(APP_DATA_DIR).free >= needed_bytes
    except Exception:
        return True


# ── 적용 (앱 종료 → 무인설치 → 재실행) ──────────────────────────────────

def _install_log_path() -> str:
    logs = os.path.join(APP_DATA_DIR, "logs")
    try:
        os.makedirs(logs, exist_ok=True)
    except Exception:
        return ""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return os.path.join(logs, f"install_{ts}.log")


def build_relaunch_command(installer_path: str, exe_path: str,
                           log_path: str = "") -> list:
    """'부모 종료 대기 → 무인설치 → 새 exe 재실행' cmd 래퍼 인자 생성.

    ping -n 4 (~3초)로 호출 프로세스가 완전히 종료되어 exe/_internal 파일 잠금이
    풀릴 시간을 준 뒤 설치기를 무인 실행하고, 성공하면 같은 경로의 새 exe를 실행한다.
    """
    _validate_path_for_cmd(installer_path, "installer_path")
    _validate_path_for_cmd(exe_path, "exe_path")
    if log_path:
        _validate_path_for_cmd(log_path, "log_path")

    log_arg = f' /LOG="{log_path}"' if log_path else ""
    inner = (
        'ping 127.0.0.1 -n 4 >nul'
        f' & "{installer_path}" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART{log_arg}'
        f' && start "" "{exe_path}"'   # 설치 성공(종료코드 0)한 경우에만 재시작
    )
    return ["cmd", "/c", inner]


def spawn_installer_and_detach(installer_path: str, exe_path: str = None) -> bool:
    """설치기를 분리된 cmd로 실행. 성공 시 True. **호출 직후 앱을 종료해야 한다.**

    앱이 살아있는 동안에는 ONEDIR의 exe/_internal\\*.dll 이 잠겨 설치기가 덮어쓸 수
    없으므로, 이 함수 호출 후 즉시 QApplication.quit()/sys.exit 으로 종료한다.
    """
    if exe_path is None:
        exe_path = sys.executable
    cmd = build_relaunch_command(installer_path, exe_path, _install_log_path())

    flags = 0
    if sys.platform == "win32":
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    try:
        subprocess.Popen(
            cmd,
            creationflags=flags,
            close_fds=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except Exception:
        return False


# ── 사용자 환경설정 (건너뛴 버전 / 마지막 확인 시각) ─────────────────────
# 설치 폴더 밖(APP_DATA_DIR)에 저장 → 업데이트/제거에도 보존.

def _load_prefs() -> dict:
    try:
        with open(_PREFS_PATH, encoding="utf-8") as f:
            d = json.load(f)
            return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _save_prefs(d: dict) -> bool:
    try:
        os.makedirs(APP_DATA_DIR, exist_ok=True)
        with open(_PREFS_PATH, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


def get_skip_version() -> str:
    return _load_prefs().get("skip_version", "")


def set_skip_version(version: str) -> None:
    d = _load_prefs()
    d["skip_version"] = version
    _save_prefs(d)


def get_last_check() -> str:
    return _load_prefs().get("last_check", "")


def set_last_check(iso: str = None) -> None:
    d = _load_prefs()
    d["last_check"] = iso or datetime.now().isoformat(timespec="seconds")
    _save_prefs(d)


def should_check_today() -> bool:
    """마지막 확인 이후 _CHECK_INTERVAL 지났는지 (자동 확인 스로틀)."""
    last = get_last_check()
    if not last:
        return True
    try:
        return (datetime.now() - datetime.fromisoformat(last)) >= _CHECK_INTERVAL
    except Exception:
        return True


if __name__ == "__main__":
    # 콘솔 점검용: python -m src.utils.updater
    print(f"local __version__ = {__version__}")
    print(f"VERSION_JSON_URL  = {VERSION_JSON_URL}")
    print(f"APP_DATA_DIR      = {APP_DATA_DIR}")
    info = fetch_version_info()
    print(f"fetch_version_info() = {info}")
    print(f"decide() = {decide(info)}")
