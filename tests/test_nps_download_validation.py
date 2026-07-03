"""NPS 엑셀 zip 매직 검증 테스트 (Fix 4).

_is_valid_xlsx 가 엑셀(zip 컨테이너, PK 매직 + 최소 크기)만 받아들이는지 검증.
공유 폴더에서 NHIS PDF 를 grab 하거나 사이드카/에러 페이지가 떨어진 경우를 가짜 엑셀로
리네임·보고하던 BUG2 경로를 차단한다. PDF %PDF- 매직 게이트와 동일 구조.
"""
import os

from src.automation.nps._download import _is_valid_xlsx


def _write(tmp_path, name, data):
    p = os.path.join(str(tmp_path), name)
    with open(p, "wb") as f:
        f.write(data)
    return p


def test_valid_xlsx_accepted(tmp_path):
    # xlsx 는 zip 컨테이너 — PK\x03\x04 매직 + 충분한 크기.
    p = _write(tmp_path, "ok.xlsx", b"PK\x03\x04" + b"\x00" * 4096)
    assert _is_valid_xlsx(p) is True


def test_pdf_bytes_rejected(tmp_path):
    # 공유 폴더에서 NHIS PDF 를 grab 한 경우 — %PDF- 매직이라 엑셄 아님.
    p = _write(tmp_path, "wrong.xlsx", b"%PDF-1.4\n" + b"\x00" * 4096)
    assert _is_valid_xlsx(p) is False


def test_truncated_rejected(tmp_path):
    # 크기 미달(사이드카/에러 페이지) — 매직은 맞아도 2048바이트 미만이면 거부.
    p = _write(tmp_path, "small.xlsx", b"PK\x03\x04" + b"\x00" * 100)
    assert _is_valid_xlsx(p) is False


def test_empty_file_rejected(tmp_path):
    p = _write(tmp_path, "empty.xlsx", b"")
    assert _is_valid_xlsx(p) is False


def test_missing_file_rejected(tmp_path):
    assert _is_valid_xlsx(os.path.join(str(tmp_path), "nope.xlsx")) is False


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
