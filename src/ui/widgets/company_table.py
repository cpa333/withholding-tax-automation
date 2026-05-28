"""수임처 목록 테이블 — 수임처별 작업 상태 표시"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QTableView, QLabel, QHBoxLayout,
)
from PySide6.QtCore import Qt, QAbstractTableModel, QModelIndex, Signal
from PySide6.QtGui import QColor


_STATUS_DISPLAY = {
    "pending":   ("대기",   "#9e9e9e"),
    "running":   ("진행중", "#2196f3"),
    "completed": ("완료",   "#4caf50"),
    "failed":    ("실패",   "#f44336"),
    "skipped":   ("건너뜀", "#ff9800"),
}

_HEADERS_JOBS = ["수임처명", "상태", "현재 단계", "소요시간", "에러"]
_HEADERS_CLIENTS = ["수임처명", "포털", "활성"]


class CompanyTableModel(QAbstractTableModel):
    """수임처 Job 목록을 테이블로 표시하는 모델"""

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
        """clients: [{"name", "portal", "enabled"}, ...]"""
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
            if role == Qt.ItemDataRole.DisplayRole:
                if col == 0: return row_data.get("name", "")
                elif col == 1: return row_data.get("portal", "")
                elif col == 2: return "O" if row_data.get("enabled", True) else "X"
            return None

        if role == Qt.ItemDataRole.DisplayRole:
            if col == 0: return row_data.get("name", "")
            elif col == 1:
                status = row_data.get("status", "pending")
                return _STATUS_DISPLAY.get(status, (status,))[0]
            elif col == 2: return row_data.get("current_step", "")
            elif col == 3:
                dur = row_data.get("duration")
                return f"{dur:.0f}s" if dur else ""
            elif col == 4: return row_data.get("error", "")
            return None

        if role == Qt.ItemDataRole.ForegroundRole and col == 1:
            status = row_data.get("status", "pending")
            color_hex = _STATUS_DISPLAY.get(status, (None, "#000"))[1]
            return QColor(color_hex)

        return None

    def get_job_at(self, row: int) -> dict | None:
        if 0 <= row < len(self._jobs):
            return self._jobs[row]
        return None


class CompanyTable(QWidget):
    """수임처 목록 테이블 + 에러 요약"""

    job_selected = Signal(int)  # job_id

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(4)

        # 에러 요약 라벨
        self.error_summary = QLabel("")
        self.error_summary.setStyleSheet("color: #f44336; font-size: 12px;")
        self.error_summary.setWordWrap(True)
        layout.addWidget(self.error_summary)

        # 테이블
        self.table = QTableView()
        self.model = CompanyTableModel()
        self.table.setModel(self.model)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableView.SelectRows)
        self.table.setSelectionMode(QTableView.SingleSelection)
        self.table.setEditTriggers(QTableView.NoEditTriggers)

        # 컬럼 너비
        self.table.setColumnWidth(0, 200)  # 수임처명
        self.table.setColumnWidth(1, 70)   # 상태
        self.table.setColumnWidth(2, 150)  # 현재 단계
        self.table.setColumnWidth(3, 70)   # 소요시간
        self.table.horizontalHeader().setStretchLastSection(True)

        self.table.clicked.connect(self._on_clicked)
        layout.addWidget(self.table)

    def update_jobs(self, jobs: list[dict], failed_info: list[dict] | None = None):
        """수임처 목록 업데이트"""
        self.model.set_jobs(jobs)

        if failed_info:
            errors = [f"  - {j['name']}: {j.get('error', '알 수 없음')}" for j in failed_info]
            self.error_summary.setText(
                f"에러 ({len(failed_info)}건):\n" + "\n".join(errors)
            )
        else:
            self.error_summary.setText("")

    def update_clients(self, clients: list[dict]):
        """수임처 마스터 목록 표시 (Phase 1 완료 후)"""
        self.model.set_clients(clients)
        self.error_summary.setText(f"등록된 수임처: {len(clients)}건")

    def _on_clicked(self, index):
        job = self.model.get_job_at(index.row())
        if job and "job_id" in job:
            self.job_selected.emit(job["job_id"])
