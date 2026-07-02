"""SWTA(원천징수이행상황신고서) 반기/매월 기간 로직 단위 테스트.

compute_half_period: 반기 신고의 (연도, 시작월, 종료월)을 실행일 기준으로 반환.
  - 7~12월 실행 → 당해 1~6월 (상반기, 7월에 신고)
  - 1~6월 실행 → 전년 7~12월 (하반기, 1월에 신고)
"""
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.automation.wehago.run_swta0101 import compute_half_period


def _dt(y, m):
    return datetime(y, m, 1)


def test_half_period_july_returns_current_year_first_half():
    # 7월(초) 실행 → 당해 1~6월 (상반기)
    assert compute_half_period(_dt(2026, 7)) == (2026, 1, 6)


def test_half_period_december_returns_current_year_first_half():
    # 12월 실행 → 여전히 당해 상반기(가장 최근 완료 반기)
    assert compute_half_period(_dt(2026, 12)) == (2026, 1, 6)


def test_half_period_january_returns_previous_year_second_half():
    # 1월(초) 실행 → 전년 7~12월 (하반기)
    assert compute_half_period(_dt(2026, 1)) == (2025, 7, 12)


def test_half_period_june_returns_previous_year_second_half():
    # 6월 실행 → 전년 하반기(가장 최근 완료 반기)
    assert compute_half_period(_dt(2026, 6)) == (2025, 7, 12)


def test_half_period_year_boundary():
    # 2027년 1월 → 2026년 7~12월
    assert compute_half_period(_dt(2027, 1)) == (2026, 7, 12)


def test_half_period_all_months_consistency():
    # 상/하반기 경계(6월↔7월) 일관성
    assert compute_half_period(_dt(2026, 6))[1:] == (7, 12)
    assert compute_half_period(_dt(2026, 7))[1:] == (1, 6)


if __name__ == "__main__":
    for fn in (
        test_half_period_july_returns_current_year_first_half,
        test_half_period_december_returns_current_year_first_half,
        test_half_period_january_returns_previous_year_second_half,
        test_half_period_june_returns_previous_year_second_half,
        test_half_period_year_boundary,
        test_half_period_all_months_consistency,
    ):
        fn()
        print(f"PASS: {fn.__name__}")
    print("\n모든 반기 기간 테스트 통과")
