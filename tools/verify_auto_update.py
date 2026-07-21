# -*- coding: utf-8 -*-
"""자동 업데이트 E2E 검증 드라이버 (개발자 전용, 2026-07-21 라이브 검증에 사용).

구버전이 설치된 PC에서 실행하면: 설치본 실행 → 시작 자동 확인(또는 이미 떠 있는
프롬프트) → '지금 업데이트' 자동 클릭 → 다운로드 → 무인 설치 → 신버전 자동
재실행까지 전 과정을 무인 관찰하고 단계별로 stdout 에 기록한다.

사용법 (릴리스 배포·전파 완료 후):
    python tools/verify_auto_update.py 1.1.2 1.1.3            # 구버전 실행부터
    python tools/verify_auto_update.py 1.1.2 1.1.3 --no-launch # 이미 실행 중이면

전제/주의:
  - 구버전이 %LOCALAPPDATA%\\원천징수자동화 에 설치되어 있어야 한다.
  - 자동 확인이 스로틀(4h)에 걸려 있으면 프롬프트가 안 뜬다 →
    %LOCALAPPDATA%\\원천징수자동화-data\\update_prefs.json 을 {} 로 비우고 실행하거나
    앱의 도움말>업데이트 확인을 이용한다. 판독은 같은 폴더 logs\\update.log.
  - 로그인 모달이 뜨면 사람이 1회 로그인해야 한다(최대 10분 대기).

★ 창 탐지는 win32 EnumWindows 를 쓴다 — pywinauto UIA 데스크톱 열거
  (Desktop().windows())는 Qt 모달(QMessageBox)을 누락하는 것이 실측 확인됨.
  조작만 UIAWrapper(UIAElementInfo(hwnd)) 로 HWND 직결한다.

종료 코드: 0=성공, 2=로그인 타임아웃, 3=프롬프트 미출현, 4=사이클 타임아웃.
"""
import ctypes
from ctypes import wintypes
import os
import subprocess
import sys
import time

from pywinauto.controls.uiawrapper import UIAWrapper
from pywinauto.uia_element_info import UIAElementInfo

user32 = ctypes.windll.user32

APP_NAME = "원천징수 자동화"
EXE = os.path.expandvars(r"%LOCALAPPDATA%\원천징수자동화\원천징수자동화.exe")
TITLE_LOGIN = f"{APP_NAME} 로그인"
TITLE_UPDATE = "업데이트"


def log(msg):
    print(f"[VERIFY] {msg}", flush=True)


def enum_windows():
    out = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, lparam):
        if user32.IsWindowVisible(hwnd):
            n = user32.GetWindowTextLengthW(hwnd)
            buf = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(hwnd, buf, n + 1)
            out.append((hwnd, buf.value))
        return True

    user32.EnumWindows(cb, 0)
    return out


def find_hwnd(title):
    for h, t in enum_windows():
        if t == title:
            return h
    return None


def wrap(hwnd):
    return UIAWrapper(UIAElementInfo(hwnd))


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) != 2:
        print(__doc__)
        return 1
    old_ver, new_ver = args
    title_old = f"{APP_NAME} v{old_ver}"
    title_new = f"{APP_NAME} v{new_ver}"

    if "--no-launch" not in sys.argv:
        log(f"launch {EXE}")
        subprocess.Popen([EXE], close_fds=True)

    # 1) (로그인 →) 업데이트 프롬프트 대기
    deadline = time.time() + 240
    prompt_hwnd = None
    seen_old = False
    while time.time() < deadline:
        if find_hwnd(TITLE_LOGIN):
            log("LOGIN_REQUIRED — 사람이 로그인해야 함 (최대 10분 대기)")
            login_deadline = time.time() + 600
            while time.time() < login_deadline and find_hwnd(TITLE_LOGIN):
                time.sleep(3)
            if find_hwnd(TITLE_LOGIN):
                log("FAIL login-timeout")
                return 2
            log("login done")
            deadline = time.time() + 120
        if not seen_old and find_hwnd(title_old):
            seen_old = True
            log(f"main window v{old_ver} visible")
        h = find_hwnd(TITLE_UPDATE)
        if h:
            try:
                if wrap(h).descendants(title="지금 업데이트", control_type="Button"):
                    prompt_hwnd = h
                    break
            except Exception:
                pass
        time.sleep(2)

    if not prompt_hwnd:
        log("FAIL no-prompt — 스로틀/skip_version/update.log 확인 (모듈 docstring 참조)")
        return 3

    dlg = wrap(prompt_hwnd)
    try:
        texts = [t.window_text() for t in dlg.descendants(control_type="Text")]
        log("prompt: " + " | ".join(x.replace("\n", " / ") for x in texts if x))
    except Exception:
        pass
    log("clicking 지금 업데이트")
    try:
        dlg.set_focus()
    except Exception:
        pass
    btn = dlg.descendants(title="지금 업데이트", control_type="Button")[0]
    try:
        btn.click_input()
    except Exception as e:
        log(f"click_input fail {e!r} — invoke 폴백")
        btn.invoke()

    # 2) 다운로드 → 앱 종료 → 무인 설치 → 신버전 재실행 (최대 12분)
    log("waiting full auto cycle (max 720s)")
    deadline = time.time() + 720
    old_gone = False
    last_note = 0
    while time.time() < deadline:
        wins = dict((t, h) for h, t in enum_windows())
        if title_new in wins:
            log(f"SUCCESS v{new_ver} relaunched — full hands-free cycle complete")
            return 0
        if not old_gone and title_old not in wins:
            old_gone = True
            log("old app closed — silent install phase")
        now = time.time()
        if now - last_note > 30:
            h = wins.get(TITLE_UPDATE)
            if h:
                try:
                    texts = [t.window_text() for t in wrap(h).descendants(control_type="Text")]
                    hint = next((x for x in texts if "다운로드" in x), None)
                    if hint:
                        log(f"progress: {hint}")
                except Exception:
                    pass
            last_note = now
        time.sleep(3)

    log("FAIL cycle-timeout — %LOCALAPPDATA%\\원천징수자동화-data\\logs\\update.log 와 install_*.log 확인")
    return 4


if __name__ == "__main__":
    sys.exit(main())
