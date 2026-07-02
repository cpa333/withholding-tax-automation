"""CompanyTableModel.get_all_clients 회귀 테스트.

버그 예방: 병렬 "전체 실행"(ALL)이 firms=None 을 넘겨 CLI 가 포털에서 직접
수임처를 긁어오게 하던 문제(NPS 엉뚱한 사업장 / NHIS 0건 처리). 수정은 전체
실행도 테이블의 모든 수임처에서 firms/mgmts 를 조립(선택건 실행과 동일 경로).
get_all_clients 가 clients_mode 의 전체 행을 _update_selected_clients 와 동일한
dict 형태로 반환하는지 검증한다. 라이브 UI 불필요(모델 단위).
"""
import os

# 헤드리스/CI 환경에서도 QApplication 생성 가능하도록 강제.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from src.ui.widgets.company_table import CompanyTableModel

app = QApplication.instance() or QApplication([])


def _model_with(clients):
    m = CompanyTableModel()
    m.set_clients(clients)
    return m


def test_returns_all_named_clients_with_full_dict_shape():
    """clients_mode 전체 행을 {name,business_number,management_number,enabled} 로 반환."""
    m = _model_with([
        {"id": 1, "name": "서율회계법인", "business_number": "123-45-67890",
         "management_number": "13781663600", "enabled": True},
        {"id": 2, "name": "주식회사더할", "business_number": "20-11-22334",
         "management_number": "", "enabled": False},
    ])
    out = m.get_all_clients()
    assert len(out) == 2
    assert out[0] == {"name": "서율회계법인", "business_number": "123-45-67890",
                      "management_number": "13781663600",
                      "id": 1, "report_cycle": "", "enabled": True}
    # enabled 필드 보존(필터링은 호출측 main_window 책임) — 비활성도 그대로 노출.
    assert out[1]["enabled"] is False
    assert out[1]["management_number"] == ""


def test_empty_when_not_clients_mode():
    """jobs 모드(Phase 2+ 일괄 실행)에서는 빈 리스트 — 전체 실행이 쓰지 않는 안전 장치."""
    m = CompanyTableModel()
    m.set_jobs([{"name": "job", "status": "pending"}])
    assert m.get_all_clients() == []


def test_empty_when_no_clients_loaded():
    """clients_mode 지만 행 없음 → 빈 리스트(main_window 가 빈 목록 가드로 흡수)."""
    m = CompanyTableModel()
    m.set_clients([])
    assert m.get_all_clients() == []


def test_skips_rows_without_name():
    """name 이 빈/없는 행은 건너뛴다(__전체수임처조회__ 등 노이즈 방지)."""
    m = _model_with([
        {"id": 1, "name": "A", "business_number": "", "management_number": "1"},
        {"id": 2, "name": "", "business_number": "", "management_number": ""},
        {"id": 3, "name": "B", "business_number": "1-2-3", "management_number": ""},
    ])
    out = m.get_all_clients()
    assert [c["name"] for c in out] == ["A", "B"]


def test_dict_shape_matches_selected_run_contract():
    """전체 실행(ALL)이 선택건 실행(SELECTED)과 동일 downstream 계약을 갖도록,
    get_all_clients 의 키가 _update_selected_clients 가 만드는 dict 의 상위집합
    (name/business_number/management_number)임을 보장. enabled 는 ALL 필터용 추가."""
    m = _model_with([{"name": "X", "business_number": "b", "management_number": "m"}])
    out = m.get_all_clients()
    keys = set(out[0].keys())
    assert {"name", "business_number", "management_number"}.issubset(keys)


if __name__ == "__main__":
    for fn in (test_returns_all_named_clients_with_full_dict_shape,
               test_empty_when_not_clients_mode, test_empty_when_no_clients_loaded,
               test_skips_rows_without_name, test_dict_shape_matches_selected_run_contract):
        fn()
        print(f"PASS: {fn.__name__}")
    print("\n모든 get_all_clients 테스트 통과")
