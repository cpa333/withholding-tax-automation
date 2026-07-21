"""updater 진단 로그(update.log) 테스트 — 기록/로테이션/never-raise 계약.

무음 자동 확인 경로는 UI 표시가 전혀 없으므로 update.log 가 유일한 사후 진단
근거다. 로깅 자체가 앱/업데이트를 죽여서는 안 된다(절대 raise 금지).
"""
import re

import pytest

from src.utils import updater


@pytest.fixture
def log_in_tmp(monkeypatch, tmp_path):
    """_LOG_DIR/_LOG_PATH 를 tmp 로 격리."""
    log_dir = tmp_path / "logs"
    log_path = log_dir / "update.log"
    monkeypatch.setattr(updater, "_LOG_DIR", str(log_dir))
    monkeypatch.setattr(updater, "_LOG_PATH", str(log_path))
    return log_path


def _read(path) -> str:
    return path.read_text(encoding="utf-8")


def test_log_event_appends_timestamped_line(log_in_tmp):
    updater.log_event("fetch: ok remote=1.1.0")
    updater.log_event("check: local=1.0.5 remote=1.1.0 action=optional")
    lines = _read(log_in_tmp).splitlines()
    assert len(lines) == 2
    # ISO 타임스탬프 prefix (초 단위) + 메시지
    assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2} fetch: ok", lines[0])
    assert lines[1].endswith("action=optional")


def test_log_event_rotates_over_cap(log_in_tmp, monkeypatch):
    monkeypatch.setattr(updater, "_LOG_MAX_BYTES", 100)
    log_in_tmp.parent.mkdir(parents=True, exist_ok=True)
    log_in_tmp.write_text("x" * 200, encoding="utf-8")  # 캡 초과 상태로 시작

    updater.log_event("after-rotation")

    rotated = log_in_tmp.with_name("update.log.1")
    assert rotated.exists() and _read(rotated) == "x" * 200
    assert "after-rotation" in _read(log_in_tmp)
    assert len(_read(log_in_tmp)) < 100  # 새 파일은 방금 한 줄뿐


def test_log_event_never_raises(monkeypatch, tmp_path):
    """로그 경로가 디렉토리라 쓰기 불가 → 조용히 무시(예외 비전파)."""
    blocked = tmp_path / "update.log"
    blocked.mkdir()
    monkeypatch.setattr(updater, "_LOG_DIR", str(tmp_path))
    monkeypatch.setattr(updater, "_LOG_PATH", str(blocked))
    updater.log_event("must-not-raise")  # 예외 없으면 통과


def test_validate_installer_logs_reason(log_in_tmp, tmp_path):
    # sha256 미지정 → 즉시 실패 + 사유 기록
    assert updater.validate_installer(str(tmp_path / "x.exe")) is False
    # 파일 없음 → stat 실패
    assert updater.validate_installer(str(tmp_path / "x.exe"), sha256="ab") is False
    # 1MB 미만 → too-small
    small = tmp_path / "small.exe"
    small.write_bytes(b"MZ" + b"\0" * 100)
    assert updater.validate_installer(str(small), sha256="ab") is False

    content = _read(log_in_tmp)
    assert "validate: fail no-sha256" in content
    assert "validate: fail stat" in content
    assert "validate: fail too-small size=102" in content


def test_spawn_installer_bad_path_returns_false(log_in_tmp):
    """cmd 메타문자(&) 경로 → ValueError 가 아니라 False (never-raise 계약).

    회귀 고정: build_relaunch_command 가 try 밖에 있던 시절엔 ValueError 가
    호출자(main_window._apply_update)까지 전파됐다.
    """
    ok = updater.spawn_installer_and_detach(
        r"C:\bad&path\installer.exe", exe_path=r"C:\app\app.exe",
    )
    assert ok is False
    assert "spawn: fail" in _read(log_in_tmp)
