"""pytest 공용 픽스처 — 배치 엔진 회귀 테스트용.

배치 레이어(src.batch.*)만 사용하므로 Playwright/PySide6 없이 동작.
cp949 콘솔 인코딩 이슈 회피를 위해 PYTHONUTF8=1 권장.
"""
import sys
from pathlib import Path

# 프로젝트 루트를 sys.path에 (pytest pythonpath 와 이중 보험)
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest

from src.batch.db import BatchDB, ClientRepository
from src.batch.engine import BatchEngine
from src.batch.models import Client


def seed_clients(db_path: str, portal: str = "wehago", count: int = 2) -> None:
    """engine.initialize 전 활성 수임처를 시드(독립 연결 사용 후 종료)."""
    with BatchDB(db_path) as db:
        repo = ClientRepository(db)
        for i in range(count):
            repo.upsert(Client(
                name=f"수임처_{i}",
                portal=portal,
                business_number=f"123-45-6789{i}",
                enabled=True,
                priority=i,
            ))


@pytest.fixture
def db_path(tmp_path) -> str:
    return str(tmp_path / "test_batch.db")


@pytest.fixture
def engine_with_jobs(db_path):
    """클라이언트 2명 시드 + prepare_batch(2026-05) 까지 마친 엔진. run() 대기."""
    seed_clients(db_path)
    engine = BatchEngine(db_path, portal="wehago")
    engine.initialize()
    batch = engine.prepare_batch(year=2026, month=5)
    yield engine, batch
    engine.close()
