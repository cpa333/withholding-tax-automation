"""수임처 목록 테이블 — 수임처별 작업 상태 표시"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QTableView, QLabel, QHBoxLayout,
    QPushButton,
)
from PySide6.QtCore import Qt, QAbstractTableModel, QModelIndex, Signal
from PySide6.QtGui import QColor

from src.ui.styles import STATUS_DISPLAY, BTN_BLUE, BTN_RED, BTN_ORANGE, BTN_GREEN
from src.batch.models import biz_to_mgmt_no

_HEADERS_JOBS = ["수임처명", "상태", "현재 단계", "소요시간", "에러"]
_HEADERS_CLIENTS = ["수임처명", "사업자등록번호", "관리번호", "포털", "활성"]


class CompanyTableModel(QAbstractTableModel):
    """수임처 Job 목록을 테이블로 표시하는 모델"""

    # clients_mode 관리번호 컬럼 인덱스 (직접 key-in 편집 대상)
    _MGMT_COL = 2

    management_number_changed = Signal(int, str)  # (client_id, override_value)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._jobs: list[dict] = []
        self._clients_mode = False

    def set_jobs(self, jobs: list[dict]):
        """jobs: [{"name", "status", "current_step", "duration", "error"}, ...]"""
        self.beginResetModel()
        self._jobs = jobs
        self._clients_mode = False
        self.endResetModel()

    def set_clients(self, clients: list[dict]):
        """clients: [{"id","name","business_number","management_number",
                     "management_number_override","portal","enabled"}, ...]"""
        self.beginResetModel()
        self._jobs = clients
        self._clients_mode = True
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return len(self._jobs)

    def columnCount(self, parent=QModelIndex()):
        return len(_HEADERS_CLIENTS) if self._clients_mode else len(_HEADERS_JOBS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Horizontal:
            headers = _HEADERS_CLIENTS if self._clients_mode else _HEADERS_JOBS
            return headers[section]
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or index.row() >= len(self._jobs):
            return None

        row_data = self._jobs[index.row()]
        col = index.column()

        if self._clients_mode:
            # EditRole 도 DisplayRole 과 동일값 반환 → 관리번호 셀 편집 시
            # 현재 값이 빈칸이 아니라 기존 관리번호로 미리 채워진 채로 수정 가능
            if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
                if col == 0: return row_data.get("name", "")
                elif col == 1: return row_data.get("business_number", "")
                elif col == 2: return row_data.get("management_number", "")
                elif col == 3: return row_data.get("portal", "")
                elif col == 4: return "O" if row_data.get("enabled", True) else "X"
            return None

        if role == Qt.ItemDataRole.DisplayRole:
            if col == 0: return row_data.get("name", "")
            elif col == 1:
                status = row_data.get("status", "pending")
                return STATUS_DISPLAY.get(status, (status,))[0]
            elif col == 2: return row_data.get("current_step", "")
            elif col == 3:
                dur = row_data.get("duration")
                return f"{dur:.0f}s" if dur else ""
            elif col == 4: return row_data.get("error", "")
            return None

        if role == Qt.ItemDataRole.ForegroundRole and col == 1:
            status = row_data.get("status", "pending")
            color_hex = STATUS_DISPLAY.get(status, (None, "#000"))[1]
            return QColor(color_hex)

        return None

    def flags(self, index):
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        base = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        # clients_mode 의 관리번호 컬럼만 직접 key-in 편집 허용
        if self._clients_mode and index.column() == self._MGMT_COL:
            base |= Qt.ItemFlag.ItemIsEditable
        return base

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if role != Qt.ItemDataRole.EditRole:
            return False
        if not (self._clients_mode and index.column() == self._MGMT_COL):
            return False
        row_data = self._jobs[index.row()]
        client_id = row_data.get("id")
        if client_id is None:
            return False

        normalized = (value or "").strip()
        # 빈 값은 override 해제(원복) → biz_to_mgmt_no 자동계산 표시
        derived = biz_to_mgmt_no(row_data.get("business_number", ""))
        row_data["management_number_override"] = normalized
        row_data["management_number"] = normalized if normalized else derived

        tl = self.index(index.row(), self._MGMT_COL)
        self.dataChanged.emit(tl, tl, [Qt.ItemDataRole.DisplayRole])
        self.management_number_changed.emit(client_id, normalized)
        return True

    def get_job_at(self, row: int) -> dict | None:
        if 0 <= row < len(self._jobs):
            return self._jobs[row]
        return None

    def get_all_clients(self) -> list[dict]:
        """현재 테이블에 표시된 전체 수임처(clients_mode).

        선택건 실행(CompanyTable._update_selected_clients)과 동일한 dict 형태를
        반환 → 전체 실행(ALL) 병렬 경로에서 firms/mgmts 조립 시 선택건(SELECTED)
        과 완전히 같은 downstream 계약을 갖는다. clients_mode 가 아니면 빈 리스트.
        enabled 필드를 포함해 호출측에서 비활성(X) 수임처를 필터링할 수 있게 한다.
        """
        clients: list[dict] = []
        if not self._clients_mode:
            return clients
        for job in self._jobs:
            if job and job.get("name"):
                clients.append({
                    "name": job.get("name", ""),
                    "business_number": job.get("business_number", ""),
                    "management_number": job.get("management_number", ""),
                    "enabled": job.get("enabled", True),
                })
        return clients


class CompanyTable(QWidget):
    """수임처 목록 테이블 + 에러 요약"""

    job_selected = Signal(int)  # job_id
    refresh_requested = Signal()
    delete_all_requested = Signal()
    selected_run_requested = Signal(list)  # [{"name": str, "business_number": str}, ...]
    full_run_requested = Signal()
    stop_requested = Signal()
    management_number_changed = Signal(int, str)  # (client_id, override_value) — DB 저장용 릴레이

    def __init__(self, parent=None):
        super().__init__(parent)
        self._selected_clients: list[dict] = []
        self._is_running = False
        self._setup_ui()

        # 선택 변경 시그널 — 한 번만 연결
        self.table.selectionModel().selectionChanged.connect(self._on_selection_changed)

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(4)

        # 수임처 관리 버튼 (Phase 1 모드)
        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)

        self.refresh_btn = QPushButton("새로 가져오기")
        self.refresh_btn.setStyleSheet(BTN_BLUE)
        self.refresh_btn.clicked.connect(self.refresh_requested.emit)

        self.delete_all_btn = QPushButton("모두 삭제")
        self.delete_all_btn.setStyleSheet(BTN_RED)
        self.delete_all_btn.clicked.connect(self.delete_all_requested.emit)

        self.full_run_btn = QPushButton("전체실행")
        self.full_run_btn.setStyleSheet(BTN_GREEN)
        self.full_run_btn.clicked.connect(self._on_full_run_clicked)
        self.full_run_btn.setVisible(False)

        self.selected_run_btn = QPushButton("선택건 실행")
        self.selected_run_btn.setStyleSheet(BTN_ORANGE)
        self.selected_run_btn.setEnabled(False)
        self.selected_run_btn.clicked.connect(self._on_selected_run)
        self.selected_run_btn.setVisible(False)

        btn_row.addWidget(self.refresh_btn)
        btn_row.addWidget(self.delete_all_btn)
        btn_row.addWidget(self.full_run_btn)
        btn_row.addWidget(self.selected_run_btn)
        btn_row.addStretch()

        self._btn_row_widget = QWidget()
        self._btn_row_widget.setLayout(btn_row)
        layout.addWidget(self._btn_row_widget)

        # 선택 방법 안내 (Phase 2+ 모드에서만 표시)
        self.selection_hint = QLabel("")
        self.selection_hint.setStyleSheet("color: #777; font-size: 11px; padding-left: 4px;")
        self.selection_hint.setWordWrap(True)
        self.selection_hint.setVisible(False)
        layout.addWidget(self.selection_hint)

        # 에러 요약 라벨
        self.error_summary = QLabel("")
        self.error_summary.setStyleSheet("color: #f44336; font-size: 12px;")
        self.error_summary.setWordWrap(True)
        layout.addWidget(self.error_summary)

        # 테이블
        self.table = QTableView()
        self.model = CompanyTableModel()
        self.table.setModel(self.model)
        # 모델의 관리번호 편집 → CompanyTable 릴레이 → main_window DB 저장
        self.model.management_number_changed.connect(self.management_number_changed)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableView.SelectRows)
        self.table.setSelectionMode(QTableView.ExtendedSelection)
        # 관리번호 컬럼만 편집 가능 — flags()가 해당 컬럼만 ItemIsEditable 부여
        self.table.setEditTriggers(
            QTableView.DoubleClicked | QTableView.EditKeyPressed | QTableView.AnyKeyPressed
        )

        # 컬럼 너비 (Job 모드 기준)
        self.table.setColumnWidth(0, 200)  # 수임처명
        self.table.setColumnWidth(1, 130)  # 사업자등록번호 / 상태
        self.table.setColumnWidth(2, 120)  # 관리번호(편집) / 현재 단계
        self.table.setColumnWidth(3, 70)   # 포털 / 소요시간
        self.table.setColumnWidth(4, 70)   # 활성 / 에러
        self.table.horizontalHeader().setStretchLastSection(True)

        layout.addWidget(self.table)

    def update_clients(self, clients: list[dict]):
        """수임처 마스터 목록 표시 (Phase 1 모드)"""
        self.model.set_clients(clients)
        self.error_summary.setText(f"등록된 수임처: {len(clients)}건")
        self._btn_row_widget.setVisible(True)

    def get_all_clients(self) -> list[dict]:
        """현재 표시된 전체 수임처(위임). CompanyTableModel.get_all_clients 참조."""
        return self.model.get_all_clients()

    def update_jobs(self, jobs: list[dict], failed_info: list[dict] | None = None):
        """수임처 Job 목록 업데이트 (Phase 2+ 모드)"""
        self.model.set_jobs(jobs)
        self.selected_run_btn.setEnabled(False)

        if failed_info:
            errors = [f"  - {j['name']}: {j.get('error', '알 수 없음')}" for j in failed_info]
            self.error_summary.setText(
                f"에러 ({len(failed_info)}건):\n" + "\n".join(errors)
            )
        else:
            self.error_summary.setText("")

    def set_client_mode(self, enabled: bool):
        """Phase 1 모드: 새로가져오기/모두삭제 표시, 전체실행/선택건실행 숨김"""
        self.refresh_btn.setVisible(enabled)
        self.delete_all_btn.setVisible(enabled)
        self.full_run_btn.setVisible(not enabled)
        self.selected_run_btn.setVisible(not enabled)
        self.selection_hint.setVisible(not enabled)
        if enabled:
            self.full_run_btn.setEnabled(False)
            self.selected_run_btn.setEnabled(False)

    def set_selected_run_mode(self, visible: bool):
        """Phase 2+ 전체실행/선택건실행 모드"""
        self.full_run_btn.setVisible(visible)
        self.selected_run_btn.setVisible(visible)
        self.selected_run_btn.setEnabled(False)
        self._selected_clients = []
        if visible:
            self.full_run_btn.setEnabled(True)
            self.selection_hint.setVisible(True)
            self.selection_hint.setText(
                "수임처를 선택하세요: 개별 선택은 Ctrl + 클릭, "
                "연속 범위 선택은 Shift + 클릭"
            )
        else:
            self.selection_hint.setVisible(False)

    def set_buttons_enabled(self, enabled: bool):
        """버튼 활성/비활성 (실행 중 잠금)"""
        self.refresh_btn.setEnabled(enabled)
        self.delete_all_btn.setEnabled(enabled)
        self.full_run_btn.setEnabled(enabled)

    def _on_selection_changed(self, selected, deselected):
        """멀티 선택 변경 시 선택된 수임처 목록 업데이트"""
        self._update_selected_clients()

    def _update_selected_clients(self):
        indexes = self.table.selectionModel().selectedRows()
        self._selected_clients = []
        for idx in indexes:
            job = self.model.get_job_at(idx.row())
            if job and "name" in job and self.model._clients_mode:
                self._selected_clients.append({
                    "name": job.get("name", ""),
                    "business_number": job.get("business_number", ""),
                    "management_number": job.get("management_number", ""),
                })
        self.selected_run_btn.setEnabled(len(self._selected_clients) > 0)

    def _on_selected_run(self):
        if self._selected_clients:
            self.full_run_btn.setEnabled(False)
            self.selected_run_requested.emit(self._selected_clients)

    def _on_full_run_clicked(self):
        """전체실행/정지 토글 — 실행 중이면 정지, 대기 중이면 전체실행"""
        if self._is_running:
            self.stop_requested.emit()
        else:
            self.full_run_requested.emit()

    def set_run_active(self, active: bool):
        """실행 상태 전환: 버튼이 '전체실행'(초록) ↔ '정지'(빨강) 로 토글"""
        self._is_running = active
        if active:
            self.full_run_btn.setText("정지")
            self.full_run_btn.setStyleSheet(BTN_RED)
            self.full_run_btn.setEnabled(True)
        else:
            self.full_run_btn.setText("전체실행")
            self.full_run_btn.setStyleSheet(BTN_GREEN)
            self.full_run_btn.setEnabled(True)

    def set_running(self, active: bool):
        """병렬 실행 상태 통합 전환. full_run_btn 은 항상 정지 버튼으로 동작.

        기존엔 set_run_active(True) + set_buttons_enabled(False) +
        set_selected_run_mode(False) 를 연달아 호출했으나, 뒤 두 메서드가
        full_run_btn(=정지 버튼)까지 같이 비활성화/숨김 처리해 실행 중 정지 버튼이
        사라지는 버그가 있었다. 정지 버튼은 실행 중 반드시 보이고 활성화되어야 하므로
        이 메서드에서 위젯별로 직접 제어한다(set_selected_run_mode 의 두 버튼 가시성
        결합을 우회).

        - active=True(실행 중): full_run_btn='정지'(빨강)+visible+enabled.
          refresh/delete_all 비활성, selected_run_btn 숨김, selection_hint 숨김.
        - active=False(완료): set_run_active(False)+set_buttons_enabled(True)+
          set_selected_run_mode(True) 의 정확한 동등 복원(hint 텍스트 포함).
        """
        self._is_running = active
        if active:
            self.full_run_btn.setText("정지")
            self.full_run_btn.setStyleSheet(BTN_RED)
            self.full_run_btn.setEnabled(True)
            self.full_run_btn.setVisible(True)
            self.refresh_btn.setEnabled(False)
            self.delete_all_btn.setEnabled(False)
            self.selected_run_btn.setVisible(False)
            self.selection_hint.setVisible(False)
        else:
            self.full_run_btn.setText("전체실행")
            self.full_run_btn.setStyleSheet(BTN_GREEN)
            self.full_run_btn.setEnabled(True)
            self.full_run_btn.setVisible(True)
            self.refresh_btn.setEnabled(True)
            self.delete_all_btn.setEnabled(True)
            self.selected_run_btn.setVisible(True)
            self.selected_run_btn.setEnabled(False)
            self._selected_clients = []
            self.selection_hint.setVisible(True)
            self.selection_hint.setText(
                "수임처를 선택하세요: 개별 선택은 Ctrl + 클릭, "
                "연속 범위 선택은 Shift + 클릭"
            )
