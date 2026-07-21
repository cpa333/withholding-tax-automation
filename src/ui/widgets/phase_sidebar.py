"""페이즈 사이드바 — 상단 고정 항목 + 3개 카테고리 아코디언(공단 EDI/위하고/홈택스)"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QPushButton, QLabel, QScrollArea, QFrame,
)
from PySide6.QtCore import Signal, Qt

from src.ui.styles import STATUS_COLORS


# ── 카테고리 매핑 (표시 전용 — registry/실행 경로와 무관) ──
CATEGORY_ORDER = ("공단 EDI", "위하고", "홈택스")
FALLBACK_CATEGORY = "기타"
PORTAL_CATEGORY = {
    "parallel":   "공단 EDI",
    "nhis_edi":   "공단 EDI",
    "nps_edi":    "공단 EDI",
    "comwel_edi": "공단 EDI",
    "wehago":     "위하고",
    "hometax":    "홈택스",
}


def group_phases(phases: list[dict]):
    """phase 목록을 (pinned, [(카테고리명, [phase,...]), ...]) 로 분류하는 순수 함수.

    - is_list_phase 항목은 카테고리와 무관하게 상단 고정(pinned)으로 분리한다.
      ★ phase 1(수임처 리스트)은 portal="wehago" 이므로, portal 로 분류하기 **전에**
        반드시 is_list_phase 를 먼저 떼어내야 위하고로 흡수되지 않는다.
    - 나머지는 PORTAL_CATEGORY 로 버킷팅하고 CATEGORY_ORDER 순서를 유지한다.
    - 비어있는 카테고리는 생략, 매핑에 없는 portal 은 버리지 않고 후행 "기타"로 모은다.
    - pinned 및 각 그룹 내부는 phase_id 오름차순(입력 정렬에 의존하지 않음).

    Qt 에 의존하지 않으므로 QApplication 없이 단위 테스트 가능.
    """
    pinned = sorted(
        (p for p in phases if p.get("is_list_phase")),
        key=lambda p: p["phase_id"],
    )

    buckets: dict[str, list] = {}
    for p in phases:
        if p.get("is_list_phase"):
            continue
        cat = PORTAL_CATEGORY.get(p.get("portal"), FALLBACK_CATEGORY)
        buckets.setdefault(cat, []).append(p)

    # 알려진 카테고리 순서 유지 + 미지(fallback) 카테고리는 뒤에 배치
    ordered_names = list(CATEGORY_ORDER)
    for name in buckets:
        if name not in ordered_names:
            ordered_names.append(name)

    groups = []
    for name in ordered_names:
        items = buckets.get(name)
        if not items:
            continue
        groups.append((name, sorted(items, key=lambda p: p["phase_id"])))

    return pinned, groups


class PhaseButton(QWidget):
    """단일 페이즈 버튼 + 진행 상태 표시"""

    clicked = Signal(int)  # phase_id

    def __init__(self, phase_id: int, display_name: str, parent=None, *, enabled: bool = True):
        super().__init__(parent)
        self.phase_id = phase_id
        self._status = "pending"
        self._selected = False
        self._progress = (0, 0)
        self._enabled = enabled

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(2)

        self.btn = QPushButton(f"{phase_id}. {display_name}")
        self.btn.setFlat(True)

        if enabled:
            self.btn.setStyleSheet(
                "QPushButton { text-align: left; padding: 6px; font-size: 13px; "
                "color: #1a1a1a; background-color: transparent; border: none; }"
            )
            self.btn.clicked.connect(lambda: self.clicked.emit(self.phase_id))
        else:
            self.btn.setEnabled(False)
            self.btn.setStyleSheet(
                "QPushButton { text-align: left; padding: 6px; font-size: 13px; "
                "color: #b0b0b0; background-color: #e8e8e8; border: none; border-radius: 3px; } "
                "QPushButton:disabled { color: #b0b0b0; background-color: #e8e8e8; }"
            )

        layout.addWidget(self.btn)

        self.progress_label = QLabel("")
        self.progress_label.setStyleSheet("color: #666; font-size: 11px; padding-left: 8px;")
        layout.addWidget(self.progress_label)

        self._update_style()

    def set_selected(self, selected: bool):
        self._selected = selected
        self._update_style()

    def set_status(self, status: str, completed: int = 0, total: int = 0):
        self._status = status
        self._progress = (completed, total)

        if total > 0:
            self.progress_label.setText(f"  ({completed}/{total})")
        else:
            self.progress_label.setText("")

        self._update_style()

    def _update_style(self):
        if not self._enabled:
            self.setStyleSheet(
                "PhaseButton { background-color: #ececec; "
                "border-left: 4px solid #ccc; margin: 1px 4px; border-radius: 3px; }"
            )
            return

        fg, bg = STATUS_COLORS.get(self._status, STATUS_COLORS["pending"])
        if self._selected:
            bg = "#bbdefb"
            border_fg = "#0d47a1"
            btn_bg = "#bbdefb"
            btn_font = "font-weight: bold;"
        else:
            border_fg = fg
            btn_bg = "transparent"
            btn_font = ""
        self.setStyleSheet(
            f"PhaseButton {{ background-color: {bg}; "
            f"border-left: 4px solid {border_fg}; margin: 1px 4px; border-radius: 3px; }}"
        )
        self.btn.setStyleSheet(
            f"QPushButton {{ text-align: left; padding: 6px; font-size: 13px; "
            f"color: #1a1a1a; background-color: {btn_bg}; border: none; {btn_font} }}"
        )

    @property
    def status(self):
        return self._status


class CollapsibleSection(QWidget):
    """접이식 카테고리 섹션 — 헤더(화살표+라벨) 클릭 시 본문만 토글.

    독립 토글(다른 섹션에 영향 없음), 기본 펼침. 헤더 클릭은 phase_selected 를
    절대 emit 하지 않는다(선택은 자식 PhaseButton 만 담당).
    색상은 전부 하드코딩 라이트값 — 시스템 팔레트(다크모드)에 의존하지 않음.
    """

    def __init__(self, title: str, parent=None, *, expanded: bool = True):
        super().__init__(parent)
        self._title = title
        self._expanded = expanded

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.header = QPushButton()
        self.header.setFlat(True)
        self.header.setCursor(Qt.PointingHandCursor)
        # 전역 QPushButton QSS(테두리/배경)가 새지 않도록 전용 스타일시트 부여
        self.header.setStyleSheet(
            "QPushButton { text-align: left; padding: 6px 8px; font-size: 13px; "
            "font-weight: bold; color: #1a1a1a; background-color: #f0f3f7; border: none; } "
            "QPushButton:hover { background-color: #e4ebf3; }"
        )
        self.header.clicked.connect(self._toggle)
        layout.addWidget(self.header)

        self._body = QWidget()
        body_layout = QVBoxLayout(self._body)
        body_layout.setContentsMargins(10, 0, 0, 0)  # 카테고리 하위 들여쓰기
        body_layout.setSpacing(0)
        layout.addWidget(self._body)

        self._refresh_header()
        self._body.setVisible(self._expanded)

    def add_button(self, widget: QWidget):
        self._body.layout().addWidget(widget)

    def _toggle(self):
        self._expanded = not self._expanded
        self._body.setVisible(self._expanded)
        self._refresh_header()

    def _refresh_header(self):
        arrow = "▾" if self._expanded else "▸"
        self.header.setText(f"{arrow}  {self._title}")


class PhaseSidebar(QWidget):
    """페이즈 선택 사이드바 — 상단 고정 + 카테고리 아코디언"""

    phase_selected = Signal(int)  # phase_id

    def __init__(self, parent=None):
        super().__init__(parent)
        self._buttons: dict[int, PhaseButton] = {}
        self._selected_phase: int = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.setSpacing(0)

        title = QLabel("  자동화 단계")
        title.setStyleSheet("font-weight: bold; font-size: 14px; padding: 8px;")
        layout.addWidget(title)

        # 구분선
        layout.addWidget(self._make_divider())

        # 동적 콘텐츠 컨테이너 — set_phases 재진입 시 이 레이아웃만 비운다
        # (title/구분선은 정적으로 유지, spacer/섹션 누적 방지)
        self._content = QWidget()
        content_layout = QVBoxLayout(self._content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        # 세로 스크롤 — 카테고리를 모두 펼치면 총 높이가 사이드바 높이를 넘어
        # 위젯이 압축되며 글자가 잘리던 문제 방지. 항목은 항상 제 높이로 렌더되고,
        # 넘칠 때만 세로 스크롤바가 나타난다(가로 스크롤은 끔).
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self._content)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        layout.addWidget(scroll)

    @staticmethod
    def _make_divider() -> QWidget:
        line = QWidget()
        line.setFixedHeight(1)
        line.setStyleSheet("background-color: #ddd;")
        return line

    @staticmethod
    def _clear_layout(layout):
        """레이아웃의 모든 항목 제거 — 위젯은 deleteLater, spacer 는 자동 폐기."""
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()

    def set_phases(self, phases: list[dict]):
        """페이즈 목록 설정.

        phases: get_all_phases() 결과. 각 dict 는 phase_id/display_name/portal/
        enabled/is_list_phase 등을 포함. is_list_phase 는 상단 고정, 나머지는
        portal 기준 3개 카테고리 아코디언으로 그룹핑한다.
        """
        content_layout = self._content.layout()
        self._clear_layout(content_layout)
        self._buttons.clear()

        pinned, groups = group_phases(phases)

        # 상단 고정 항목(수임처 리스트) + 구분선
        if pinned:
            for phase in pinned:
                content_layout.addWidget(self._make_phase_button(phase))
            content_layout.addWidget(self._make_divider())

        # 카테고리별 아코디언 섹션 (기본 펼침)
        for name, items in groups:
            section = CollapsibleSection(name, expanded=True)
            for phase in items:
                section.add_button(self._make_phase_button(phase))
            content_layout.addWidget(section)

        # 빈 공간
        content_layout.addStretch(1)

        # 활성화된 첫 번째 페이즈 자동 선택 (평면 리스트 기준 — 기존 동작 보존)
        first_enabled = next(
            (p["phase_id"] for p in phases if p.get("enabled", True)),
            None,
        )
        if first_enabled is not None and first_enabled in self._buttons:
            self._selected_phase = first_enabled
            self._buttons[first_enabled].set_selected(True)

    def _make_phase_button(self, phase: dict) -> PhaseButton:
        """PhaseButton 생성 + 신호 연결 + self._buttons 등록(위치 무관, 전부 등록)."""
        btn = PhaseButton(phase["phase_id"], phase["display_name"],
                          enabled=phase.get("enabled", True))
        btn.clicked.connect(self._on_phase_clicked)
        self._buttons[phase["phase_id"]] = btn
        return btn

    def update_phase_status(self, phase_id: int, status: str,
                            completed: int = 0, total: int = 0):
        btn = self._buttons.get(phase_id)
        if btn:
            btn.set_status(status, completed, total)

    def _on_phase_clicked(self, phase_id: int):
        # 이전 선택 해제
        if self._selected_phase in self._buttons:
            self._buttons[self._selected_phase].set_selected(False)
        # 새 선택 표시
        self._selected_phase = phase_id
        if phase_id in self._buttons:
            self._buttons[phase_id].set_selected(True)
        self.phase_selected.emit(phase_id)
