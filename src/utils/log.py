"""공통 로깅 유틸리티 — 자동화 모듈 전역에서 사용

log() 호출 시 mutually exclusive 라우팅:
1. _log_callback이 설정된 경우(GUI 직렬 자동화) → callback만 호출(print 스킵)
2. _log_callback이 None인 경우(CLI / 병렬 자식 subprocess) → print()로 stdout 출력

GUI(AutomationRunner)에서 set_log_callback()으로 콜백을 등록하면
자동화 모듈 내부의 log() 출력이 실시간으로 GUI 로그 패널에 표시된다.

★ callback 설정 시 print를 스킵하는 이유: AutomationRunner의 QThread가
sys.stdout을 LogCapture(async_bridge.py)로 교체하므로, print 또한 같은
log_message 시그널로 수렴하여 동일 메시지가 GUI에 2회 표시되기 때문이다.
대신 dev 터미널 가시성을 위해 sys.__stdout__(LogCapture가 가로채지 않는 원본
stdout 참조)으로만 미러링한다. 비-log stdout(stray print, traceback.print_exc)은
LogCapture가 계속 캡처한다.
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
    # callback이 설정된 환경(GUI 직렬 자동화)에서는 callback을 유일 전달 경로로 쓴다.
    # 이 환경에선 AsyncWorker.run()이 sys.stdout을 LogCapture로 교체(async_bridge.py)해
    # print()도 다시 log_message.emit()으로 수렴하므로, callback과 print를 동시에 쓰면
    # 같은 메시지가 GUI에 2회 표시된다 → callback 설정 시 print는 스킵.
    # 단 dev 터미널 가시성을 위해 sys.__stdout__(LogCapture가 가로채지 않는 원본)으로 미러.
    if _log_callback:
        try:
            _log_callback(msg)
        except Exception:
            pass
        try:
            print(msg, flush=True, file=sys.__stdout__)
        except Exception:
            pass
        return
    # callback이 없는 환경(CLI / 병렬 자식 subprocess) — print만으로 stdout 출력.
    # 병렬은 부모 ParallelCliRunner._pump가 자식 stdout 파이프를 읽어 [NPS]/[NHIS] 로그로 방출.
    try:
        print(msg, flush=True)
    except (AttributeError, TypeError, ValueError):
        pass
