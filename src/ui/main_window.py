"""메인 윈도우 — 전체 UI 레이아웃 관리"""

import sys
from datetime import datetime

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout,
    QSplitter, QPushButton, QHBoxLayout,
    QCheckBox, QSpinBox, QLabel, QLineEdit, QMessageBox,
    QProgressDialog, QApplication,
)
from PySide6.QtCore import Qt, QTimer

from src.version import __version__
from src.config import DB_PATH
from src.ui.widgets.log_panel import LogPanel
from src.ui.widgets.phase_sidebar import PhaseSidebar
from src.ui.widgets.company_table import CompanyTable
from src.ui.widgets.step_detail import StepDetail
from src.ui.workers.automation_runner import AutomationRunner
from src.ui.workers.auth_worker import AuthWorker
from src.ui.workers.update_worker import UpdateWorker
from src.ui.resources.auth_config import AUTH_REFRESH_INTERVAL_SECS
from src.utils import updater
from src.utils import auth


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"원천징수 자동화 v{__version__}")
        self.setMinimumSize(1100, 700)
        self.resize(1280, 800)

        self.runner = AutomationRunner(self)
        self.runner.log_message.connect(self._on_log)
        self.runner.error_occurred.connect(self._on_error)
        self.runner.phase_changed.connect(self._on_phase_changed)
        self.runner.batch_progress.connect(self._on_batch_progress)
        self.runner.job_changed.connect(self._on_job_changed)
        self.runner.finished_ok.connect(self._on_runner_finished)

        # 병렬 자동화(NPS+NHIS subprocess) — 단일 runner 와 독립, 회귀 0
        from src.ui.workers.parallel_cli_worker import ParallelCliRunner
        self.parallel_runner = ParallelCliRunner(self)
        self.parallel_runner.log_message.connect(self._on_log)
        self.parallel_runner.finished_one.connect(self._on_parallel_finished_one)
        self.parallel_runner.all_finished.connect(self._on_parallel_finished)

        self._selected_phase = 1
        self._selected_job_id = 0

        # 자동 업데이트 상태
        self._automation_active = False
        self._update_in_progress = False
        self._update_worker = None
        self._download_worker = None
        self._progress_dialog = None
        self._download_canceled = False

        self._setup_ui()
        self._load_phases()

        # 수임처 관리 버튼 연결
        self.company_table.refresh_requested.connect(self._on_refresh_clients)
        self.company_table.delete_all_requested.connect(self._on_delete_all_clients)
        self.company_table.selected_run_requested.connect(self._on_selected_run)
        self.company_table.full_run_requested.connect(self._on_start)
        self.company_table.stop_requested.connect(self._on_stop)
        self.company_table.management_number_changed.connect(self._on_management_number_changed)

        # 시작 시 DB에서 수임처 목록 로드
        self._load_client_list()

        # Phase 1이 기본 선택 → 전체실행 버튼 비활성화
        self.company_table.full_run_btn.setEnabled(False)
        self.company_table.set_client_mode(True)

        # Phase 1 기본 선택 상태 초기화 (이름 필드 표시 등)
        self._on_phase_selected(1)

        # 진행 상황 폴링 타이머 (러너가 실행 중일 때)
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(2000)
        self._poll_timer.timeout.connect(self._poll_step_detail)

        # 도움말 메뉴 (업데이트 확인 / 정보)
        self._create_help_menu()

        # 시작 직후 자동 업데이트 확인 (무알림; dev 모드/스로틀 시 조기 반환)
        QTimer.singleShot(2500, self._auto_check_for_update)

        # 주기적 인증 갱신 (4시간마다)
        self._auth_timer = QTimer(self)
        self._auth_timer.setInterval(AUTH_REFRESH_INTERVAL_SECS * 1000)
        self._auth_timer.timeout.connect(self._periodic_auth_check)
        self._auth_timer.start()

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

        # 상태바 우측: 로그인 정보 + 로그아웃 버튼
        self._user_label = QLabel()
        self._user_label.setStyleSheet("color: #666; padding: 0 8px;")
        self.statusBar().addPermanentWidget(self._user_label)

        self._logout_btn = QPushButton("로그아웃")
        self._logout_btn.setFlat(True)
        self._logout_btn.setFixedHeight(20)
        self._logout_btn.setStyleSheet(
            "QPushButton { color: #666; border: none; padding: 0 8px; text-decoration: underline; }"
            "QPushButton:hover { color: #f44336; }"
        )
        self._logout_btn.clicked.connect(self._on_logout)
        self.statusBar().addPermanentWidget(self._logout_btn)

        self._update_user_info()

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
        self.year_spin.setValue(datetime.now().year)
        self.year_spin.setFixedWidth(70)
        layout.addWidget(self.year_spin)

        # 월
        layout.addWidget(QLabel("월"))
        self.month_spin = QSpinBox()
        self.month_spin.setRange(1, 12)
        self.month_spin.setValue(datetime.now().month)
        self.month_spin.setFixedWidth(50)
        layout.addWidget(self.month_spin)

        # dry-run
        self.dry_run_check = QCheckBox("dry-run")
        self.dry_run_check.setChecked(True)
        layout.addWidget(self.dry_run_check)

        # 수임처 담당자 이름 (Phase 1 선택 시만 표시)
        self.name_label = QLabel("담당자")
        self.name_label.setVisible(False)
        layout.addWidget(self.name_label)

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("이름 입력")
        self.name_input.setFixedWidth(120)
        self.name_input.setVisible(False)
        layout.addWidget(self.name_input)

        # 전자신고 비밀번호 (Phase 7 선택 시만 표시)
        self.pw_label = QLabel("비밀번호")
        self.pw_label.setVisible(False)
        layout.addWidget(self.pw_label)

        self.pw_input = QLineEdit()
        self.pw_input.setPlaceholderText("8~15자리")
        self.pw_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.pw_input.setFixedWidth(150)
        self.pw_input.setVisible(False)
        layout.addWidget(self.pw_input)

        layout.addStretch()

        # 제어 버튼
        self.pause_btn = QPushButton("일시정지")
        self.pause_btn.setEnabled(False)
        self.pause_btn.setVisible(False)
        self.pause_btn.clicked.connect(self._on_pause)
        layout.addWidget(self.pause_btn)

        return toolbar

    def _load_phases(self):
        """페이즈 목록 로드 (워크플로우 모듈 import로 레지스트리 등록)"""
        import src.workflows.wehago_list_clients  # noqa: F401
        import src.workflows.nhis_edi             # noqa: F401
        import src.workflows.nps_edi              # noqa: F401
        import src.workflows.wehago_swsa          # noqa: F401
        import src.workflows.wehago_salary_pdf    # noqa: F401
        import src.workflows.wehago_swta          # noqa: F401
        import src.workflows.wehago_swer          # noqa: F401
        import src.workflows.hometax              # noqa: F401

        from src.workflows.registry import get_all_phases, register_parallel_phase
        # 사이드바 "공단 EDI 병렬 자동화" Phase 2 (메타데이터 전용, is_parallel=True)
        register_parallel_phase(2, "공단 EDI 병렬 자동화")
        phases = get_all_phases()

        # UI 잠금: registry 의 ui_locked 플래그(phase 4~8)가 True면 버튼 비활성.
        # 기능(워크플로우/레지스트리)은 건드리지 않고 사이드바 버튼만 비활성화.
        # (PhaseButton.enabled=False → 회색 표시 + 클릭 시그널 미연결)
        for phase in phases:
            if phase.get("ui_locked"):
                phase["enabled"] = False

        self.sidebar.set_phases(phases)

    # ── Slot ──

    def _on_log(self, message: str):
        self.log_panel.append_log(message)

    def _on_error(self, message: str):
        self.log_panel.append_log(message)
        self.statusBar().showMessage(message[:120])

    def _on_phase_changed(self, phase_id: int, status: str):
        self._automation_active = (status == "running")
        self.sidebar.update_phase_status(phase_id, status)
        self.statusBar().showMessage(f"Phase {phase_id}: {status}")

        # 페이즈 완료/실패 시 버튼 상태 복원
        if status in ("completed", "failed"):
            self.company_table.set_run_active(False)
            self.pause_btn.setEnabled(False)
            self._poll_timer.stop()
            self.company_table.set_buttons_enabled(True)
            if self._is_list_phase(self._selected_phase):
                self.company_table.full_run_btn.setEnabled(False)
            if not self._is_list_phase(self._selected_phase):
                self.company_table.set_selected_run_mode(True)

        if self._is_list_phase(phase_id) and status == "completed":
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
        if self._is_list_phase(phase_id):
            self._load_client_list()
            self.company_table.full_run_btn.setVisible(False)
            self.company_table.set_client_mode(True)
            self.company_table.set_selected_run_mode(False)
        else:
            self.company_table.full_run_btn.setVisible(True)
            self.company_table.set_client_mode(False)
            self._load_client_list(portal_override=self._get_portal_for_phase(phase_id))
            self.company_table.set_selected_run_mode(True)

        # Phase 1 선택 시 이름 필드 표시
        show_name = self._is_list_phase(phase_id)
        self.name_label.setVisible(show_name)
        self.name_input.setVisible(show_name)
        if show_name:
            self.name_input.setFocus()

        # Phase 7 선택 시 비밀번호 필드 표시
        show_pw = self._needs_password(phase_id)
        self.pw_label.setVisible(show_pw)
        self.pw_input.setVisible(show_pw)
        if show_pw:
            self.pw_input.setFocus()
        else:
            self.pw_input.clear()

    def _get_portal_for_phase(self, phase_id: int) -> str | None:
        """페이즈 ID에 해당하는 포털 반환"""
        from src.workflows.registry import get_phase_info
        info = get_phase_info(phase_id)
        return info["portal"] if info else None

    def _phase_info(self, phase_id: int) -> dict:
        from src.workflows.registry import get_phase_info
        return get_phase_info(phase_id) or {}

    def _is_list_phase(self, phase_id: int) -> bool:
        """수임처 리스트 모드 phase(Phase 1) 여부."""
        return bool(self._phase_info(phase_id).get("is_list_phase"))

    def _is_parallel(self) -> bool:
        """현재 선택 phase 가 병렬(공단 EDI 병렬 자동화)인지."""
        return bool(self._phase_info(self._selected_phase).get("is_parallel"))

    def _needs_password(self, phase_id: int) -> bool:
        """UI 비밀번호 필드가 필요한 phase(Phase 7, 8) 여부."""
        return bool(self._phase_info(phase_id).get("needs_password"))

    def _load_client_list(self, portal_override: str | None = None):
        """DB에서 수임처 목록을 조회하여 테이블에 표시

        portal_override가 None이면 Phase 1 모드 (wehago만).
        portal_override가 지정되면 해당 포털 우선, 없으면 wehago fallback.
        """
        import os
        from src.batch.db import BatchDB, ClientRepository
        from src.batch.models import get_management_number

        try:
            if not os.path.exists(DB_PATH):
                self.company_table.update_clients([])
                return

            with BatchDB(DB_PATH) as db:
                client_repo = ClientRepository(db)
                clients = client_repo.list_all()
                filtered = [c for c in clients if c.name != "__전체수임처조회__"]

                if portal_override:
                    portal_clients = [c for c in filtered if c.portal == portal_override]
                    wehago_clients = [c for c in filtered if c.portal == "wehago"]
                    source = portal_clients if portal_clients else wehago_clients
                else:
                    source = [c for c in filtered if c.portal == "wehago"]

                client_dicts = [
                    {
                        "id": c.id,
                        "name": c.name.replace("[테스트] ", ""),
                        "business_number": c.business_number,
                        "management_number": get_management_number(c),
                        "management_number_override": c.management_number or "",
                        "portal": c.portal,
                        "enabled": c.enabled,
                    }
                    for c in source
                ]
                self.company_table.update_clients(client_dicts)
        except Exception:
            self.company_table.update_clients([])

    def _on_job_selected(self, job_id: int):
        """수임처 테이블에서 행 클릭 → 세부 단계 표시"""
        self._selected_job_id = job_id
        self._poll_step_detail()

    def _on_parallel_finished(self):
        self.company_table.set_run_active(False)
        self.company_table.set_buttons_enabled(True)
        self.company_table.set_selected_run_mode(True)
        self._on_log("[병렬] 모든 subprocess 완료")

    def _on_parallel_finished_one(self, which: str, success: bool):
        label = "국민연금(NPS)" if which == "nps" else "건강보험(NHIS)"
        self._on_log(f"[병렬] {label} {'완료' if success else '실패(로그 확인)'}")

    def _on_runner_finished(self):
        self.company_table.set_run_active(False)
        if self._is_list_phase(self._selected_phase):
            self.company_table.full_run_btn.setEnabled(False)
        self.pause_btn.setEnabled(False)
        self._poll_timer.stop()
        self.company_table.set_buttons_enabled(True)
        if not self._is_list_phase(self._selected_phase):
            self.company_table.set_selected_run_mode(True)

    def _poll_step_detail(self):
        """선택된 Job의 세부 단계를 DB에서 조회하여 업데이트"""
        if not self._selected_job_id:
            return

        import os
        from src.batch.db import BatchDB, StepRepository, JobRepository

        try:
            if not os.path.exists(DB_PATH):
                return

            with BatchDB(DB_PATH) as db:
                step_repo = StepRepository(db)
                steps = step_repo.list_by_job(self._selected_job_id)

                job_repo = JobRepository(db)
                job = job_repo.get(self._selected_job_id)
                client_name = job.client_name if job else ""

                step_dicts = [
                    {"step_name": s.step_name, "status": s.status}
                    for s in steps
                ]
                self.step_detail.set_steps(client_name, step_dicts)
        except Exception:
            pass

    # ── 제어 ──

    def _on_start(self):
        if self.parallel_runner.is_running():
            self._on_log("[병렬 실행 중] 단일 전체실행은 병렬 종료 후 가능합니다.")
            return
        if not self._selected_phase:
            self.statusBar().showMessage("페이즈를 먼저 선택하세요")
            return

        # list phase(수임처 리스트)는 "새로 가져오기" 버튼으로만 실행
        if self._is_list_phase(self._selected_phase):
            self.statusBar().showMessage("수임처 리스트는 '새로 가져오기' 버튼을 사용하세요")
            return

        # ── Phase 9: 공단 EDI 병렬 자동화 (NPS+NHIS subprocess 동시 실행) ──
        if self._is_parallel():
            year = self.year_spin.value()
            month = self.month_spin.value()
            self.company_table.set_run_active(True)
            self.company_table.set_buttons_enabled(False)
            self.parallel_runner.start(nps_port=9223, nhis_port=9224,
                                       firms=None, year=year, month=month)
            self._on_log("[병렬] NPS(9223)/NHIS(9224) 백그라운드 시작 (전체 수임처)")
            self._on_log("[병렬] 두 Chrome이 열리면 각각 공동인증서로 로그인하세요 (첫 1회, 이후 세션 재사용)")
            return

        # 비밀번호 필요 phase: 툴바 비밀번호 필드에서 읽기
        password = ""
        if self._needs_password(self._selected_phase):
            password = self.pw_input.text().strip()
            if not password:
                self.statusBar().showMessage("전자신고 비밀번호를 입력하세요")
                return

        self.company_table.set_run_active(True)
        self.pause_btn.setEnabled(True)

        start_kwargs = dict(
            dry_run=self.dry_run_check.isChecked(),
            year=self.year_spin.value(),
            month=self.month_spin.value(),
        )
        if password:
            start_kwargs["password"] = password

        self.runner.start_phase(self._selected_phase, **start_kwargs)
        self._poll_timer.start()

    def _on_pause(self):
        if self.runner.is_paused:
            self.runner.request_resume()
            self.pause_btn.setText("일시정지")
        else:
            self.runner.request_pause()
            self.pause_btn.setText("재개")

    def _on_stop(self):
        # Phase 9 병렬 정지
        if self._is_parallel():
            self.parallel_runner.stop()
            self._on_log("[병렬] 정지 요청 — subprocess/Chrome 종료 중")
            return
        self.runner.request_stop()
        self.runner.cleanup_session()
        self.company_table.set_run_active(False)
        self.pause_btn.setEnabled(False)
        self.pause_btn.setText("일시정지")
        self._poll_timer.stop()
        self.statusBar().showMessage("세션 종료됨. 다시 시작하려면 '전체실행'을 눌러주세요.")

    def closeEvent(self, event):
        self._poll_timer.stop()
        self._auth_timer.stop()
        # 업데이트 워커 정리
        if self._download_worker:
            self._download_worker.cancel()
        self._cleanup_worker("_download_worker")
        self._cleanup_worker("_update_worker")
        self.runner.request_stop()
        self.runner.wait(3000)
        event.accept()

    # ── 인증 ──

    def _update_user_info(self):
        """상태바에 현재 로그인된 이메일 표시."""
        user = auth.get_current_user()
        if user and user.get("email"):
            self._user_label.setText(f"👤 {user['email']}")
            self._logout_btn.setVisible(True)
        else:
            self._user_label.setText("")
            self._logout_btn.setVisible(False)

    def _periodic_auth_check(self):
        """4시간 주기로 세션 유효성 재확인 (백그라운드)."""
        self._auth_worker = AuthWorker(self)
        self._auth_worker.validation_done.connect(self._on_periodic_auth_result)
        self._auth_worker.start_validate()

    def _on_periodic_auth_result(self, valid: bool):
        """주기적 인증 검증 결과 처리."""
        self._cleanup_worker("_auth_worker")
        if valid:
            return
        # 검증 실패 → 유예 기간 확인
        if auth.is_within_grace_period():
            return
        # 유예 기간도 초과 → 로그인 다이얼로그 재표시
        self._prompt_relogin("인증이 만료되었습니다.\n다시 로그인해 주세요.")

    def _prompt_relogin(self, message: str):
        """세션을 초기화하고 로그인 다이얼로그를 표시.

        성공 시 타이머 재시작, 취소 시 앱 종료.
        """
        auth.clear_session()
        self._auth_timer.stop()

        from PySide6.QtWidgets import QDialog
        from src.ui.widgets.login_dialog import LoginDialog
        login_dlg = LoginDialog(self)
        if login_dlg.exec() != QDialog.Accepted:
            QApplication.quit()
            return

        # 재로그인 성공 → 타이머 재시작
        self._auth_timer.start()
        self._update_user_info()
        self.statusBar().showMessage("재로그인 완료")

    def _on_logout(self):
        """로그아웃 → 세션 삭제 → 로그인 다이얼로그 재표시."""
        # 자동화 진행 중이면 확인
        if self._automation_active:
            reply = QMessageBox.warning(
                self, "로그아웃",
                "자동화 작업이 진행 중입니다.\n정말 로그아웃하시겠습니까?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return

        auth.clear_session()
        self._auth_timer.stop()

        from PySide6.QtWidgets import QDialog
        from src.ui.widgets.login_dialog import LoginDialog
        login_dlg = LoginDialog(self)
        if login_dlg.exec() != QDialog.Accepted:
            QApplication.quit()
            return

        # 재로그인 성공 → 타이머 재시작
        self._auth_timer.start()
        self._update_user_info()
        self.statusBar().showMessage("재로그인 완료")

    # ── 수임처 관리 ──

    def _on_selected_run(self, clients: list[dict]):
        """선택건 실행: 선택된 수임처 여러 건에 대해 순차 자동화 실행"""
        if self.parallel_runner.is_running():
            self._on_log("[병렬 실행 중] 단일 선택실행은 병렬 종료 후 가능합니다.")
            return
        if not self._selected_phase or self._is_list_phase(self._selected_phase):
            return

        # ── Phase 9: 공단 EDI 병렬 (선택 수임처) ──
        if self._is_parallel():
            sel = [c for c in clients if c.get("name")]
            firms = [c.get("name") for c in sel] or None
            if not firms:
                self.statusBar().showMessage("수임처를 선택하세요")
                return
            # 사업장관리번호(override 우선) — CLI 가 관리번호 검색으로 수임처 선택.
            # 비었으면 CLI가 이름 fallback.
            mgmts = [c.get("management_number", "") for c in sel]
            year = self.year_spin.value()
            month = self.month_spin.value()
            self.company_table.set_run_active(True)
            self.company_table.set_buttons_enabled(False)
            self.company_table.set_selected_run_mode(False)
            self.parallel_runner.start(nps_port=9223, nhis_port=9224,
                                       firms=firms, mgmts=mgmts, year=year, month=month)
            self._on_log(f"[병렬] 선택 수임처 {len(firms)}건 병렬 실행: {', '.join(firms)}")
            return

        from src.batch.models import biz_to_mgmt_no
        from src.utils.log import log
        client_infos = []
        for c in clients:
            # override 관리번호 우선(건강보험/국민연금 사업장관리번호), 없으면 biz+'0'
            mgmt_no = c.get("management_number") or biz_to_mgmt_no(c.get("business_number", ""))
            log(f"  수임처: name='{c['name']}' biz='{c.get('business_number','')}' mgmt='{mgmt_no}'")
            client_infos.append({
                "name": c["name"],
                "management_number": mgmt_no,
                "business_number": c.get("business_number", ""),
            })

        self.company_table.set_run_active(True)
        self.pause_btn.setEnabled(False)
        self.company_table.set_buttons_enabled(False)
        self.company_table.set_selected_run_mode(False)

        # dry-run 체크박스 값 전달 (선택건 실행도 일반 실행과 동일하게 반영)
        extra_kwargs = {"dry_run": self.dry_run_check.isChecked()}

        # 비밀번호 필요 phase: 비밀번호 전달
        if self._needs_password(self._selected_phase):
            pw = self.pw_input.text().strip()
            if not pw:
                self.statusBar().showMessage("전자신고 비밀번호를 입력하세요")
                self.company_table.set_run_active(False)
                self.company_table.set_buttons_enabled(True)
                return
            extra_kwargs["password"] = pw

        self.runner.start_selected_clients(
            self._selected_phase, client_infos,
            year=self.year_spin.value(),
            month=self.month_spin.value(),
            **extra_kwargs,
        )
        self._poll_timer.start()

    def _on_refresh_clients(self):
        """WEHAGO에서 수임처 새로 가져오기"""
        self.company_table.set_buttons_enabled(False)
        name = self.name_input.text().strip() if hasattr(self, 'name_input') else ""
        self.runner.start_refresh_clients(name=name)

    def _on_management_number_changed(self, client_id: int, value: str):
        """표에서 관리번호 key-in 편집 → DB override 저장 (건강보험/국민연금용).

        빈 값이면 override 해제(원복). 위하고는 항상 DB 사업자등록번호로 검색하므로
        여기서 저장한 값은 NHIS/NPS 사업장관리번호에만 반영된다.
        """
        from src.batch.db import BatchDB, ClientRepository
        try:
            with BatchDB(DB_PATH) as db:
                ClientRepository(db).update_management_number(client_id, value)
        except Exception as e:
            self._on_log(f"관리번호 저장 실패 (client_id={client_id}): {e}")

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
        if not os.path.exists(DB_PATH):
            self.company_table.update_clients([])
            return

        conn = sqlite3.connect(DB_PATH)
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

    # ── 자동 업데이트 ──

    def _cleanup_worker(self, attr_name: str):
        """QThread 워커를 안전하게 정리 (disconnect + deleteLater + null)."""
        worker = getattr(self, attr_name, None)
        if worker is None:
            return
        try:
            worker.disconnect()
        except (RuntimeError, TypeError):
            pass
        if worker.isRunning():
            worker.quit()
            worker.wait(2000)
        worker.deleteLater()
        setattr(self, attr_name, None)

    def _create_help_menu(self):
        """상단 '도움말' 메뉴: 업데이트 확인 / 로그아웃 / 정보"""
        menu = self.menuBar().addMenu("도움말")
        act_update = menu.addAction("업데이트 확인")
        act_update.triggered.connect(self._manual_check_for_update)
        menu.addSeparator()
        act_logout = menu.addAction("로그아웃")
        act_logout.triggered.connect(self._on_logout)
        menu.addSeparator()
        act_about = menu.addAction("정보")
        act_about.triggered.connect(self._show_about)

    def _show_about(self):
        QMessageBox.information(
            self, "정보", f"원천징수 자동화\n버전 v{__version__}",
        )

    def _auto_check_for_update(self):
        """시작 직후 자동 확인 — 무알림. dev 모드/스로틀 시 건너뜀."""
        if not getattr(sys, "frozen", False):
            return
        if not updater.should_check_today():
            return
        updater.set_last_check()
        self._start_update_check(silent=True)

    def _manual_check_for_update(self):
        """도움말>업데이트 확인 — 결과를 항상 사용자에게 알림."""
        if not getattr(sys, "frozen", False):
            QMessageBox.information(
                self, "업데이트",
                f"개발 모드에서는 업데이트 설치를 진행하지 않습니다.\n현재 버전 v{__version__}",
            )
            return
        updater.set_last_check()
        self._start_update_check(silent=False)

    def _start_update_check(self, *, silent: bool):
        if self._update_in_progress:
            return
        self._update_in_progress = True
        self._update_worker = UpdateWorker(self)
        self._update_worker.check_done.connect(
            lambda res: self._on_update_check_result(res, silent)
        )
        self._update_worker.failed.connect(
            lambda msg: self._on_update_failed(msg, silent)
        )
        self._update_worker.start_check()

    def _on_update_failed(self, msg: str, silent: bool):
        self._update_in_progress = False
        self._cleanup_worker("_update_worker")
        if not silent:
            QMessageBox.warning(
                self, "업데이트 확인 실패",
                "업데이트 확인에 실패했습니다.\n인터넷 연결을 확인한 뒤 다시 시도해 주세요.",
            )

    def _on_update_check_result(self, res: dict, silent: bool):
        action = (res or {}).get("action", "none")

        if action == "none":
            self._update_in_progress = False
            self._cleanup_worker("_update_worker")
            if not silent:
                QMessageBox.information(
                    self, "업데이트", f"현재 최신 버전입니다. (v{__version__})",
                )
            return

        version = res.get("version", "")
        mandatory = (action == "mandatory")

        # 자동(무알림) 확인 시, 사용자가 건너뛴 버전이면 조용히 무시 (강제는 예외)
        if silent and not mandatory and updater.get_skip_version() == version:
            self._update_in_progress = False
            self._cleanup_worker("_update_worker")
            return

        # 자동화 진행 중에는 적용 불가 → 보류
        if self._automation_active:
            self._update_in_progress = False
            self._cleanup_worker("_update_worker")
            if not silent:
                QMessageBox.information(
                    self, "업데이트 보류",
                    "자동화 작업이 진행 중입니다.\n작업을 정지한 뒤 다시 시도해 주세요.",
                )
            return

        self._prompt_update(res, mandatory)

    def _prompt_update(self, res: dict, mandatory: bool):
        version = res.get("version", "")
        notes = res.get("notes", "")
        prefix = "필수 업데이트입니다.\n\n" if mandatory else ""
        text = (
            prefix
            + f"새 버전이 있습니다.\n\n현재: v{__version__}\n최신: v{version}\n"
            + (f"\n{notes}\n" if notes else "")
            + "\n지금 설치하시겠습니까?\n(설치 중 프로그램이 잠시 종료된 뒤 다시 실행됩니다.)"
        )
        box = QMessageBox(self)
        box.setWindowTitle("업데이트")
        box.setIcon(QMessageBox.Information)
        box.setText(text)
        btn_update = box.addButton("지금 업데이트", QMessageBox.AcceptRole)
        btn_quit = btn_skip = None
        if mandatory:
            btn_quit = box.addButton("종료", QMessageBox.RejectRole)
        else:
            box.addButton("나중에", QMessageBox.RejectRole)
            btn_skip = box.addButton("이 버전 건너뛰기", QMessageBox.DestructiveRole)
        box.exec()
        clicked = box.clickedButton()

        if clicked == btn_update:
            self._start_download(res)
        elif mandatory and clicked == btn_quit:
            self._update_in_progress = False
            QApplication.quit()
        elif (not mandatory) and btn_skip is not None and clicked == btn_skip:
            updater.set_skip_version(version)
            self._update_in_progress = False
            self._cleanup_worker("_update_worker")
        else:
            self._update_in_progress = False  # 나중에
            self._cleanup_worker("_update_worker")

    def _start_download(self, res: dict):
        size = int(res.get("size", 0) or 0)
        # 다운로드 + 설치 압축해제 여유공간(대략 2배) 확인
        if size and not updater.has_enough_disk(size * 2):
            self._update_in_progress = False
            QMessageBox.warning(
                self, "디스크 공간 부족",
                "업데이트에 필요한 디스크 여유 공간이 부족합니다.",
            )
            return

        self._download_canceled = False
        self._progress_dialog = QProgressDialog(
            "업데이트 다운로드 중...", "취소", 0, 100, self
        )
        self._progress_dialog.setWindowTitle("업데이트")
        self._progress_dialog.setWindowModality(Qt.WindowModal)
        self._progress_dialog.setMinimumDuration(0)
        self._progress_dialog.setAutoClose(False)
        self._progress_dialog.setAutoReset(False)
        self._progress_dialog.setValue(0)
        self._progress_dialog.canceled.connect(self._on_download_cancel)

        self._download_worker = UpdateWorker(self)
        self._download_worker.download_progress.connect(self._on_download_progress)
        self._download_worker.download_done.connect(self._on_download_done)
        self._download_worker.failed.connect(lambda msg: self._on_download_done(""))
        self._download_worker.start_download(
            res.get("url", ""), size, res.get("sha256", ""),
        )

    def _on_download_cancel(self):
        self._download_canceled = True
        if self._download_worker:
            self._download_worker.cancel()

    def _on_download_progress(self, done: int, total: int):
        if not self._progress_dialog:
            return
        if total > 0:
            pct = min(int(done * 100 / total), 100)
            self._progress_dialog.setValue(pct)
            self._progress_dialog.setLabelText(
                f"업데이트 다운로드 중... {pct}% "
                f"({done // (1024 * 1024)}MB / {total // (1024 * 1024)}MB)"
            )

    def _on_download_done(self, path: str):
        if self._progress_dialog:
            self._progress_dialog.close()
            self._progress_dialog = None

        if not path:
            self._update_in_progress = False
            self._cleanup_worker("_download_worker")
            if not self._download_canceled:
                QMessageBox.warning(
                    self, "업데이트 실패",
                    "다운로드에 실패했습니다.\n잠시 후 다시 시도해 주세요.",
                )
            return

        self._apply_update(path)

    def _apply_update(self, installer_path: str):
        if not getattr(sys, "frozen", False):
            self._update_in_progress = False
            QMessageBox.information(
                self, "업데이트",
                "개발 모드에서는 설치를 진행하지 않습니다.\n"
                f"다운로드 위치: {installer_path}",
            )
            return

        # 깔끔한 종료: 폴링 중지 → 자동화 워커 정지 → Chrome 종료
        self._poll_timer.stop()
        try:
            self.runner.request_stop()
            self.runner.cleanup_session()
            self.runner.wait(3000)
        except Exception:
            pass

        # 설치기를 분리 실행 (앱 종료 후 무인설치 → 재실행)
        if not updater.spawn_installer_and_detach(installer_path):
            self._update_in_progress = False
            QMessageBox.warning(
                self, "업데이트 실패", "설치 프로그램을 실행하지 못했습니다.",
            )
            return

        QApplication.quit()
