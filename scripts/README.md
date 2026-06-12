# scripts/ — 개발/디버깅 참고 스크립트

이 디렉토리의 스크립트는 프로덕션 코드가 아닙니다.
SWSA0101 기능 개발 중 작성된 분석/테스트 스크립트로, 향후 디버깅 시 참고용으로 보관합니다.

## SWSA0101 귀속연월(React LS_calendar) 분석 스크립트

| 파일 | 용도 |
|------|------|
| `analyze_fakeinput.py` ~ `analyze_fakeinput_v7.py` | 귀속연월 fakeinput DOM 구조 분석 (v1→v7 반복 개선) |
| `cdp_swsa0101_calendar.py` | React LS_calendar 컴포넌트 구조 탐색 |
| `cdp_swsa0101_date_inspect.py` | 날짜 관련 DOM 엘리먼트 상세 검사 |
| `cdp_swsa0101_e2e.py` | 전체 플로우 E2E 테스트 (엑셀 다운로드→업로드) |
| `cdp_swsa0101_set_date.py` | React setState로 연도 변경 검증 (프로덕션 코드의 원천) |

## E2E 테스트 스크립트

| 파일 | 용도 |
|------|------|
| `e2e_set_swsa_ym.py` | `set_swsa_ym()` 함수 동일 연도 월 변경 + 복원 테스트 |
| `e2e_set_swsa_ym_cross_year.py` | `set_swsa_ym()` 연도 변경(cross-year) + 복원 + 월 변경 테스트 |

## 실행 방법

모든 스크립트는 Chrome CDP(port 9223) 실행 후, 프로젝트 루트에서 실행:

```bash
python scripts/e2e_set_swsa_ym.py
```

## 참고

- 프로덕션 코드: `src/automation/wehago/run_swsa0101.py`, `src/automation/wehago/_common.py`
- `cdp_swsa0101_set_date.py`의 React setState JS가 `run_swsa0101.py`의 `_REACT_SET_CALENDAR_YEAR_JS`로 통합됨
