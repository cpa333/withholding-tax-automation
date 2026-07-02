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

# CLI(_emit_summary)가 stdout 으로 찍는 구조화 결과 마커. 이 라인은 log_message 가
# 아니라 result_summary 로 변환되어 로그 패널에 raw JSON 이 노출되지 않는다.
# src/automation/nps/nps_auto_cdp.py / nhis/nhis_edi_auto_cdp.py 의 _RESULT_MARKER 와 동일.
_RESULT_MARKER = "__WTAX_RESULT__"

# 병렬 실행 시 NHIS/NPS 가 같은 최상위 폴더에 저장하도록 두 CLI 에 전달할 저장 폴더명.
# → ~/Desktop/공단EDI_{YYYYMM}/{수임처}/ 안에 건강보험+국민연금 자료가 함께 들어감.
PARALLEL_SAVE_SITE = "공단EDI"


class ParallelCliRunner(QThread):
    """NPS+NHIS CLI 를 병렬 subprocess 로 실행·모니터링."""

    log_message = Signal(str)            # "[NPS] ..." / "[NHIS] ..." 라인
    finished_one = Signal(str, bool)     # (which, success)
    all_finished = Signal()
    result_summary = Signal(str, str)    # (which, json) — _emit_summary 마커 파싱 결과

    def __init__(self, parent=None):
        super().__init__(parent)
        self._procs = {}                 # "nps"/"nhis" -> Popen
        self._readers = {}               # "nps"/"nhis" -> Thread
        self._nps_port = 9223
        self._nhis_port = 9224

    def start(self, *, nps_port=9223, nhis_port=9224,
              firms=None, mgmts=None, year=None, month=None):
        """두 CLI 백그라운드 시작. firms=None → 전체 수임처(--auto 만).

        mgmts: firms 와 같은 순서의 사업장관리번호 리스트. 제공되면 CLI 가
        이름 대신 관리번호로 수임처를 선택(원래 동작). 비었으면 이름 fallback.
        """
        self._nps_port = nps_port
        self._nhis_port = nhis_port
        # 본 파일(src/ui/workers/) 기준 3단계 위 = repo root (src 패키지 부모).
        # 주의: 2단계는 src/ 까지라 python -m src... 가 src 를 못 찾음(ModuleNotFoundError).
        repo_root = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "..")
        )
        # src 패키지 해석 이중 보장: cwd(repo root) + PYTHONPATH(안전망)
        pypath = repo_root + os.pathsep + os.environ.get("PYTHONPATH", "")
        env_nps = {**os.environ, "WTAX_CDP_PORT": str(nps_port),
                   "PYTHONUTF8": "1", "PYTHONPATH": pypath}
        env_nhis = {**os.environ, "WTAX_CDP_PORT": str(nhis_port),
                    "PYTHONUTF8": "1", "PYTHONPATH": pypath}
        self._spawn("nps", "src.automation.nps.nps_auto_cdp", env_nps,
                    repo_root, firms, mgmts, year, month)
        self._spawn("nhis", "src.automation.nhis.nhis_edi_auto_cdp", env_nhis,
                    repo_root, firms, mgmts, year, month)
        super().start()  # QThread.run — 완료 대기

    def _spawn(self, which, module, env, cwd, firms, mgmts, year, month):
        # frozen(PyInstaller exe)에서는 python -m 이 불가 → 진입점(gui_main)의
        # --wtax-cli 디스패치로 CLI 모듈 실행. dev(python)은 기존 -m 방식 유지.
        if getattr(sys, "frozen", False):
            args = [sys.executable, "--wtax-cli", module, "--auto"]
        else:
            args = [sys.executable, "-u", "-m", module, "--auto"]
        if year is not None:
            args += ["--year", str(year)]
        if month is not None:
            args += ["--month", str(month)]
        if firms:
            args += ["--firms", ",".join(firms)]
        if mgmts:
            args += ["--mgmts", ",".join(str(m) for m in mgmts)]
        # 병렬: 두 CLI 를 같은 최상위 폴더로 묶어 수임처별로 건강보험+국민연금 자료를 함께 저장.
        args += ["--save-site", PARALLEL_SAVE_SITE]
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
                line = line.rstrip()
                # 구조화 결과 마커 라인은 result_summary 로 분리(로그 패널엔 미출력).
                if line.startswith(_RESULT_MARKER):
                    self.result_summary.emit(which, line[len(_RESULT_MARKER):].strip())
                    continue
                self.log_message.emit(f"{prefix} {line}")
        except Exception:
            pass

    def run(self):
        for which, proc in list(self._procs.items()):
            proc.wait()
            self.finished_one.emit(which, proc.returncode == 0)
        # _pump 스레드가 마지막 마커(result_summary) emit 을 끝내고 종료한 뒤에
        # all_finished 를 emit 하도록 join. 같은 GUI 이벤트 큐에 FIFO 로 적재되어
        # result_summary 가 항상 all_finished 핸들러보다 먼저 처리된다(순서 보장).
        for t in list(self._readers.values()):
            t.join(timeout=5.0)
        self.all_finished.emit()

    def stop(self):
        """두 subprocess + 자식 Chrome 트리 종료.

        강제 종료 전 짧은 grace 창을 둬서, 마무리 단계의 CLI가 스스로
        browser.close()로 영속 프로필(보안 확장 포함)을 flush 할 기회를 준다.
        단 Windows의 proc.terminate()/taskkill /F 는 비동기 강제종료라 완전한
        graceful 은 보장 못 함 — 신뢰 가능한 flush 는 자연완료 경로가 담당한다.
        """
        for which, proc in list(self._procs.items()):
            # grace 창: 자연 종료 중이면 스스로 flush 하고 끝나도록 잠시 대기.
            # _pump reader 스레드가 stdout 파이프를 계속 drain 하므로 wait 가
            # pipe-buffer 가득 참으로 교착되지 않는다(TimeoutExpired → except).
            try:
                proc.wait(timeout=2.0)
            except Exception:
                pass
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
        # 재사용/분리(detached) Chrome 은 CLI 자식 트리에 없어 taskkill /T 가 못 죽임.
        # CDP 포트를 LISTEN 중인 Chrome 브라우저 프로세스를 포트로 찾아 확실히 종료.
        # 정지=완전 중단일 때만 kill — 자연 완료(_on_parallel_finished) 시엔 죽이지 않아
        # 다음 실행이 세션을 재사용(재로그인 생략)할 수 있게 한다.
        from src.utils.chrome_cdp import kill_chrome_by_port
        kill_chrome_by_port(self._nps_port)
        kill_chrome_by_port(self._nhis_port)
        self.requestInterruption()

    def is_running(self):
        return any(p.poll() is None for p in self._procs.values())
