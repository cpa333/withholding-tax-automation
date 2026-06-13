"""공통 로깅 유틸리티 — 자동화 모듈 전역에서 사용

log() 호출 시:
1. print()로 stdout 출력 (CLI 모드)
2. _log_callback이 설정되어 있으면 콜백 호출 (GUI 모드)

GUI(AutomationRunner)에서 set_log_callback()으로 콜백을 등록하면
자동화 모듈 내부의 log() 출력이 실시간으로 GUI 로그 패널에 표시됨.
"""

import sys

# 전역 로그 콜백 — GUI에서 set_log_callback()으로 설정
_log_callback = None


def set_log_callback(cb):
    """GUI 등 외부에서 로그 메시지를 수신할 콜백 설정

    Args:
        cb: callable(str) — 로그 메시지를 수신하는 콜백. None이면 해제.
    """
    global _log_callback
    _log_callback = cb


def log(msg):
    try:
        print(msg, flush=True)
    except (AttributeError, TypeError, ValueError):
        pass
    if _log_callback:
        try:
            _log_callback(msg)
        except Exception:
            pass
