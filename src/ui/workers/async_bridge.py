"""QThread + asyncio 브릿지 — Playwright와 PySide6 이벤트루프 연결

핵심: Playwright는 asyncio 기반, PySide6는 Qt 이벤트루프.
QThread 내부에서 별도 asyncio 이벤트루프를 실행하여 분리.

로그 캡처: sys.stdout을 LogCapture로 교체하여
기존 log() 함수의 print() 출력을 Qt Signal로 방출.
"""

import asyncio
import io
import sys
import threading
import queue
from typing import Optional

from PySide6.QtCore import QThread, Signal, QMutex, QMutexLocker


class LogCapture(io.TextIOBase):
    """sys.stdout 대체 — print() 출력을 Qt Signal로 방출.

    기존 자동화 코드의 log() → print() 체인을 그대로 두고
    출력만 가로채서 GUI로 전달.
    """

    def __init__(self, original_stdout, log_signal):
        super().__init__()
        self._original = original_stdout
        self._log_signal = log_signal

    def write(self, text):
        if text and text.strip():
            self._log_signal.emit(text.rstrip())
        if self._original is not None:
            self._original.write(text)
        return len(text) if text else 0

    def flush(self):
        if self._original is not None:
            self._original.flush()

    @property
    def encoding(self):
        return self._original.encoding if hasattr(self._original, 'encoding') else 'utf-8'


class AsyncWorker(QThread):
    """백그라운드 스레드에서 asyncio 이벤트루프를 실행하는 워커.

    Signal:
        log_message(str)     - 로그 출력
        phase_changed(int, str)  - (phase_id, status)
        job_changed(int, str, str, str, str)  - (job_id, client_name, status, current_step, error)
        step_changed(int, str, str)  - (job_id, step_name, status)
        batch_progress(dict) - 진행 요약
        finished_ok()        - 정상 완료
        error_occurred(str)  - 치명적 에러
    """

    log_message = Signal(str)
    phase_changed = Signal(int, str)
    job_changed = Signal(int, str, str, str, str)
    step_changed = Signal(int, str, str)
    batch_progress = Signal(dict)
    finished_ok = Signal()
    error_occurred = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._pause_event.set()  # 초기엔 일시정지 아님
        self._command_queue: queue.SimpleQueue = queue.SimpleQueue()
        self._log_capture: Optional[LogCapture] = None
        self._original_stdout = None
        self._dead = False  # 복구 불가능한 상태인지

    def run(self):
        """QThread.run — 백그라운드 스레드 진입점

        예외 발생 시 워커가 죽지 않고 재시작 가능한 상태로 유지.
        새 명령이 들어오면 start()로 다시 실행 가능.
        """
        self._dead = False
        self._original_stdout = sys.stdout
        self._log_capture = LogCapture(self._original_stdout, self.log_message)

        sys.stdout = self._log_capture

        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        try:
            self._loop.run_until_complete(self._async_main())
        except Exception as e:
            # 치명적 에러: 워커는 죽지만, UI에서 재시작 가능하도록 상태 표시
            self.error_occurred.emit(f"워커 오류: {e}")
            self._dead = True
        finally:
            if self._original_stdout:
                sys.stdout = self._original_stdout
            self._loop.close()
            self.finished_ok.emit()

    async def _async_main(self):
        """비동기 메인 — 명령 대기 루프"""
        self.log_message.emit("워커 시작됨")

        while not self._stop_event.is_set():
            # 일시정지 확인
            if not self._pause_event.is_set():
                await asyncio.sleep(0.5)
                continue

            # 명령 큐 확인
            try:
                cmd = self._command_queue.get_nowait()
            except queue.Empty:
                await asyncio.sleep(0.1)
                continue

            if cmd.get("type") == "stop":
                break
            elif cmd.get("type") == "run_phase":
                await self._handle_run_phase(cmd)

        self.log_message.emit("워커 종료됨")

    async def _handle_run_phase(self, cmd: dict):
        """run_phase 명령 처리 (Phase B에서 구현)"""
        phase_id = cmd.get("phase_id", 0)
        self.log_message.emit(f"Phase {phase_id} 실행 요청 (구현 예정)")

    # ── 외부에서 호출 (메인 스레드에서) ──

    def _ensure_running(self):
        """워커가 멈춰있으면 재시작. QThread는 start()로 재사용 가능.

        기존 큐에 남은 stop 명령 등 잔여 명령을 모두 비운 뒤 시작.
        """
        self._stop_event.clear()
        self._pause_event.set()
        # 큐에 남은 잔여 명령 제거
        while not self._command_queue.empty():
            try:
                self._command_queue.get_nowait()
            except Exception:
                break
        if not self.isRunning():
            self.start()

    def start_phase(self, phase_id: int, **kwargs):
        """페이즈 실행 명령 전송"""
        self._ensure_running()
        self._command_queue.put({"type": "run_phase", "phase_id": phase_id, **kwargs})

    def start_refresh_clients(self):
        """수임처 새로 가져오기 명령 전송"""
        self._ensure_running()
        self._command_queue.put({"type": "refresh_clients"})

    def request_stop(self):
        """정지 요청"""
        self._stop_event.set()
        self._command_queue.put({"type": "stop"})

    def request_pause(self):
        """일시정지"""
        self._pause_event.clear()

    def request_resume(self):
        """재개"""
        self._pause_event.set()

    @property
    def is_paused(self):
        return not self._pause_event.is_set()
