"""NPS _find_workplace_row_by_mgmt 관리번호 매칭 회귀 테스트.

버그 예방: NPS select_workplace 관리번호 경로가 검색 후 row=0(첫 행)을 무조건
더블클릭하던 NHIS 동일 버그 부류(→ 항상 첫 사업장 것만 가져옴). 수정은
관리번호가 정확히 일치하는 행만 선택. _find_workplace_row_by_mgmt 가 그리드에서
일치 행을 정확히 찾는지 검증한다. nexacro_get_grid_data 를 가짜 그리드로 mock —
라이브(Nexacro) 불필요, NHIS 회귀테스트(test_nhis_firm_selector_mgmt_match.py)와 대칭.
"""
import asyncio
from unittest.mock import patch, AsyncMock

import src.automation.nps._workplace as wp

# 가짜 NPS 사업장 그리드: [순번(col0), 사업장관리번호(col1), 사업장명(col2)]
# col 매핑은 list_workplaces 가 입증(col1=number, col2=name).
GRID = [
    ["1", "13781663600", "서율회계법인"],
    ["2", "69588014640", "주식회사더할"],
    ["3", "36088016460", "주식회사도담"],
]


def _find(mgmt):
    with patch.object(wp, "nexacro_get_grid_data", new=AsyncMock(return_value=GRID)):
        return asyncio.run(wp._find_workplace_row_by_mgmt(None, mgmt))


def test_picks_non_first_row_by_mgmt():
    """관리번호 69588014640 → 첫 행(서율회계법인, row=0)이 아닌 row=1 선택."""
    found = _find("69588014640")
    assert found is not None
    row, name = found
    assert row == 1
    assert name == "주식회사더할"
    assert name != "서율회계법인"   # ★ 핵심: 첫 사업장이 아니어야 함


def test_no_match_returns_none():
    """존재하지 않는 관리번호 → None(이름 fallback 유도)."""
    assert _find("99999999999") is None


def test_digit_normalization_ignores_hyphen():
    """'360-8801-6460' → 숫자만 비교해 36088016460(row=2)와 일치."""
    found = _find("360-8801-6460")
    assert found is not None
    row, name = found
    assert row == 2
    assert name == "주식회사도담"


def test_empty_mgmt_returns_none():
    """빈/None 관리번호 → None(이름 경로로 바로 가도록)."""
    assert _find("") is None
    assert _find(None) is None


def test_first_row_when_mgmt_matches_first():
    """관리번호 13781663600 → 첫 행(서율회계법인) 정상 선택(정상 케이스)."""
    found = _find("13781663600")
    assert found is not None
    assert found[0] == 0
    assert found[1] == "서율회계법인"


if __name__ == "__main__":
    for fn in (test_picks_non_first_row_by_mgmt, test_no_match_returns_none,
               test_digit_normalization_ignores_hyphen, test_empty_mgmt_returns_none,
               test_first_row_when_mgmt_matches_first):
        fn()
        print(f"PASS: {fn.__name__}")
    print("\n모든 _find_workplace_row_by_mgmt 테스트 통과")
