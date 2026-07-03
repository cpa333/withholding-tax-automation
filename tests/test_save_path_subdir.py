"""make_save_dir subdir 파라미터 테스트 — 병렬(2번) 포털별 하위폴더 분리 (Fix 1).

병렬 실행 시 NPS/NHIS 가 공단EDI 최상위를 공유하되 포털 하위폴더(국민연금/국민건강보험)
로 분리해 두 Chrome 의 listdir/cleanup 파일 레이스(BUG1/BUG2 근원 A)를 없앤다.
단일 실행은 subdir=None 으로 현행 {site}_{YYYYMM}/{client}/ 구조 유지.

get_desktop_path 를 tmp_path 로 monkeypatch 해 실제 바탕화면 오염을 막는다.
"""
import os

from src.utils.save_path import make_save_dir


def test_subdir_none_preserves_legacy_layout(monkeypatch, tmp_path):
    import src.utils.save_path as sp
    monkeypatch.setattr(sp, "get_desktop_path", lambda: str(tmp_path))
    d = make_save_dir("국민연금", "리틀치프코리아", year=2026, month=6)
    # 단일 실행: {site}_{YYYYMM}/{client}/ (하위폴더 없음)
    assert d == os.path.join(str(tmp_path), "국민연금_202606", "리틀치프코리아")


def test_subdir_splits_portals_under_shared_site(monkeypatch, tmp_path):
    """병렬: 공단EDI 최상위 공유 + 포털 하위폴더 분리 → 두 Chrome 이 다른 폴더에 쓴다."""
    import src.utils.save_path as sp
    monkeypatch.setattr(sp, "get_desktop_path", lambda: str(tmp_path))

    nps = make_save_dir("공단EDI", "리틀치프코리아", year=2026, month=6, subdir="국민연금")
    nhis = make_save_dir("공단EDI", "리틀치프코리아", year=2026, month=6, subdir="국민건강보험")

    assert nps == os.path.join(str(tmp_path), "공단EDI_202606", "리틀치프코리아", "국민연금")
    assert nhis == os.path.join(str(tmp_path), "공단EDI_202606", "리틀치프코리아", "국민건강보험")
    # ★ 핵심: 두 포털이 서로 다른 폴더 → listdir/cleanup 레이스 불가
    assert nps != nhis
    assert os.path.isdir(nps) and os.path.isdir(nhis)


def test_subdir_spaces_in_client_replaced(monkeypatch, tmp_path):
    import src.utils.save_path as sp
    monkeypatch.setattr(sp, "get_desktop_path", lambda: str(tmp_path))
    d = make_save_dir("공단EDI", "리틀 치프 코리아", year=2026, month=6, subdir="국민연금")
    assert "리틀_치프_코리아" in d


def test_subdir_reuse_is_idempotent(monkeypatch, tmp_path):
    """같은 인자로 재호출 시 같은 경로(이미 존재해도 exist_ok 로 정상)."""
    import src.utils.save_path as sp
    monkeypatch.setattr(sp, "get_desktop_path", lambda: str(tmp_path))
    a = make_save_dir("공단EDI", "회사A", year=2026, month=6, subdir="국민연금")
    b = make_save_dir("공단EDI", "회사A", year=2026, month=6, subdir="국민연금")
    assert a == b


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
