"""management_number override 보존 회귀테스트 (Fix A) + auto-calc 단위테스트 (Fix B 기반).

새로가져오기(replace_clients_preserving_mgmt)가 management_number override를
DELETE+INSERT 후에도 보존하는지 검증. 예전엔 INSERT 가 해당 컬럼을 안 넣어 매번 wipe 됐다
(2026-07-03 사건 — 24개 전부 빈 값). biz_to_mgmt_no/get_management_number 는 Fix B 병렬
자가방어의 기반이 되는 auto-calc(biz+'0') 로직.
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.batch.db import BatchDB, ClientRepository
from src.batch.models import Client, biz_to_mgmt_no, get_management_number


def _fresh_db() -> str:
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    return path


def _seed(db_path, name, biz, mgmt):
    with BatchDB(db_path) as db:
        repo = ClientRepository(db)
        cid = repo.upsert(Client(name=name, portal="wehago",
                                 business_number=biz, enabled=True))
        if mgmt:
            repo.update_management_number(cid, mgmt)


def test_refresh_preserves_management_number_override():
    """★ Fix A 핵심: 새로가져오기 후에도 수동 override 잔존 (이전엔 wipe)."""
    path = _fresh_db()
    try:
        _seed(path, "주식회사A", "111-22-33333", "111223333399")  # override (≠ biz+'0')
        _seed(path, "주식회사B", "222-33-44444", "")              # override 없음
        # 새로가져오기 시뮬: 같은 name 스크랩(mgmt 없음)
        with BatchDB(path) as db:
            ClientRepository(db).replace_clients_preserving_mgmt([
                {"name": "주식회사A", "business_number": "111-22-33333", "report_cycle": "매월"},
                {"name": "주식회사B", "business_number": "222-33-44444", "report_cycle": ""},
            ])
        with BatchDB(path) as db:
            repo = ClientRepository(db)
            a = repo.get_by_name("주식회사A", "wehago")
            b = repo.get_by_name("주식회사B", "wehago")
        assert a is not None and a.management_number == "111223333399", "override 보존 실패"
        assert b is not None and b.management_number == "", "override 없는 회사는 빈 값 유지"
    finally:
        os.unlink(path)


def test_refresh_deletes_missing_and_inserts_new_empty():
    """누락(스크랩에 없음) 행은 삭제, 신규 행은 빈 mgmt 로 INSERT."""
    path = _fresh_db()
    try:
        _seed(path, "삭제될회사", "999-88-77777", "999887777799")
        with BatchDB(path) as db:
            ClientRepository(db).replace_clients_preserving_mgmt([
                {"name": "신규회사", "business_number": "555-66-77777", "report_cycle": ""},
            ])
        with BatchDB(path) as db:
            repo = ClientRepository(db)
            assert repo.get_by_name("삭제될회사", "wehago") is None
            new = repo.get_by_name("신규회사", "wehago")
            assert new is not None and new.management_number == ""
    finally:
        os.unlink(path)


def test_refresh_report_cycle_updated():
    """report_cycle 은 INSERT 에 포함되므로 스크랩값으로 갱신됨(mgmt 보존과 무관)."""
    path = _fresh_db()
    try:
        _seed(path, "주식회사A", "111-22-33333", "111223333399")
        with BatchDB(path) as db:
            ClientRepository(db).replace_clients_preserving_mgmt([
                {"name": "주식회사A", "business_number": "111-22-33333", "report_cycle": "반기"},
            ])
        with BatchDB(path) as db:
            a = ClientRepository(db).get_by_name("주식회사A", "wehago")
        assert a.report_cycle == "반기"
        assert a.management_number == "111223333399"  # mgmt 도 여전히 보존
    finally:
        os.unlink(path)


def test_biz_to_mgmt_no():
    assert biz_to_mgmt_no("123-45-67890") == "12345678900"
    assert biz_to_mgmt_no("111-22-3333") == "1112233330"
    assert biz_to_mgmt_no("") == ""


def test_get_management_number_override_precedence():
    """override 우선, 없으면 biz+'0' 자동계산 (Fix B 병렬 자가방어의 기반)."""
    c1 = Client(name="X", portal="wehago", business_number="123-45-67890",
                management_number="OVERRIDE99")
    assert get_management_number(c1) == "OVERRIDE99"
    c2 = Client(name="Y", portal="wehago", business_number="123-45-67890",
                management_number="")
    assert get_management_number(c2) == "12345678900"


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
