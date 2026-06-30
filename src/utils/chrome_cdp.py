"""범용 Chrome CDP 실행 유틸리티 — 어떤 PC에서든 동작"""

import asyncio
import os
import shutil
import subprocess
import json
import time
import urllib.request
import glob

from src.config import APP_DATA_DIR


# WTAX_NO_DELAY 선례: env 미설정 → 9223(직렬, 현행). WTAX_CDP_PORT=9224 등으로 병렬 분리.
CDP_PORT = int(os.environ.get("WTAX_CDP_PORT", "9223"))
# 127.0.0.1 명시 — Windows에서 localhost가 IPv6(::1)로 먼저 풀리면 Chrome의
# IPv4(127.0.0.1) 디버그 서버와 연결이 간헐 실패(연결 거부)한다.
CDP_URL = f"http://127.0.0.1:{CDP_PORT}"

# 병렬(포트 분리)에서 자기 Chrome PID만 정밀 종료하기 위한 레지스트리: port → pid.
# _attempt_launch 가 Popen.pid 를 등록하고 kill_chrome(port=...)이 조회한다.
_launched_pids: dict[int, int] = {}


def find_chrome():
    """Chrome 실행 파일 경로 자동 탐지"""
    candidates = []

    # 환경변수 기반 경로
    for env_var in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
        base = os.environ.get(env_var, "")
        if base:
            candidates.append(
                os.path.join(base, "Google", "Chrome", "Application", "chrome.exe")
            )

    # 레지스트리에서 탐색
    try:
        result = subprocess.run(
            ["reg", "query",
             r"HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe",
             "/ve"],
            capture_output=True, text=True, encoding="oem", errors="ignore",
            timeout=5,
        )
        for line in result.stdout.splitlines():
            line = line.strip()
            if line.endswith("chrome.exe"):
                # 레지스트리 값에서 경로 추출
                path = line.split("REG_SZ")[-1].strip().strip('"')
                if path and os.path.exists(path):
                    return path
    except Exception:
        pass

    # 일반적인 설치 경로 추가
    candidates.extend([
        os.path.expanduser(r"~\AppData\Local\Google\Chrome\Application\chrome.exe"),
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ])

    for path in candidates:
        if os.path.exists(path):
            return path

    return None


def find_chrome_user_data():
    """Chrome User Data 디렉토리 자동 탐지"""
    local_app = os.environ.get("LOCALAPPDATA", "")
    if local_app:
        path = os.path.join(local_app, "Google", "Chrome", "User Data")
        if os.path.isdir(path):
            return path
    return None


def find_chrome_profile(user_data_dir):
    """사용 중인 Chrome 프로필 자동 탐지 (Default, Profile 1, Profile 2, ...)"""
    if not user_data_dir or not os.path.isdir(user_data_dir):
        return None

    # Local State에서 프로필 목록 읽기
    local_state_path = os.path.join(user_data_dir, "Local State")
    if os.path.exists(local_state_path):
        try:
            with open(local_state_path, "r", encoding="utf-8") as f:
                state = json.load(f)

            profiles = state.get("profile", {}).get("info_cache", {})
            # 마지막 사용 프로필 우선
            last_used = state.get("profile", {}).get("last_used", "")
            if last_used and last_used in profiles:
                return last_used

            # 프로필 중 활성 프로필 탐색
            for name in profiles:
                # Guest Profile, System Profile 제외
                if "guest" in name.lower() or "system" in name.lower():
                    continue
                return name
        except Exception:
            pass

    # 폴백: 디렉토리 스캔
    for name in ["Default", "Profile 1", "Profile 2", "Profile 3"]:
        if os.path.isdir(os.path.join(user_data_dir, name)):
            return name

    return None


def _create_junction(user_data_dir):
    """Chrome User Data에 대한 junction 링크 생성"""
    junc = os.path.join(os.environ.get("TEMP", "/tmp"), "chrome-cdp-link")

    # 기존 junction 제거
    if os.path.exists(junc):
        try:
            os.rmdir(junc)
        except OSError:
            subprocess.run(
                ["cmd", "/c", "rmdir", "/S", "/Q", junc],
                capture_output=True, timeout=5,
            )

    # junction 생성
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", junc, user_data_dir],
        capture_output=True, text=True, encoding="oem", errors="ignore",
        timeout=10,
    )
    if not os.path.exists(junc):
        raise RuntimeError(f"Junction 생성 실패: {result.stderr}")

    return junc


def check_cdp_available(*, url: str = CDP_URL):
    """CDP 포트가 활성인지 확인 (url 미지정 시 모듈 기본 포트)."""
    try:
        with urllib.request.urlopen(f"{url}/json/version", timeout=3) as resp:
            return resp.status == 200
    except Exception:
        return False


def kill_chrome(*, pid: int | None = None, port: int | None = None):
    """Chrome 종료. 인자 없음=전체 kill(콜드부팅 폴백, 현행 동작 보존).
    pid 지정=해당 PID 트리만(taskkill /PID /T). port 지정=_launched_pids[port]로 pid 해석.
    병렬에서는 pid/port로 자기 Chrome만 종료 → 타 포트 Chrome 보호.
    """
    if pid is None and port is not None:
        pid = _launched_pids.get(port)
    if pid is not None:
        # PID 재사용 방어: 해당 PID가 여전히 chrome.exe인지 확인 후 kill.
        if not _process_running(pid):
            if port is not None:
                _launched_pids.pop(port, None)
            return
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        if port is not None:
            _launched_pids.pop(port, None)
        return
    # pid 없음 — 직렬(port=9223 + env 미설정)만 전체 kill(현행 회귀 보존).
    # 병렬(WTAX_CDP_PORT 설정 또는 port!=9223)은 자기 Chrome을 띄운 적 없으므로
    # 전체 kill 금지(다른 병렬 Chrome 보호) → 스킵. 동시 launch 레이스 회피.
    is_parallel = (
        os.environ.get("WTAX_CDP_PORT") is not None
        or (port is not None and port != 9223)
    )
    if is_parallel:
        return
    subprocess.run(
        ["taskkill", "/F", "/IM", "chrome.exe", "/T"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def kill_chrome_by_port(port: int) -> list[int]:
    """CDP 포트를 LISTEN 중인 Chrome 브라우저 프로세스를 포트로 찾아 종료.

    CLI 가 재사용(reuse)했거나 분리(detached) 실행한 Chrome 은 CLI 자식 프로세스
    트리에 없어서 taskkill /PID <cli> /T 로는 죽지 않는다(병렬 stop 시 Chrome 이
    남는 원인). netstat -ano 에서 해당 포트의 LISTENING 소켓 PID(= Chrome 브라우저
    프로세스)를 찾아 taskkill /PID /T /F 한다. kill_chrome(port=) 와 달리
    _launched_pids 레지스트리(자식 CLI 메모리에 있어 GUI 가 못 봄)에 의존하지 않아
    GUI 측(ParallelCliRunner.stop)에서도 동작한다. 다른 포트의 Chrome 은 건드리지 않는다.

    Returns: taskkill 을 시도한 PID 목록(중복 제거).
    """
    try:
        r = subprocess.run(
            ["netstat", "-ano"], capture_output=True, text=True,
            encoding="oem", errors="ignore", timeout=8,
        )
    except Exception:
        return []
    pids: list[int] = []
    suffix = f":{port}"
    for line in r.stdout.splitlines():
        parts = line.split()
        # netstat -ano 행: [Proto, LocalAddr, ForeignAddr, State, PID]
        if len(parts) >= 5 and parts[1].endswith(suffix) and "LISTENING" in line:
            pid = parts[-1]
            if pid.isdigit():
                pids.append(int(pid))
    killed: list[int] = []
    for pid in dict.fromkeys(pids):  # 중복 제거(순서 보존)
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        killed.append(pid)
    return killed


def _chrome_process_running() -> bool:
    """chrome.exe 프로세스가 하나라도 실행 중인지 확인 (tasklist 기반, psutil 무의존)."""
    try:
        r = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq chrome.exe", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, encoding="oem", errors="ignore",
            timeout=5,
        )
        out = r.stdout.strip()
        if not out:
            return False
        # chrome이 없으면 "정보: ... 없습니다" / "INFO: No tasks" 만 출력됨.
        return "chrome.exe" in out.lower()
    except Exception:
        return False


def _process_running(pid: int) -> bool:
    """특정 PID가 chrome.exe로 실행 중인지 확인 (PID 재사용 방어).
    _chrome_process_running(이름 전체 검사)의 PID 정밀 버전.
    """
    try:
        r = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, encoding="oem", errors="ignore",
            timeout=5,
        )
        out = r.stdout.strip()
        return bool(out) and str(pid) in out and "chrome.exe" in out.lower()
    except Exception:
        return False


def _attempt_launch(chrome_path, junc, profile, url, *, port=CDP_PORT, kill_wait=3) -> dict:
    """Chrome 1회 실행 시도: kill → 잠금 해제 대기 → Popen → CDP 준비 대기.

    Returns:
        {"success": bool, "pid": int|None}: CDP 활성화 여부와 Popen.pid.
        port 지정 시 자기 포트 Chrome만 kill(kill_chrome(port=port)) → 병렬 안전.
    """
    kill_chrome(port=port)
    time.sleep(kill_wait)  # 프로필 SingletonLock 해제 대기

    proc = subprocess.Popen(
        [
            chrome_path,
            f"--remote-debugging-port={port}",
            f"--user-data-dir={junc}",
            f"--profile-directory={profile}",
            "--start-maximized",
            # webdriver=true 원천 차단 — a2f9c11이 --test-type(탐지신호라 제거 맞음)과
            # 함께 묶어 삭제한 플래그 복원. NHIS EDI 보안프로그램이 navigator.webdriver
            # 를 감지해 페이지를 무한 리로드(로그인 루프)하는 것을 막는다. blink 레벨에서
            # 꺼지므로 첫 페이지 로드부터 적용(stealth add_init_script 타이밍 갭 해소).
            "--disable-blink-features=AutomationControlled",
            # 병렬(창 2개)에서 뒤에 가려지는 창은 Chrome이 렌더·타이머를
            # throttle 해 Nexacro 화면 구성이 지연된다(탭 전환·로그인 감지 실패
            # 원인). 가려진/백그라운드 창도 전경처럼 풀스피드로 유지.
            "--disable-backgrounding-occluded-windows",
            "--disable-renderer-backgrounding",
            "--disable-background-timer-throttling",
            url,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    pid = proc.pid
    if port is not None:
        _launched_pids[port] = pid

    cdp_url = f"http://127.0.0.1:{port}"
    # CDP 활성 대기 — 0.5초 간격, 최대 약 30초
    for _ in range(60):
        time.sleep(0.5)
        if check_cdp_available(url=cdp_url):
            return {"success": True, "pid": pid}
    return {"success": False, "pid": pid}


def _prepare_user_data_dir(port: int) -> str:
    """병렬 모드 전용: 포트별 영속 user-data-dir (보안프로그램 재설치 생략 목적).

    APP_DATA_DIR/chrome-profiles/cdp-{port} — 매 실행 동일 경로 재사용.
    한국 EDI 포털(NPS/NHIS)이 "보안프로그램 설치됨"을 Chrome 확장(프로필 단위
    저장) 유무로 판단한다. 예전의 %TEMP% 빈 임시 프로필로는 매번 재설치 메뉴가
    떴기 때문에, 영속 프로필에 한 번 설치하면 이후 실행부터 재설치가 안 뜬다
    (직렬 junction 경로와 동일 원리). 두 포트(9223/9224)는 각각 별개 디렉토리를
    쓰므로 SingletonLock 충돌 회피도 그대로 유지된다.

    WTAX_FRESH_PROFILE=1 (1/true/yes/on) 시 디버그용으로 프로필을 완전 초기화
    (구 %TEMP% 빈-dir 동작과 같은 효과). Chrome이 프로필을 잡고 있으면 rmtree가
    실패할 수 있으므로 stop 후 적용한다.
    잔존 SingletonLock 파일이 있으면 정리(확장/세션 데이터는 보존).
    """
    fresh = (
        os.environ.get("WTAX_FRESH_PROFILE", "").strip().lower()
        in ("1", "true", "yes", "on")
    )
    base = os.path.join(APP_DATA_DIR, "chrome-profiles")
    path = os.path.join(base, f"cdp-{port}")
    if fresh:
        shutil.rmtree(path, ignore_errors=True)
    os.makedirs(path, exist_ok=True)
    for lockname in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
        try:
            os.remove(os.path.join(path, lockname))
        except OSError:
            pass
    return path


def launch_chrome(url="https://www.wehago.com/", *, port=CDP_PORT, force=False):
    """Chrome을 CDP 디버깅 모드로 실행.

    Args:
        url: 시작 시 열 URL
        port: CDP 디버그 포트(기본 CDP_PORT=env). 병렬 시 포트별 분리.
        force: True면 이미 CDP가 활성이어도 재실행

    Returns:
        dict: {success, chrome_path?, profile?, junction?, pid?, reused?,
               separate_user_data?, error?}
    """
    result = {"success": False, "error": None}
    cdp_url = f"http://127.0.0.1:{port}"

    # 이미 CDP 활성이면 재사용 (재사용은 우리가 띄운 Chrome이 아닐 수 있어 pid는 레지스트리 조회)
    if not force and check_cdp_available(url=cdp_url):
        result["success"] = True
        result["reused"] = True
        result["pid"] = _launched_pids.get(port)
        return result

    # Chrome 경로 탐지
    chrome_path = find_chrome()
    if not chrome_path:
        result["error"] = "Chrome 실행 파일을 찾을 수 없습니다"
        return result
    result["chrome_path"] = chrome_path

    # 병렬 신호: WTAX_CDP_PORT 명시적 설정(배치)이거나 port!=기본이거나 별도 env.
    # 배치가 WTAX_CDP_PORT=9223 이라도 명시 설정이면 빈 dir(일반 Chrome과 Lock 충돌 회피).
    # 직렬(env 완전 미설정 + port=9223)만 현행 junction 경로 100% 보존.
    use_separate = (
        os.environ.get("WTAX_CDP_PORT") is not None
        or port != 9223
        or os.environ.get("WTAX_SEPARATE_USER_DATA", "").strip().lower()
            in ("1", "true", "yes", "on")
    )
    if use_separate:
        junc = _prepare_user_data_dir(port)
        profile = "Default"
        result["separate_user_data"] = True
    else:
        user_data = find_chrome_user_data()
        if not user_data:
            result["error"] = "Chrome User Data 디렉토리를 찾을 수 없습니다"
            return result
        profile = find_chrome_profile(user_data)
        if not profile:
            profile = "Default"
        junc = _create_junction(user_data)
    result["profile"] = profile
    result["junction"] = junc

    # 1차 실행 시도 (port 전달 → 자기 포트만 kill)
    attempt = _attempt_launch(chrome_path, junc, profile, url, port=port, kill_wait=3)
    if attempt["success"]:
        result["success"] = True
        result["pid"] = attempt["pid"]
        return result

    # 위임(delegation) 감지: chrome.exe가 살아있는데 CDP 포트가 없으면 재시도.
    # (병렬 빈 dir에서는 위임 자체가 발생하지 않음 — 직렬 경로 위주)
    if _chrome_process_running():
        attempt2 = _attempt_launch(chrome_path, junc, profile, url, port=port, kill_wait=4)
        if attempt2["success"]:
            result["success"] = True
            result["pid"] = attempt2["pid"]
            return result
        result["error"] = (
            "CDP 포트 응답 없음 — 다른 Chrome 창이 열려 디버그 포트를 차지하고 있을 수 있습니다. "
            "모든 Chrome 창을 닫은 후 다시 시도하세요."
        )
    else:
        result["error"] = (
            "CDP 포트 응답 없음 (Chrome 실행 실패) — Chrome 경로/프로필을 확인하세요."
        )
    return result


async def launch_chrome_async(url="https://www.wehago.com/", *, port=CDP_PORT, force=False):
    """launch_chrome의 async 버전"""
    return launch_chrome(url, port=port, force=force)


async def connect_page(playwright, *, url: str = CDP_URL):
    """CDP로 Chrome에 연결하고 WEHAGO 탭 우선 반환 (url 미지정 시 기본 포트)"""
    from src.utils.stealth import stealth_all_pages, register_auto_stealth

    browser = await playwright.chromium.connect_over_cdp(url)
    context = browser.contexts[0]

    await stealth_all_pages(context)
    register_auto_stealth(context)

    # WEHAGO가 열려있는 탭 우선 선택
    for p in context.pages:
        try:
            if "wehago.com" in p.url:
                return browser, context, p
        except Exception:
            continue

    # 없으면 첫 번째 탭 또는 새 탭
    page = context.pages[0] if context.pages else await context.new_page()
    return browser, context, page


def list_tabs(*, url: str = CDP_URL):
    """현재 열린 Chrome 탭 목록 반환 (url 미지정 시 기본 포트)"""
    try:
        with urllib.request.urlopen(f"{url}/json", timeout=3) as resp:
            tabs = json.loads(resp.read())
            return [
                {"title": t.get("title", ""), "url": t.get("url", ""), "type": t.get("type", "")}
                for t in tabs
                if t.get("type") == "page"
            ]
    except Exception:
        return []


if __name__ == "__main__":
    print("=== Chrome CDP 환경 정보 ===")
    print(f"Chrome 경로: {find_chrome()}")
    print(f"User Data: {find_chrome_user_data()}")
    user_data = find_chrome_user_data()
    if user_data:
        print(f"프로필: {find_chrome_profile(user_data)}")
    print(f"CDP 활성: {check_cdp_available()}")
    print(f"현재 탭: {list_tabs()}")
