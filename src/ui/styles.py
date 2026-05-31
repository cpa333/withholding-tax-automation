"""공통 UI 스타일 — 색상 팔레트, 상태별 스타일, 버튼 템플릿"""

# 상태별 색상 (아이콘/텍스트, 배경)
STATUS_COLORS = {
    "pending":   ("#9e9e9e", "#f5f5f5"),
    "running":   ("#2196f3", "#e3f2fd"),
    "completed": ("#4caf50", "#e8f5e9"),
    "failed":    ("#f44336", "#ffebee"),
    "skipped":   ("#ff9800", "#fff3e0"),
    "paused":    ("#ff9800", "#fff3e0"),
}

# 상태 표시 (텍스트, 색상)
STATUS_DISPLAY = {
    "pending":   ("대기",   "#9e9e9e"),
    "running":   ("진행중", "#2196f3"),
    "completed": ("완료",   "#4caf50"),
    "failed":    ("실패",   "#f44336"),
    "skipped":   ("건너뜀", "#ff9800"),
}

# 단계 상태 아이콘
STEP_STATUS_STYLE = {
    "completed": ("✓", "#4caf50"),
    "running":   ("▶", "#2196f3"),
    "failed":    ("✗", "#f44336"),
    "pending":   ("○", "#9e9e9e"),
}


def btn_style(color: str, hover: str) -> str:
    return (
        f"QPushButton {{ background-color: {color}; color: white; "
        f"padding: 4px 12px; border-radius: 3px; font-size: 12px; }}"
        f"QPushButton:hover {{ background-color: {hover}; }}"
        f"QPushButton:disabled {{ background-color: #bbb; }}"
    )


BTN_BLUE = btn_style("#2196f3", "#1976d2")
BTN_RED = btn_style("#f44336", "#d32f2f")
BTN_ORANGE = btn_style("#ff9800", "#f57c00")
BTN_GREEN = (
    "QPushButton { background-color: #4caf50; color: white; "
    "padding: 5px 15px; border-radius: 3px; font-weight: bold; }"
)
