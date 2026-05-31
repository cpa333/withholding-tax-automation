"""공통 로깅 유틸리티 — 자동화 모듈 전역에서 사용"""

import sys


def log(msg):
    try:
        print(msg, flush=True)
    except (AttributeError, TypeError, ValueError):
        pass
