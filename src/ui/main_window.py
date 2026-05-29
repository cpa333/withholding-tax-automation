"""메인 윈도우 — 전체 UI 레이아웃 관리"""

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout,
    QSplitter, QPushButton, QHBoxLayout,
    QCheckBox, QSpinBox, QLabel, QMessageBox,
)
from PySide6.QtCore import Qt, QTimer

from src.ui.widgets.log_panel import LogPanel
from src.ui.widgets.phase_sidebar import PhaseSidebar
from src.ui.widgets.company_table import CompanyTable
from src.ui.widgets.step_detail import StepDetail
from src.ui.workers.automation_runner import AutomationRunner


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("원천징수 자동화")
        self.setMinimumSize(1100, 700)
        self.resize(1280, 800)

        self.runner = AutomationRunner(self)
        self.runner.log_message.connect(self._on_log)
        self.runner.error_occurred.connect(self._on_error)
        self.runner.phase_changed.connect(self._on_phase_changed)
        self.runner.batch_progress.connect(self._on_batch_progress)
        self.runner.job_changed.connect(self._on_job_changed)
        self.runner.finished_ok.connect(self._on_runner_finished)

        self._selected_phase = 1
        self._selected_job_id = 0

        self._setup_ui()
        self._load_phases()

        # 수임처 관리 버튼 연결
        self.company_table.refresh_requested.connect(self._on_refresh_clients)
        self.company_table.delete_all_requested.connect(self._on_delete_all_clients)
        self.company_table.single_run_requested.connect(self._on_single_run)

        # 시작 시 DB에서 수임처 목록 로드
        self._load_client_list()

        # Phase 1이 기본 선택 → 시작 버튼 비활성화
        self.start_btn.setEnabled(False)
        self.company_table.set_client_mode(True)

        # 진행 상황 폴링 타이머 (러너가 실행 중일 때)
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(2000)
        self._poll_timer.timeout.connect(self._poll_step_detail)

    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)

        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # 상단 툴바
        toolbar = self._create_toolbar()
        main_layout.addWidget(toolbar)

        # 중간: 사이드바 | 수임처 테이블 + 세부 단계
        h_splitter = QSplitter(Qt.Horizontal)

        self.sidebar = PhaseSidebar()
        self.sidebar.setFixedWidth(220)
        self.sidebar.phase_selected.connect(self._on_phase_selected)

        # 오른쪽: 수임처 테이블 | 세부 단계
        right_splitter = QSplitter(Qt.Vertical)

        self.company_table = CompanyTable()
        self.company_table.job_selected.connect(self._on_job_selected)

        self.step_detail = StepDetail()

        right_splitter.addWidget(self.company_table)
        right_splitter.addWidget(self.step_detail)
        right_splitter.setStretchFactor(0, 2)
        right_splitter.setStretchFactor(1, 1)

        h_splitter.addWidget(self.sidebar)
        h_splitter.addWidget(right_splitter)
        h_splitter.setStretchFactor(0, 0)
        h_splitter.setStretchFactor(1, 1)

        main_layout.addWidget(h_splitter, stretch=1)

        # 하단: 로그 패널
        self.log_panel = LogPanel()
        self.log_panel.setMaximumHeight(200)
        main_layout.addWidget(self.log_panel)

        # 상태바
        self.statusBar().showMessage("준비")

    def _create_toolbar(self) -> QWidget:
        toolbar = QWidget()
        toolbar.setStyleSheet(
            "QWidget { background-color: #fafafa; border-bottom: 1px solid #ddd; }"
        )
        layout = QHBoxLayout(toolbar)
        layout.setContentsMargins(8, 4, 8, 4)

        # 연도
        layout.addWidget(QLabel("연도"))
        self.year_spin = QSpinBox()
        self.year_spin.setRange(2024, 2030)
        self.year_spin.setValue(2026)
        self.year_spin.setFixedWidth(70)
        layout.addWidget(self.year_spin)

        # 월
        layout.addWidget(QLabel("월"))
        self.month_spin = QSpinBox()
        self.month_spin.setRange(1, 12)
        self.month_spin.setValue(5)
        self.month_spin.setFixedWidth(50)
        layout.addWidget(self.month_spin)

        # dry-run
        self.dry_run_check = QCheckBox("dry-run")
        self.dry_run_check.setChecked(True)
        layout.addWidget(self.dry_run_check)

        layout.addStretch()

        # 제어 버튼
        self.start_btn = QPushButton("시작")
        self.start_btn.setStyleSheet(
            "QPushButton { background-color: #4caf50; color: white; "
            "padding: 5px 15px; border-radius: 3px; font-weight: bold; }"
        )
        self.start_btn.clicked.connect(self._on_start)
        layout.addWidget(self.start_btn)

        self.pause_btn = QPushButton("일시정지")
        self.pause_btn.setEnabled(False)
        self.pause_btn.clicked.connect(self._on_pause)
        layout.addWidget(self.pause_btn)

        self.stop_btn = QPushButton("정지")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._on_stop)
        layout.addWidget(self.stop_btn)

        return toolbar

    def _load_phases(self):
        """페이즈 목록 로드 (워크플로우 모듈 import로 레지스트리 등록)"""
        import src.workflows.wehago_list_clients  # noqa: F401
        import src.workflows.nhis_edi             # noqa: F401
        import src.workflows.nps_edi              # noqa: F401
        import src.workflows.wehago_swsa          # noqa: F401
        import src.workflows.wehago_swta          # noqa: F401
        import src.workflows.wehago_swer          # noqa: F401
        import src.workflows.hometax              # noqa: F401

        from src.workflows.registry import get_all_phases
        phases = get_all_phases()
        self.sidebar.set_phases(phases)

    # ── Slot ──

    def _on_log(self, message: str):
        self.log_panel.append_log(message)

    def _on_error(self, message: str):
        self.log_panel.append_log(message)
        self.statusBar().showMessage(message[:120])

    def _on_phase_changed(self, phase_id: int, status: str):
        self.sidebar.update_phase_status(phase_id, status)
        self.statusBar().showMessage(f"Phase {phase_id}: {status}")

        # 페이즈 완료/실패 시 버튼 상태 복원
        if status in ("completed", "failed"):
            if self._selected_phase == 1:
                self.start_btn.setEnabled(False)
                # Phase 1이어도 버튼 재활성화 (브라우저 종료 후 재시작 가능)
                self.company_table.set_buttons_enabled(True)
            else:
                self.start_btn.setEnabled(True)
            self.pause_btn.setEnabled(False)
            self.stop_btn.setEnabled(False)
            self._poll_timer.stop()
            self.company_table.set_buttons_enabled(True)
            if self._selected_phase >= 2:
                self.company_table.set_single_run_mode(True)

        if phase_id == 1 and status == "completed":
            self._load_client_list()

    def _on_batch_progress(self, progress: dict):
        phase_id = progress.get("phase_id", 0)
        jobs = progress.get("jobs", [])
        failed = progress.get("failed", [])
        if not isinstance(failed, list):
            failed = []

        # 페이즈 상태 업데이트
        completed = sum(1 for j in jobs if j.get("status") == "completed")
        total = len(jobs)
        self.sidebar.update_phase_status(phase_id, "running", completed, total)

        # 수임처 테이블 업데이트 (선택된 페이즈면)
        if phase_id == self._selected_phase:
            self.company_table.update_jobs(jobs, failed)

    def _on_job_changed(self, job_id, name, status, step, error):
        pass  # _poll_step_detail에서 처리

    def _on_phase_selected(self, phase_id: int):
        self._selected_phase = phase_id
        if phase_id == 1:
            self._load_client_list()
            self.start_btn.setEnabled(False)
            self.company_table.set_client_mode(True)
            self.company_table.set_single_run_mode(False)
        else:
            self.start_btn.setEnabled(True)
            self.company_table.set_client_mode(False)
            self._load_client_list_for_phase(phase_id)
            self.company_table.set_single_run_mode(True)

    def _load_client_list(self):
        """DB에서 수임처 목록을 조회하여 테이블에 표시"""
        try:
            import os
            from src.batch.db import BatchDB, ClientRepository

            db_path = os.path.join(os.getcwd(), "data", "withholding_tax.db")
            if not os.path.exists(db_path):
                self.company_table.update_clients([])
                return

            db = BatchDB(db_path)
            db.connect()
            try:
                client_repo = ClientRepository(db)
                clients = client_repo.list_all()
                client_dicts = [
                    {
                        "name": c.name.replace("[테스트] ", ""),
                        "business_number": c.business_number,
                        "portal": c.portal,
                        "enabled": c.enabled,
                    }
                    for c in clients
                    if c.name != "__전체수임처조회__"
                    and c.portal == "wehago"
                ]
                self.company_table.update_clients(client_dicts)
            finally:
                db.close()
        except Exception:
            self.company_table.update_clients([])

    def _load_client_list_for_phase(self, phase_id: int):
        """Phase 2+ 선택 시 수임처 목록을 클라이언트 모드로 표시"""
        from src.workflows.registry import get_phase_info
        info = get_phase_info(phase_id)
        if not info:
            return
        portal = info["portal"]
        try:
            import os
            from src.batch.db import BatchDB, ClientRepository

            db_path = os.path.join(os.getcwd(), "data", "withholding_tax.db")
            if not os.path.exists(db_path):
                self.company_table.update_clients([])
                return

            db = BatchDB(db_path)
            db.connect()
            try:
                client_repo = ClientRepository(db)
                clients = client_repo.list_all()

                # 대상 포털 클라이언트 우선, 없으면 WEHAGO 클라이언트 사용
                portal_clients = [
                    c for c in clients
                    if c.name != "__전체수임처조회__" and c.portal == portal
                ]
                wehago_clients = [
                    c for c in clients
                    if c.name != "__전체수임처조회__" and c.portal == "wehago"
                ]
                source = portal_clients if portal_clients else wehago_clients

                client_dicts = [
                    {
                        "name": c.name.replace("[테스트] ", ""),
                        "business_number": c.business_number,
                        "portal": c.portal,
                        "enabled": c.enabled,
                    }
                    for c in source
                ]
                self.company_table.update_clients(client_dicts)
            finally:
                db.close()
        except Exception:
            self.company_table.update_clients([])

    def _on_job_selected(self, job_id: int):
        """수임처 테이블에서 행 클릭 → 세부 단계 표시"""
        self._selected_job_id = job_id
        self._poll_step_detail()

    def _on_runner_finished(self):
        if self._selected_phase == 1:
            self.start_btn.setEnabled(False)
        else:
            self.start_btn.setEnabled(True)
        self.pause_btn.setEnabled(False)
        self.stop_btn.setEnabled(False)
        self._poll_timer.stop()
        self.company_table.set_buttons_enabled(True)
        if self._selected_phase >= 2:
            self.company_table.set_single_run_mode(True)

    def _poll_step_detail(self):
        """선택된 Job의 세부 단계를 DB에서 조회하여 업데이트"""
        if not self._selected_job_id:
            return

        try:
            import os
            from src.batch.db import BatchDB, StepRepository

            db_path = os.path.join(os.getcwd(), "data", "withholding_tax.db")
            if not os.path.exists(db_path):
                return

            db = BatchDB(db_path)
            db.connect()
            try:
                step_repo = StepRepository(db)
                steps = step_repo.list_by_job(self._selected_job_id)

                # 클라이언트명 찾기
                client_name = ""
                from src.batch.db import JobRepository
                job_repo = JobRepository(db)
                job = job_repo.get(self._selected_job_id)
                if job:
                    client_name = job.client_name

                step_dicts = [
                    {"step_name": s.step_name, "status": s.status}
                    for s in steps
                ]
                self.step_detail.set_steps(client_name, step_dicts)
            finally:
                db.close()
        except Exception:
            pass

    # ── 제어 ──

    def _on_start(self):
        if not self._selected_phase:
            self.statusBar().showMessage("페이즈를 먼저 선택하세요")
            return

        # Phase 1은 "새로 가져오기" 버튼으로만 실행
        if self._selected_phase == 1:
            self.statusBar().showMessage("수임처 리스트는 '새로 가져오기' 버튼을 사용하세요")
            return

        self.start_btn.setEnabled(False)
        self.pause_btn.setEnabled(True)
        self.stop_btn.setEnabled(True)

        self.runner.start_phase(
            self._selected_phase,
            dry_run=self.dry_run_check.isChecked(),
        )
        self._poll_timer.start()

    def _on_pause(self):
        if self.runner.is_paused:
            self.runner.request_resume()
            self.pause_btn.setText("일시정지")
        else:
            self.runner.request_pause()
            self.pause_btn.setText("재개")

    def _on_stop(self):
        self.runner.request_stop()
        self.runner.cleanup_session()
        self.start_btn.setEnabled(True)
        self.pause_btn.setEnabled(False)
        self.pause_btn.setText("일시정지")
        self.stop_btn.setEnabled(False)
        self._poll_timer.stop()
        self.statusBar().showMessage("세션 종료됨. 다시 시작하려면 '시작'을 눌러주세요.")

    def closeEvent(self, event):
        self._poll_timer.stop()
        self.runner.request_stop()
        self.runner.wait(3000)
        event.accept()

    # ── 수임처 관리 ──

    def _on_single_run(self, client_name: str, business_number: str):
        """단건 실행: 선택된 수임처 1개에 대해서만 자동화 실행"""
        if not self._selected_phase or self._selected_phase == 1:
            return

        from src.batch.models import biz_to_mgmt_no
        management_number = biz_to_mgmt_no(business_number)

        self.start_btn.setEnabled(False)
        self.pause_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.company_table.set_buttons_enabled(False)
        self.company_table.set_single_run_mode(False)

        self.runner.start_single_client(
            self._selected_phase, client_name, management_number,
        )
        self._poll_timer.start()

    def _on_refresh_clients(self):
        """WEHAGO에서 수임처 새로 가져오기"""
        self.company_table.set_buttons_enabled(False)
        self.runner.start_refresh_clients()

    def _on_delete_all_clients(self):
        """DB에서 수임처 모두 삭제"""
        reply = QMessageBox.question(
            self, "수임처 삭제",
            "등록된 수임처를 모두 삭제하시겠습니까?\n(다른 페이즈의 배치 데이터도 함께 삭제됩니다)",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        import os, sqlite3
        db_path = os.path.join(os.getcwd(), "data", "withholding_tax.db")
        if not os.path.exists(db_path):
            self.company_table.update_clients([])
            return

        conn = sqlite3.connect(db_path)
        try:
            conn.execute("DELETE FROM steps")
            conn.execute("DELETE FROM jobs")
            conn.execute("DELETE FROM batches")
            conn.execute("DELETE FROM clients")
            conn.commit()
        finally:
            conn.close()

        self.company_table.update_clients([])
        self.sidebar.update_phase_status(1, "pending")
        self.statusBar().showMessage("수임처 모두 삭제됨")
