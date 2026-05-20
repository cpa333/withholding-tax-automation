"""subprocess로 Chrome을 CDP 디버깅 모드로 실행 (9222 포트)

주의: playwright.chromium.launch()로 실행하면 download.save_as()가 0바이트를 반환함.
반드시 subprocess.Popen으로 실행 후 connect_over_cdp로 연결할 것.
"""
import subprocess
import os
import time
import sys


def find_chrome():
    """Chrome 실행 파일 경로 찾기"""
    paths = [
        os.path.join(os.environ.get("PROGRAMFILES", ""), "Google", "Chrome", "Application", "chrome.exe"),
        os.path.join(os.environ.get("PROGRAMFILES(X86)", ""), "Google", "Chrome", "Application", "chrome.exe"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Google", "Chrome", "Application", "chrome.exe"),
    ]
    for p in paths:
        if os.path.exists(p):
            return p
    return None


def main():
    chrome_path = find_chrome()
    if not chrome_path:
        print("Chrome 브라우저를 찾을 수 없습니다.", flush=True)
        sys.exit(1)

    user_data_dir = os.path.join(os.environ.get("TEMP", ""), "chrome-cdp-session")
    target_url = sys.argv[1] if len(sys.argv) > 1 else "https://www.wehago.com/#/main"

    print(f"Chrome: {chrome_path}", flush=True)
    print(f"User Data: {user_data_dir}", flush=True)
    print(f"URL: {target_url}", flush=True)

    subprocess.Popen([
        chrome_path,
        "--remote-debugging-port=9222",
        f"--user-data-dir={user_data_dir}",
        "--start-maximized",
        target_url,
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    print("CDP 포트 대기...", flush=True)
    for i in range(30):
        time.sleep(1)
        try:
            import urllib.request
            with urllib.request.urlopen("http://localhost:9222/json/version", timeout=2) as resp:
                if resp.status == 200:
                    print(f"READY: CDP 포트 9222 활성 (Chrome 연결 가능)", flush=True)
                    return
        except Exception:
            pass

    print("CDP 포트 대기 실패 (30초 초과)", flush=True)
    sys.exit(1)


if __name__ == "__main__":
    main()
