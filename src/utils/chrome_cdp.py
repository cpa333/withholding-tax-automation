"""범용 Chrome CDP 실행 유틸리티 — 어떤 PC에서든 동작"""

import asyncio
import os
import subprocess
import json
import urllib.request
import glob


CDP_PORT = 9223
CDP_URL = f"http://localhost:{CDP_PORT}"


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
            capture_output=True, text=True, timeout=5,
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
        capture_output=True, text=True, timeout=10,
    )
    if not os.path.exists(junc):
        raise RuntimeError(f"Junction 생성 실패: {result.stderr}")

    return junc


def check_cdp_available():
    """CDP 포트가 활성인지 확인"""
    try:
        with urllib.request.urlopen(f"{CDP_URL}/json/version", timeout=2) as resp:
            return resp.status == 200
    except Exception:
        return False


def kill_chrome():
    """기존 Chrome 프로세스 종료"""
    subprocess.run(
        ["taskkill", "/F", "/IM", "chrome.exe", "/T"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def launch_chrome(url="https://www.wehago.com/", *, force=False):
    """Chrome을 CDP 디버깅 모드로 실행.

    Args:
        url: 시작 시 열 URL
        force: True면 이미 CDP가 활성이어도 재실행

    Returns:
        dict: {"success": bool, "chrome_path": str, "profile": str, "junction": str, ...}
    """
    result = {"success": False, "error": None}

    # 이미 CDP 활성이면 재사용
    if not force and check_cdp_available():
        result["success"] = True
        result["reused"] = True
        return result

    # Chrome 경로 탐지
    chrome_path = find_chrome()
    if not chrome_path:
        result["error"] = "Chrome 실행 파일을 찾을 수 없습니다"
        return result
    result["chrome_path"] = chrome_path

    # User Data 경로 탐지
    user_data = find_chrome_user_data()
    if not user_data:
        result["error"] = "Chrome User Data 디렉토리를 찾을 수 없습니다"
        return result

    # 프로필 탐지
    profile = find_chrome_profile(user_data)
    if not profile:
        profile = "Default"
    result["profile"] = profile

    # Junction 링크 생성
    junc = _create_junction(user_data)
    result["junction"] = junc

    # 기존 Chrome 종료
    kill_chrome()

    # Chrome 실행
    subprocess.Popen(
        [
            chrome_path,
            f"--remote-debugging-port={CDP_PORT}",
            f"--user-data-dir={junc}",
            f"--profile-directory={profile}",
            "--start-maximized",
            url,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # CDP 활성 대기
    for _ in range(20):
        import time
        time.sleep(1)
        if check_cdp_available():
            result["success"] = True
            return result

    result["error"] = "CDP 포트 응답 없음 (Chrome 실행 실패)"
    return result


async def launch_chrome_async(url="https://www.wehago.com/", *, force=False):
    """launch_chrome의 async 버전"""
    return launch_chrome(url, force=force)


async def connect_page(playwright):
    """CDP로 Chrome에 연결하고 첫 번째 페이지 반환"""
    browser = await playwright.chromium.connect_over_cdp(CDP_URL)
    context = browser.contexts[0]
    page = context.pages[0] if context.pages else await context.new_page()
    return browser, context, page


def list_tabs():
    """현재 열린 Chrome 탭 목록 반환"""
    try:
        with urllib.request.urlopen(f"{CDP_URL}/json", timeout=3) as resp:
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
