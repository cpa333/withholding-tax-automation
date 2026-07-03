"""NPS run_single_workplace 다운로드-실패 마스킹 해소 테스트 (Fix 3).

download_final_integrated 가 원천엑셀을 못 받으면({excel: None}) run_single_workplace 가
False 를 반환해야 한다 — run_auto_batch 가 이를 다운로드실패로 skipped 에 넣어 종합 리포트에
드러나게(Fix 3). 이전엔 반환값을 버려 누락이 항상 '완료'로 마스킹됐다(BUG2).

nps_auto_cdp 모듈 import 시의 stdout detach 는 try/except 가드되어 pytest capture 에 안전.
run_single_workplace 의 브라우저 의존(navigate/open_detail/download/human_delay/make_save_dir)
을 monkeypatch 로 끊어 순수 제어흐름(반환값)만 검증한다.
"""
import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import src.automation.nps.nps_auto_cdp as nps  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


def _patch_deps(monkeypatch, tmp_path, excel_result):
    async def fake_navigate(page):
        return True

    async def fake_open_detail(page, year=None, month=None):
        return {"ok": True}

    async def fake_download(page, context, save_dir, year=None, month=None):
        return {"excel": excel_result, "pdf": None}

    async def fake_delay(*a, **k):
        return None

    monkeypatch.setattr(nps, "navigate_to_decision_details", fake_navigate)
    monkeypatch.setattr(nps, "open_decision_detail", fake_open_detail)
    monkeypatch.setattr(nps, "download_final_integrated", fake_download)
    monkeypatch.setattr(nps, "human_delay", fake_delay)
    monkeypatch.setattr(nps, "make_save_dir", lambda *a, **k: str(tmp_path))


def test_returns_true_when_excel_downloaded(monkeypatch, tmp_path):
    _patch_deps(monkeypatch, tmp_path, os.path.join(str(tmp_path), "결정내역통보서_202606.xlsx"))
    ok = _run(nps.run_single_workplace(None, None, "테스트회사", year=2026, month=6))
    assert ok is True


def test_returns_false_when_excel_missing(monkeypatch, tmp_path):
    """★ BUG2 핵심: 엑셀 누락 시 False 반환 → 상층이 다운로드실패로 보고."""
    _patch_deps(monkeypatch, tmp_path, None)
    ok = _run(nps.run_single_workplace(None, None, "테스트회사", year=2026, month=6))
    assert ok is False


def test_returns_false_when_download_result_none(monkeypatch, tmp_path):
    """download_final_integrated 자체가 None 을 반환한 경우도 실패."""
    async def fake_download(page, context, save_dir, year=None, month=None):
        return None
    _patch_deps(monkeypatch, tmp_path, None)
    monkeypatch.setattr(nps, "download_final_integrated", fake_download)
    ok = _run(nps.run_single_workplace(None, None, "테스트회사", year=2026, month=6))
    assert ok is False


def test_returns_false_on_navigate_fail(monkeypatch, tmp_path):
    async def fake_navigate(page):
        return False
    _patch_deps(monkeypatch, tmp_path, None)
    monkeypatch.setattr(nps, "navigate_to_decision_details", fake_navigate)
    ok = _run(nps.run_single_workplace(None, None, "테스트회사", year=2026, month=6))
    assert ok is False


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
