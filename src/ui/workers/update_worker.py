"""업데이트 전용 백그라운드 워커 (QThread).

버전 확인(version.json 조회)과 설치파일 다운로드를 Qt UI 스레드와 분리해 수행한다.
자동화용 AutomationRunner(Playwright 전용, sys.stdout 가로채기)와 **분리**하여
업데이트 작업이 자동화 상태나 로그 캡처에 영향을 주지 않도록 한다.

src.utils.updater(stdlib, 예외 비전파)를 호출만 하며, 결과를 Qt Signal로 방출한다.
"""

import threading

from PySide6.QtCore import QThread, Signal

from src.utils import updater


class UpdateWorker(QThread):
    """체크/다운로드 두 모드를 갖는 단발성 워커.

    Signals:
        check_done(dict)            - updater.check() 결과 dict ({"action": ...})
        download_progress(int, int) - (받은 바이트, 전체 바이트)
        download_done(str)          - 검증 완료된 설치파일 경로 ("" = 실패/취소)
        failed(str)                 - 예기치 못한 오류 메시지
    """

    check_done = Signal(dict)
    download_progress = Signal(int, int)
    download_done = Signal(str)
    failed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._mode = "check"
        self._url = ""
        self._size = 0
        self._sha256 = ""
        self._cancel = threading.Event()

    # ── 외부 호출 (메인 스레드) ──

    def start_check(self):
        """버전 확인 시작."""
        self._mode = "check"
        self._cancel.clear()
        self.start()

    def start_download(self, url: str, size: int = 0, sha256: str = ""):
        """설치파일 다운로드 시작."""
        self._mode = "download"
        self._url = url
        self._size = size
        self._sha256 = sha256
        self._cancel.clear()
        self.start()

    def cancel(self):
        """다운로드 취소 요청 (다음 청크 경계에서 중단)."""
        self._cancel.set()

    # ── 스레드 본문 ──

    def run(self):
        try:
            if self._mode == "check":
                result = updater.check()
                self.check_done.emit(result or {"action": "none"})
            else:
                path = updater.download_installer(
                    self._url,
                    expected_size=self._size,
                    sha256=self._sha256,
                    progress_cb=lambda done, total: self.download_progress.emit(done, total),
                    cancel_cb=lambda: self._cancel.is_set(),
                )
                self.download_done.emit(path or "")
        except Exception as e:  # updater가 이미 삼키지만 방어적으로
            self.failed.emit(str(e))
