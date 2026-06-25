"""NHIS 받은문서 월(YYYYMM) 매칭 회귀 테스트.

버그 예방: NHIS 가 선택 월 무시하고 항상 6월(당월)만 수집하던 버그.
(1) 병렬 풀러밍 누락(별도 수정) + (2) _find_target_row 의 raw 부분문자열 매칭이
포털 날짜 포맷(2026-05-15 / 2026.05 / 2026년05월)과 안 맞아 실패.

_resolve_period(year, month) 가 None 폴백 포함 6자리 YYYYMM 을 올바르게 만드는지,
그리고 _find_target_row 의 숫자정규화 매칭(행 textContent 의 숫자만 추출해 YYYYMM
부분문자열 검사)이 어떤 날짜 포맷에도 동작하는지 검증한다. 라이브 UI 불필요.
"""
import re
from datetime import datetime

from src.automation.nhis._doc_download import _resolve_period


def test_resolve_period_formats_yyyymm():
    assert _resolve_period(2026, 5) == (2026, 5, "202605")
    assert _resolve_period(2026, 12) == (2026, 12, "202612")
    assert _resolve_period(2025, 1) == (2025, 1, "202501")
    assert _resolve_period(2026, 6) == (2026, 6, "202606")


def test_resolve_period_none_falls_back_to_current_month():
    """year/month 미전달(병렬 과거 버그) 시 당월 폴백 — 이 값이 곧 '항상 6월'의 원인이었음."""
    now = datetime.now()
    y, m, yyyymm = _resolve_period(None, None)
    assert (y, m) == (now.year, now.month)
    assert yyyymm == f"{now.year}{now.month:02d}"


def test_resolve_period_only_one_none():
    assert _resolve_period(2026, None)[2].startswith("2026")
    # month=None → 당월. (년도는 전달값 고정)
    assert _resolve_period(2026, None)[0] == 2026


# ── _find_target_row JS 매칭 계약의 Python 미러 ──────────────────────────────
# (매칭은 브라우저 내 JS evaluate 로 일어나 직접 단위테스트 불가 → 동일 규칙을
#  Python 미러로 묘사해 계약을 고정. JS: (row.textContent||'').replace(/\D+/g,'')
#  .indexOf(target) !== -1)
def _digits_match(row_text: str, target_yyyymm: str) -> bool:
    digits = re.sub(r"\D+", "", row_text or "")
    return target_yyyymm in digits


def test_digits_match_handles_all_portal_date_formats():
    """포털 날짜가 어떤 구분자를 써도 YYYYMM(202605) 에 매칭되어야 한다."""
    assert _digits_match("1 2026-05-15 12345 가입자고지(산출)내역서", "202605")
    assert _digits_match("2026.05 가입자고지내역서", "202605")
    assert _digits_match("2026년05월19일", "202605")
    assert _digits_match("2026/05/15", "202605")


def test_digits_match_current_month_june():
    """당월(202606) 행은 기존 동작 회귀 없이 매칭."""
    assert _digits_match("2026-06-19 가입자고지내역서", "202606")
    assert _digits_match("20260619", "202606")


def test_digits_match_negative_for_other_months():
    """다른 월 행에는 매칭되지 않아야 한다(=잘못된 월 수집 방지)."""
    assert not _digits_match("2025-12-31 가입자고지내역서", "202605")
    assert not _digits_match("2026-07-01", "202605")


if __name__ == "__main__":
    for fn in (test_resolve_period_formats_yyyymm,
               test_resolve_period_none_falls_back_to_current_month,
               test_resolve_period_only_one_none,
               test_digits_match_handles_all_portal_date_formats,
               test_digits_match_current_month_june,
               test_digits_match_negative_for_other_months):
        fn()
        print(f"PASS: {fn.__name__}")
    print("\n모든 NHIS 월 매칭 테스트 통과")
