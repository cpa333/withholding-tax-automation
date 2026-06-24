"""병렬(2번) not-found 스킵 + 종합 리포트 회귀 테스트.

공용 emit_summary(src.automation._parallel_report)가 찍는 구조화 마커 계약과
ParallelCliRunner._pump 의 마커 라우팅(마커는 result_summary 로, 일반 로그는
log_message 로)을 검증. 라이브 불필요.

참고: CLI 진입점(nps_auto_cdp/nhis_edi_auto_cdp)은 import 시 sys.stdout.detach()
재래핑을 해 pytest capture 를 망가뜨리므로, 요약 로직은 _parallel_report 에 분리해
여기서 직접 테스트한다.
"""
import io
import json
import contextlib

from src.automation._parallel_report import emit_summary, RESULT_MARKER


def _capture_emit(total, completed, skipped):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        emit_summary(total, completed, skipped)
    return buf.getvalue()


def _marker_payload(out):
    lines = [l for l in out.splitlines() if l.startswith(RESULT_MARKER)]
    assert len(lines) == 1, f"마커 라인이 정확히 1개여야 함: {lines}"
    return json.loads(lines[0][len(RESULT_MARKER):].strip())


def test_marker_constant_consistent_with_worker():
    """공용 마커 상수와 worker 의 _RESULT_MARKER 가 동일해야 함(계약)."""
    from src.ui.workers.parallel_cli_worker import _RESULT_MARKER as worker_marker
    assert RESULT_MARKER == "__WTAX_RESULT__" == worker_marker


def test_emit_summary_marker_schema():
    out = _capture_emit(3, 1, [{"name": "근린건축", "reason": "미발견"}])
    payload = _marker_payload(out)
    assert payload == {
        "total": 3,
        "completed": 1,
        "not_found": [{"name": "근린건축", "reason": "미발견"}],
    }


def test_emit_summary_marker_schema_no_notfound():
    out = _capture_emit(2, 2, [])
    payload = _marker_payload(out)
    assert payload == {"total": 2, "completed": 2, "not_found": []}


def test_emit_summary_detail_excluded_from_marker():
    """detail(오류 메시지 등)은 마커 JSON 의 not_found 항목에서 제외(name/reason 만)."""
    out = _capture_emit(1, 0, [{"name": "X", "reason": "오류", "detail": "boom"}])
    payload = _marker_payload(out)
    assert payload["not_found"] == [{"name": "X", "reason": "오류"}]


class _FakeProc:
    """_pump 테스트용: stdout 을 라인 리스트로 흉내."""
    def __init__(self, lines):
        self.stdout = lines


def test_pump_routes_marker_to_result_summary():
    """마커 라인은 result_summary 로 가고 log_message 에는 나오지 않는다."""
    from PySide6.QtWidgets import QApplication
    from src.ui.workers.parallel_cli_worker import ParallelCliRunner

    app = QApplication.instance() or QApplication([])
    runner = ParallelCliRunner()
    logs, summaries = [], []
    runner.log_message.connect(logs.append)
    runner.result_summary.connect(lambda w, j: summaries.append((w, j)))

    runner._procs["nps"] = _FakeProc([
        "일반 로그\n",
        '__WTAX_RESULT__ {"total":2,"completed":1,"not_found":[{"name":"A","reason":"미발견"}]}\n',
        "또 다른 로그\n",
    ])
    runner._pump("nps")

    # 마커는 log_message 에서 제외
    assert logs == ["[NPS] 일반 로그", "[NPS] 또 다른 로그"]
    # 마커는 result_summary 로 (which, json 문자열)
    assert len(summaries) == 1
    which, payload_json = summaries[0]
    assert which == "nps"
    assert json.loads(payload_json)["not_found"] == [{"name": "A", "reason": "미발견"}]


if __name__ == "__main__":
    for fn in (test_marker_constant_consistent_with_worker,
               test_emit_summary_marker_schema,
               test_emit_summary_marker_schema_no_notfound,
               test_emit_summary_detail_excluded_from_marker,
               test_pump_routes_marker_to_result_summary):
        fn()
        print(f"PASS: {fn.__name__}")
    print("\n모든 병렬 not-found 리포트 테스트 통과")
