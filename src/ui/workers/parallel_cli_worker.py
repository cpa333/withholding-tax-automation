"""GUI 병렬 자동화용 subprocess 워커 (QThread).

두 CLI(NPS 9223 / NHIS 9224)를 WTAX_CDP_PORT env로 백그라운드 실행하고,
stdout 을 폴링해 [NPS]/[NHIS] 접두사 로그로 방출한다.
정지는 proc.pid 를 taskkill /T (CLI→Chrome 트리 종료) — kill_chrome(port=) 은
GUI 프로세스의 _launched_pids 가 비어있어(자식 CLI 메모리) 안 통하므로 우회.
"""
import os
import sys
import subprocess
import threading

from PySide6.QtCore import QThread, Signal


class ParallelCliRunner(QThread):
    """NPS+NHIS CLI 를 병렬 subprocess 로 실행·모니터링."""

    log_message = Signal(str)            # "[NPS] ..." / "[NHIS] ..." 라인
    finished_one = Signal(str, bool)     # (which, success)
    all_finished = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._procs = {}                 # "nps"/"nhis" -> Popen
        self._readers = {}               # "nps"/"nhis" -> Thread
        self._nps_port = 9223
        self._nhis_port = 9224

    def start(self, *, nps_port=9223, nhis_port=9224,
              firms=None, year=None, month=None):
        """두 CLI 백그라운드 시작. firms=None → 전체 수임처(--auto 만)."""
        self._nps_port = nps_port
        self._nhis_port = nhis_port
        repo_root = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..")
        )
        env_nps = {**os.environ, "WTAX_CDP_PORT": str(nps_port), "PYTHONUTF8": "1"}
        env_nhis = {**os.environ, "WTAX_CDP_PORT": str(nhis_port), "PYTHONUTF8": "1"}
        self._spawn("nps", "src.automation.nps.nps_auto_cdp", env_nps,
                    repo_root, firms, year, month)
        self._spawn("nhis", "src.automation.nhis.nhis_edi_auto_cdp", env_nhis,
                    repo_root, firms, None, None)
        super().start()  # QThread.run — 완료 대기

    def _spawn(self, which, module, env, cwd, firms, year, month):
        args = [sys.executable, "-u", "-m", module, "--auto"]
        if year is not None:
            args += ["--year", str(year)]
        if month is not None:
            args += ["--month", str(month)]
        if firms:
            args += ["--firms", ",".join(firms)]
        kwargs = dict(
            args=args, env=env, cwd=cwd,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL, text=True, encoding="utf-8",
        )
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        self._procs[which] = subprocess.Popen(**kwargs)
        t = threading.Thread(target=self._pump, args=(which,), daemon=True)
        t.start()
        self._readers[which] = t

    def _pump(self, which):
        prefix = "[NPS]" if which == "nps" else "[NHIS]"
        proc = self._procs.get(which)
        if not proc or not proc.stdout:
            return
        try:
            for line in proc.stdout:
                self.log_message.emit(f"{prefix} {line.rstrip()}")
        except Exception:
            pass

    def run(self):
        for which, proc in list(self._procs.items()):
            proc.wait()
            self.finished_one.emit(which, proc.returncode == 0)
        self.all_finished.emit()

    def stop(self):
        """두 subprocess + 자식 Chrome 트리 종료."""
        for which, proc in list(self._procs.items()):
            try:
                proc.terminate()
            except Exception:
                pass
            # CLI→Chrome 부모-자식 트리 종료 (kill_chrome port= GUI 한계 회피).
            if sys.platform == "win32" and proc.poll() is None:
                try:
                    subprocess.run(
                        ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    )
                except Exception:
                    pass
        self.requestInterruption()

    def is_running(self):
        return any(p.poll() is None for p in self._procs.values())
