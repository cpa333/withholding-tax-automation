"""SWTA(원천징수이행상황신고서) 반기/매월 기간 로직 단위 테스트.

compute_half_period: 반기 신고의 (연도, 시작월, 종료월)을 실행일 기준으로 반환.
  - 7~12월 실행 → 당해 1~6월 (상반기, 7월에 신고)
  - 1~6월 실행 → 전년 7~12월 (하반기, 1월에 신고)
"""
import asyncio
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.automation.wehago.run_swta0101 import compute_half_period
from src.automation.wehago._common import get_report_period_type


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


# ═══════════════════════════════════════════════════════════════════════
# get_report_period_type: 라디오 정착(settle) 폴링 로직
#   매월 = "반기가 체크 안 됨"이라는 부정형 신호이므로, 정착 창 동안 폴링하여
#   반기가 관측되면 즉시 확정, 끝내 관측 안 되면 매월 확정한다.
#   (프로젝트에 pytest-asyncio 가 없어 asyncio.run 으로 구동)
# ═══════════════════════════════════════════════════════════════════════

class _FakeRadioPage:
    """라디오 읽기를 시뮬레이션. evaluate() 호출마다 states 시퀀스의 다음 값을 반환."""

    def __init__(self, states, has_selector=True):
        self._states = states
        self._i = 0
        self._has_selector = has_selector

    async def wait_for_selector(self, selector, timeout=None):
        if not self._has_selector:
            raise TimeoutError("selector not found")

    async def evaluate(self, expr):
        if not self._states:
            return None
        v = self._states[min(self._i, len(self._states) - 1)]
        self._i += 1
        return v


def test_period_type_half_detected_after_settle():
    # 처음엔 매월(과도기)으로 읽히다가 반기 체크로 전환 → 반기 확정.
    # 이전 구현이라면 첫 읽기(매월)로 오판했을 것(버그 시나리오).
    page = _FakeRadioPage(["매월", "매월", "반기", "반기"])
    result = asyncio.run(get_report_period_type(page, settle_seconds=0.3, interval=0.05))
    assert result == "반기"


def test_period_type_monthly_when_never_half():
    # 정착 창 내내 반기 미관측 → 매월 확정
    page = _FakeRadioPage(["매월"] * 20)
    result = asyncio.run(get_report_period_type(page, settle_seconds=0.2, interval=0.05))
    assert result == "매월"


def test_period_type_none_when_radio_missing():
    # 라디오 자체가 안 뜨면(미로드) None → 상층 매월 폴백, 역충전 안 함
    page = _FakeRadioPage([], has_selector=False)
    result = asyncio.run(get_report_period_type(page, settle_seconds=0.2, interval=0.05))
    assert result is None


def test_period_type_none_when_unknown():
    # 라디오는 있으나 라벨/value 인식 불가 → None(판별 불가)
    page = _FakeRadioPage(["unknown"] * 20)
    result = asyncio.run(get_report_period_type(page, settle_seconds=0.2, interval=0.05))
    assert result is None


if __name__ == "__main__":
    for fn in (
        test_half_period_july_returns_current_year_first_half,
        test_half_period_december_returns_current_year_first_half,
        test_half_period_january_returns_previous_year_second_half,
        test_half_period_june_returns_previous_year_second_half,
        test_half_period_year_boundary,
        test_half_period_all_months_consistency,
        test_period_type_half_detected_after_settle,
        test_period_type_monthly_when_never_half,
        test_period_type_none_when_radio_missing,
        test_period_type_none_when_unknown,
    ):
        fn()
        print(f"PASS: {fn.__name__}")
    print("\n모든 SWTA 주기 판별 테스트 통과")
