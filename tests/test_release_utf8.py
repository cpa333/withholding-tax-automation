"""release.py cp949 자체 방어 테스트.

배경: v1.0.4 릴리스가 cp949 콘솔에서 "✓"/한글 노트 출력 중 UnicodeEncodeError 로
gh 업로드 직전에 죽어 공개된 적이 없음 (deploy.sh 는 PYTHONUTF8=1 을 export 하지만
release.py 수동 실행 경로가 무방비였다). release.py 는 import 시점에 stdout/stderr 를
utf-8(errors=replace) 로 reconfigure 해 스스로 방어해야 한다.
"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_release_import_survives_cp949_console():
    """cp949 스트림 강제 환경에서 release import + 유니코드 출력이 죽지 않는다."""
    env = os.environ.copy()
    env["PYTHONUTF8"] = "0"
    env["PYTHONIOENCODING"] = "cp949"
    env.pop("PYTHONLEGACYWINDOWSSTDIO", None)

    code = "import release; print('\\u2713 \\ud55c\\uae00 \\ub9b4\\ub9ac\\uc2a4 \\ub178\\ud2b8')"
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(ROOT), env=env, capture_output=True, timeout=60,
    )
    assert proc.returncode == 0, (
        f"cp949 콘솔에서 유니코드 출력 실패 (v1.0.4 재발):\n{proc.stderr.decode(errors='replace')}"
    )
    # reconfigure 이후 stdout 은 utf-8 — 체크마크가 살아서 나와야 한다
    assert "✓" in proc.stdout.decode("utf-8", errors="replace")
