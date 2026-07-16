"""COMWEL 당월보험료 부과내역조회(WL0502_P04) 다운로드 로직 단위 테스트.

라이브 검증(2026-07) 기반 신규 다운로드 흐름의 단위화 가능 부분 검증:
  - 파일명(산재/고용 탭 구분, period, 충돌 회피)
  - close id derive 헬퍼(P02 회귀 불변 + P04 신규)
  - 다운로드 파일 매직 형식 판별(PDF/XLSX/XLS)
  - 0건 스킵 + 폴더 미생성(FakePage 로 DOM 모킹)
  - 버튼 없음 스킵(정상)
  - _close_support_popup 이 P04 팝업 id 로부터 P04 close id 를 실사용

DOM 의존 흐름(인쇄→ClipReport 실제 다운로드, run_single_workplace 3단계 순서)은
라이브 CDP 검증 항목으로 남긴다(여기서는 mock 기반 분기/네이밍만).
"""
import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.automation.comwel._download import (
    _premium_detail_base_name,
    _popup_close_id, _report_modal_close_id,
    _detect_format,
    download_premium_detail_printout,
    _close_support_popup,
)
from src.automation.comwel._constants import (
    POPUP_SUPPORT_ID, POPUP_SUPPORT_CLOSE_ID, REPORT_MODAL_CLOSE_ID,
    POPUP_PREMIUM_DETAIL_ID, POPUP_PREMIUM_DETAIL_CLOSE_ID,
    REPORT_MODAL_P04_CLOSE_ID,
)


# ═══════════════════════════════════════════════════════════════════════
# 파일명: 산재/고용 탭 구분 + period + 충돌 회피
# ═══════════════════════════════════════════════════════════════════════

def test_base_name_sanjeong_with_period():
    assert _premium_detail_base_name("산재", 2026, 6) == "당월보험료부과내역_산재_202606"


def test_base_name_goyong_with_period():
    assert _premium_detail_base_name("고용", 2026, 6) == "당월보험료부과내역_고용_202606"


def test_base_name_zero_padded_month():
    # 월은 2자리 zero-pad (7월 → 07)
    assert _premium_detail_base_name("산재", 2026, 7) == "당월보험료부과내역_산재_202607"


def test_base_name_no_period():
    # year/month 미제공 → period 접미사 생략
    assert _premium_detail_base_name("산재") == "당월보험료부과내역_산재"
    assert _premium_detail_base_name("고용", None, None) == "당월보험료부과내역_고용"


def test_base_name_sanjeong_vs_goyong_no_collision():
    """산재/고용 같은 period → 파일명 반드시 상이(탭 태그로 구분)."""
    sj = _premium_detail_base_name("산재", 2026, 6)
    gy = _premium_detail_base_name("고용", 2026, 6)
    assert sj != gy
    assert "산재" in sj and "고용" in gy


def test_base_name_empty_tab_falls_back_to_sanjeong():
    # tab=None/빈 → 폴백 "산재"(조회 후 기본 활성 탭)
    assert _premium_detail_base_name(None, 2026, 6) == "당월보험료부과내역_산재_202606"
    assert _premium_detail_base_name("", 2026, 6) == "당월보험료부과내역_산재_202606"


# ═══════════════════════════════════════════════════════════════════════
# close id derive: P02 회귀(불변) + P04 신규 — 라이브 검증 id 와 일치
# ═══════════════════════════════════════════════════════════════════════

def test_popup_close_id_p04_matches_live_constant():
    assert _popup_close_id(POPUP_PREMIUM_DETAIL_ID) == POPUP_PREMIUM_DETAIL_CLOSE_ID
    assert _popup_close_id(POPUP_PREMIUM_DETAIL_ID) == "mf_wfm_content_WL0502_P04_close"


def test_report_modal_close_id_p04_matches_live_constant():
    assert _report_modal_close_id(POPUP_PREMIUM_DETAIL_ID) == REPORT_MODAL_P04_CLOSE_ID
    assert (_report_modal_close_id(POPUP_PREMIUM_DETAIL_ID)
            == "mf_wfm_content_WL0502_P04_wframe_WZ0203_close")


def test_popup_close_id_p02_regression_unchanged():
    """기존 지원금(P02) close id derive 가 라이브 상수와 불변."""
    assert _popup_close_id(POPUP_SUPPORT_ID) == POPUP_SUPPORT_CLOSE_ID
    assert _popup_close_id(POPUP_SUPPORT_ID) == "mf_wfm_content_WL0502_P02_close"


def test_report_modal_close_id_p02_regression_unchanged():
    assert _report_modal_close_id(POPUP_SUPPORT_ID) == REPORT_MODAL_CLOSE_ID
    assert (_report_modal_close_id(POPUP_SUPPORT_ID)
            == "mf_wfm_content_WL0502_P02_wframe_WZ0203_close")


# ═══════════════════════════════════════════════════════════════════════
# _detect_format: 다운로드 파일 매직 형식 판별
# ═══════════════════════════════════════════════════════════════════════

def test_detect_format_pdf(tmp_path):
    p = tmp_path / "a.pdf"
    p.write_bytes(b"%PDF-1.5\n%binary")
    assert _detect_format(str(p)) == "pdf"


def test_detect_format_xlsx(tmp_path):
    # OOXML: PK 매직 + 크기 2048 이상
    p = tmp_path / "a.xlsx"
    p.write_bytes(b"PK\x03\x04" + b"\x00" * 3000)
    assert _detect_format(str(p)) == "xlsx"


def test_detect_format_xls_ole2(tmp_path):
    # ClipReport 엑셀(구 .xls) — OLE2 Compound Document 매직
    p = tmp_path / "a.xls"
    p.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 100)
    assert _detect_format(str(p)) == "xls"


def test_detect_format_xlsx_too_small_is_none(tmp_path):
    # PK 매직이어도 2048 미만 → None(과도기 crdownload 등 오탐 방지)
    p = tmp_path / "small.xlsx"
    p.write_bytes(b"PK\x03\x04" + b"\x00" * 10)
    assert _detect_format(str(p)) is None


def test_detect_format_unknown_is_none(tmp_path):
    p = tmp_path / "a.bin"
    p.write_bytes(b"\x00\x01\x02\x03")
    assert _detect_format(str(p)) is None


# ═══════════════════════════════════════════════════════════════════════
# FakePage 기반 분기 테스트 — DOM 의존 evaluate 호출을 arg/expr 마커로 라우팅
# ═══════════════════════════════════════════════════════════════════════

class _FakePage:
    """download_premium_detail_printout 흐름 시뮬레이션용 page double.

    evaluate(expr, arg) 를 arg/expr 마커로 라우팅해 반환. eval_args 에 모든 arg 를
    기록해 close id 실사용 검증에 쓴다.
    """
    def __init__(self, *, count=0, launcher_id="fake_launcher_id",
                 popup_visible=True):
        self.count = count
        self.launcher_id = launcher_id
        self.popup_visible = popup_visible
        self.eval_args = []

    async def evaluate(self, expr, arg=None):
        self.eval_args.append(arg)
        s = expr if isinstance(expr, str) else ""
        # 당월보험료 부과내역 런처 버튼(텍스트 매칭 클릭)
        if isinstance(arg, str) and arg == "당월보험료 부과내역":
            return self.launcher_id
        # 건수 읽기: JS 에 '총'/'match' 포함
        if "총" in s and "match" in s:
            return self.count
        # 팝업 가시성 폴링
        if "getBoundingClientRect" in s and isinstance(arg, str) \
                and arg.startswith("mf_wfm_content_WL"):
            return self.popup_visible
        # 닫기/기타 — 의미있는 반환 없음
        return None


async def _fast_sleep(_):
    """asyncio.sleep 을 즉시 반환하도록 대체(테스트 속도)."""
    return


def test_premium_detail_skips_zero_count_no_folder(monkeypatch):
    """0건 → skipped=True, 인쇄 생략, 폴더(make_save_dir) 미생성."""
    import src.utils.save_path as sp
    import src.automation.comwel._download as dl

    monkeypatch.setattr(asyncio, "sleep", _fast_sleep)
    make_calls = []
    def _fake_make(*a, **k):
        make_calls.append((a, k))
        return os.path.join(os.path.dirname(__file__), "_fake_dir")
    monkeypatch.setattr(sp, "make_save_dir", _fake_make)

    page = _FakePage(count=0, launcher_id="mf_wfm_content_wq_uuid_1759",
                     popup_visible=True)
    # context 는 0건 경로에 도달하지 않음(setup_cdp 호출 전 반환)
    result = asyncio.run(download_premium_detail_printout(
        page, context=None, client_name="리드플렉스", tab="산재", year=2026, month=6,
    ))

    assert result["skipped"] is True
    assert result["count"] == 0
    assert result["print_clicked"] is False
    assert result["path"] is None
    # 폴더 생성 함수 미호출
    assert make_calls == []
    # 런처 클릭은 텍스트(keyword) 매칭으로 수행됨 — eval_args 에 키워드 남김
    assert "당월보험료 부과내역" in page.eval_args


def test_premium_detail_zero_count_closes_p04_popup(monkeypatch):
    """0건 스킵 시 P04 팝업 + ClipReport(WZ0203) 모달 close id 가 실사용된다."""
    monkeypatch.setattr(asyncio, "sleep", _fast_sleep)
    page = _FakePage(count=0, popup_visible=True)
    asyncio.run(download_premium_detail_printout(
        page, context=None, client_name="리드플렉스", tab="산재", year=2026, month=6,
    ))
    # close id derive 가 실제 evaluate 호출에 쓰였는지
    assert REPORT_MODAL_P04_CLOSE_ID in page.eval_args
    assert POPUP_PREMIUM_DETAIL_CLOSE_ID in page.eval_args


def test_premium_detail_skips_when_launcher_button_missing(monkeypatch):
    """당월보험료 부과내역 런처 버튼 자체가 없으면 스킵(정상, 버튼 미오픈)."""
    import src.utils.save_path as sp
    monkeypatch.setattr(asyncio, "sleep", _fast_sleep)
    make_calls = []
    monkeypatch.setattr(sp, "make_save_dir",
                        lambda *a, **k: make_calls.append((a, k)))

    page = _FakePage(count=99, launcher_id=None, popup_visible=True)
    result = asyncio.run(download_premium_detail_printout(
        page, context=None, client_name="샘플", tab="고용", year=2026, month=6,
    ))

    assert result["skipped"] is True
    assert result["count"] is None   # 팝업 안 열렸으므로 건수 미조회
    assert make_calls == []


def test_close_support_popup_default_uses_p02_ids(monkeypatch):
    """_close_support_popup() 기본값 = P02(지원금) close id — 기존 흐름 불변."""
    monkeypatch.setattr(asyncio, "sleep", _fast_sleep)
    page = _FakePage()
    asyncio.run(_close_support_popup(page))
    assert POPUP_SUPPORT_CLOSE_ID in page.eval_args
    assert REPORT_MODAL_CLOSE_ID in page.eval_args
    # P04 id 가 섞이지 않음
    assert POPUP_PREMIUM_DETAIL_CLOSE_ID not in page.eval_args


def test_close_support_popup_p04_explicit(monkeypatch):
    """명시적 P04 전달 시 P04 close id 사용(derive)."""
    monkeypatch.setattr(asyncio, "sleep", _fast_sleep)
    page = _FakePage()
    asyncio.run(_close_support_popup(page, POPUP_PREMIUM_DETAIL_ID))
    assert POPUP_PREMIUM_DETAIL_CLOSE_ID in page.eval_args
    assert REPORT_MODAL_P04_CLOSE_ID in page.eval_args


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
