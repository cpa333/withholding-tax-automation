"""병렬 CLI 배치 공용 종료 요약 — 사람용 블록(log) + 구조화 마커(stdout).

NPS/NHIS 양쪽 run_auto_batch 가 공유. ParallelCliRunner._pump 가 __WTAX_RESULT__
마커 라인을 가로채 result_summary 시그널로 변환한다(로그 패널엔 raw JSON 미출력).

별도 모듈로 뺀 이유: CLI 진입점(nps_auto_cdp/nhis_edi_auto_cdp)은 import 시
sys.stdout.detach() 재래핑을 수행해 pytest capture 를 망가뜨린다. 요약 로직만
분리해 테스트 가능하고 DRY 하게 유지.
"""
import json

from src.utils.log import log

# ParallelCliRunner._RESULT_MARKER 와 동일해야 함.
RESULT_MARKER = "__WTAX_RESULT__"


def emit_summary(total, completed, skipped):
    """배치 종료 요약 출력.

    skipped: [{"name": str, "reason": str, "detail"?: str}, ...]
    reason 은 "오픈실패" / "미발견" / "오류". 사람용 블록은 log() 로 패널에 항상
    표시되고, 구조화 마커는 stdout 으로 나가 worker 가 result_summary 로 변환한다.
    not_found 항목은 name/reason 만(detail 제외).
    """
    log("\n" + "=" * 55)
    log(f"  결과 요약: 총 {total} / 완료 {completed} / 처리못함 {len(skipped)}")
    for s in skipped:
        detail = f" ({s['detail']})" if s.get("detail") else ""
        log(f"    - {s['name']} [{s['reason']}]{detail}")
    log("=" * 55)
    payload = {
        "total": total,
        "completed": completed,
        "not_found": [{"name": s["name"], "reason": s["reason"]} for s in skipped],
    }
    print(f"{RESULT_MARKER} {json.dumps(payload, ensure_ascii=False)}", flush=True)
