"""WehagoSwsaWorkflow._locate_raw_data 단독·병렬(공단EDI) 양경로 탐색 테스트.

회귀(커밋 779c248 이후 병렬 모드에서 NHIS/NPS/고용보험이 모두 미반영되던 버그)를 잡는다:
_locate_raw_data 가 단독 실행 경로({보험}_{period}/{folder}/)만 알고
병렬 실행 경로(공단EDI_{period}/{folder}/{포털}/)를 모르던 문제.

get_desktop_path 를 tmp_path 로 monkeypatch 해 실제 바탕화면 오염을 막는다.
_locate_raw_data 는 @staticmethod 이므로 인스턴스화 없이 직접 호출.
"""
import os

import pytest

import src.workflows.wehago_swsa as wsw
from src.workflows.wehago_swsa import WehagoSwsaWorkflow

CLIENT = "리틀치프코리아"
YEAR = 2026
MONTH = 7
PERIOD = "202607"


@pytest.fixture(autouse=True)
def _silence_log(monkeypatch):
    """_locate_raw_data 의 lazy import log 를 no-op 처리 (출력/의존 최소화)."""
    import src.automation.wehago._common as common
    monkeypatch.setattr(common, "log", lambda *a, **k: None)


def _patch_desktop(monkeypatch, tmp_path):
    monkeypatch.setattr(wsw, "get_desktop_path", lambda: str(tmp_path))


def _touch(path):
    """빈 파일 생성 (내용 불필요 — _locate_raw_data 는 경로/이름만 본다)."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb"):
        pass


def test_standalone_paths_found(monkeypatch, tmp_path):
    """단독 실행 경로({보험}_{period}/{client}/) 3종 모두 발견 (레거시 호환)."""
    _patch_desktop(monkeypatch, tmp_path)
    _touch(os.path.join(str(tmp_path), f"국민건강보험_{PERIOD}", CLIENT,
                        "가입자고지내역서_건강_20260701.pdf"))
    _touch(os.path.join(str(tmp_path), f"국민연금_{PERIOD}", CLIENT,
                        "결정내역통보서_202607.xlsx"))
    _touch(os.path.join(str(tmp_path), f"고용보험_{PERIOD}", CLIENT,
                        "고용보험료지원금정보_202607.xls"))

    r = WehagoSwsaWorkflow._locate_raw_data(CLIENT, YEAR, MONTH)
    assert r is not None
    assert r["nhis_pdf"] and r["nhis_pdf"].endswith(".pdf")
    assert r["nps_integrated"] and r["nps_integrated"].endswith(".xlsx")
    assert r["ei_xls"] and r["ei_xls"].endswith(".xls")


def test_parallel_paths_found(monkeypatch, tmp_path):
    """병렬(공단EDI) 경로 하위 3종 모두 발견 — 회귀 핵심 (구 코드에서는 전부 None)."""
    _patch_desktop(monkeypatch, tmp_path)
    root = os.path.join(str(tmp_path), f"공단EDI_{PERIOD}", CLIENT)
    _touch(os.path.join(root, "국민건강보험", "가입자고지내역서_건강_20260701.pdf"))
    _touch(os.path.join(root, "국민연금", "결정내역통보서_202607.xlsx"))
    _touch(os.path.join(root, "고용보험", "고용보험료지원금정보_202607.xls"))

    r = WehagoSwsaWorkflow._locate_raw_data(CLIENT, YEAR, MONTH)
    assert r is not None
    assert r["nhis_pdf"] and "공단EDI" in r["nhis_pdf"]
    assert r["nps_integrated"] and "공단EDI" in r["nps_integrated"]
    assert r["ei_xls"] and "공단EDI" in r["ei_xls"]


def test_mixed_paths(monkeypatch, tmp_path):
    """혼용: NHIS 는 단독, NPS·EI 는 공단EDI → 각 보험별 독립 리졸브로 모두 발견."""
    _patch_desktop(monkeypatch, tmp_path)
    # NHIS 만 단독 경로
    _touch(os.path.join(str(tmp_path), f"국민건강보험_{PERIOD}", CLIENT,
                        "가입자고지내역서_건강_20260701.pdf"))
    # NPS·EI 는 공단EDI 경로
    root = os.path.join(str(tmp_path), f"공단EDI_{PERIOD}", CLIENT)
    _touch(os.path.join(root, "국민연금", "결정내역통보서_202607.xlsx"))
    _touch(os.path.join(root, "고용보험", "고용보험료지원금정보_202607.xls"))

    r = WehagoSwsaWorkflow._locate_raw_data(CLIENT, YEAR, MONTH)
    assert r is not None
    assert r["nhis_pdf"] and f"국민건강보험_{PERIOD}" in r["nhis_pdf"]
    assert r["nps_integrated"] and "공단EDI" in r["nps_integrated"]
    assert r["ei_xls"] and "공단EDI" in r["ei_xls"]


def test_no_paths_returns_none(monkeypatch, tmp_path):
    """어느 경로에도 폴더가 없으면 None."""
    _patch_desktop(monkeypatch, tmp_path)
    r = WehagoSwsaWorkflow._locate_raw_data(CLIENT, YEAR, MONTH)
    assert r is None


def test_nps_legacy_3files_in_parallel(monkeypatch, tmp_path):
    """공단EDI 경로에서 통합엑셀 없이 구 3파일만 → member/retro/govt 발견, integrated=None."""
    _patch_desktop(monkeypatch, tmp_path)
    nps = os.path.join(str(tmp_path), f"공단EDI_{PERIOD}", CLIENT, "국민연금")
    _touch(os.path.join(nps, "가입자내역_엑셀_202607.xlsx"))
    _touch(os.path.join(nps, "소급분내역_엑셀_202607.xlsx"))
    _touch(os.path.join(nps, "국고지원내역_엑셀_202607.xlsx"))

    r = WehagoSwsaWorkflow._locate_raw_data(CLIENT, YEAR, MONTH)
    assert r is not None
    assert r["nps_integrated"] is None
    assert r["nps_member"] and r["nps_member"].endswith(".xlsx")
    assert r["nps_retro"] and r["nps_retro"].endswith(".xlsx")
    assert r["nps_govt"] and r["nps_govt"].endswith(".xlsx")


def test_period_mismatch_returns_none(monkeypatch, tmp_path):
    """period 불일치(202607 폴더인데 2026/6 으로 호출) → None."""
    _patch_desktop(monkeypatch, tmp_path)
    _touch(os.path.join(str(tmp_path), f"공단EDI_{PERIOD}", CLIENT,
                        "국민연금", "결정내역통보서_202607.xlsx"))
    r = WehagoSwsaWorkflow._locate_raw_data(CLIENT, 2026, 6)  # 202606 조회
    assert r is None


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
