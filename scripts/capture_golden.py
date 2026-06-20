"""골든 스냅샷 캡처/비교 — 리팩토링 회귀 검증용 기준선.

배경
----
tests/ 가 없어 구조 통합(Wave 3 등)의 회귀를 자동으로 검증할 수단이 없다.
실제 자동화 dry-run(로그인/브라우저 필요)은 이 스크립트 밖에서 수행하고,
이 스크립트는 생성된 배치 DB 상태를 정규화된 JSON 으로 캡처/비교한다.

사용 흐름
---------
1. 기준선 캡처 (리팩토링 전):
     python scripts/capture_golden.py capture --db <DB_PATH> --label baseline --out tests/golden
2. 각 Wave 후 동일 dry-run 재실행 → 재캡처:
     python scripts/capture_golden.py capture --db <DB_PATH> --label wave3 --out tests/golden
3. 기준선과 비교 (상태 전이/단계 시퀀스 회귀 확인):
     python scripts/capture_golden.py compare --base tests/golden/baseline.json \
         --curr tests/golden/wave3.json

정규화
------
타임스탬프(*_at), duration_secs 등 휘발성 컬럼은 "<volatile>" 로 치환해
실행 시각 차이가 diff 를 만들지 않도록 한다. status/step_name/step_index/
retry_count 등 구조적 값은 그대로 둔다.

주의: 본 스크립트는 DB 상태만 다룬다. log() 출력 캡처는 GUI 로그 패널 또는
stdout 리다이렉트로 별도 수집해 tests/golden/<label>.log 로 보관할 것.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 회귀 비교에서 무시할 휘발성 컬럼(실행 시각/소요시간 등)
_VOLATILE_COLS = {"started_at", "completed_at", "created_at", "updated_at", "duration_secs"}
_VOLATILE_PLACEHOLDER = "<volatile>"


def _normalize_rows(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        nr = {}
        for k, v in r.items():
            nr[k] = _VOLATILE_PLACEHOLDER if k in _VOLATILE_COLS else v
        out.append(nr)
    return out


def snapshot(db_path: str) -> dict:
    """배치 DB 의 batches/jobs/steps/clients 행을 정규화해 반환."""
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"DB 파일이 없습니다: {db_path}")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        data = {}
        for tbl in ("batches", "jobs", "steps", "clients"):
            try:
                rows = conn.execute(f"SELECT * FROM {tbl} ORDER BY id").fetchall()
            except sqlite3.Error:
                rows = []
            data[tbl] = _normalize_rows([dict(r) for r in rows])
        return data
    finally:
        conn.close()


def capture(db_path: str, label: str, out_dir: str) -> str:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    data = snapshot(db_path)
    data["_meta"] = {"label": label}
    path = out / f"{label}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"캡처 완료: {path}")
    for tbl in ("batches", "jobs", "steps", "clients"):
        print(f"  {tbl}: {len(data[tbl])}행")
    return str(path)


def _summary(data: dict) -> dict:
    """회귀 비교용 요약 — 테이블별 행수 + jobs/steps 상태 분포."""
    from collections import Counter
    s = {tbl: len(data.get(tbl, [])) for tbl in ("batches", "jobs", "steps", "clients")}
    job_status = Counter(r.get("status") for r in data.get("jobs", []))
    step_status = Counter(r.get("status") for r in data.get("steps", []))
    s["jobs_by_status"] = dict(job_status)
    s["steps_by_status"] = dict(step_status)
    return s


def compare(base_path: str, curr_path: str) -> int:
    base = json.loads(Path(base_path).read_text(encoding="utf-8"))
    curr = json.loads(Path(curr_path).read_text(encoding="utf-8"))
    sb, sc = _summary(base), _summary(curr)

    print(f"기준선: {base_path}")
    print(f"현재  : {curr_path}\n")
    diffs = 0
    for key in ("batches", "jobs", "steps", "clients", "jobs_by_status", "steps_by_status"):
        if sb.get(key) != sc.get(key):
            diffs += 1
            print(f"  [변경] {key}: {sb.get(key)} -> {sc.get(key)}")
        else:
            print(f"  [동일] {key}: {sb.get(key)}")

    # 행 단위 정밀 diff(jobs/steps)
    for tbl in ("jobs", "steps"):
        b = {r["id"]: r for r in base.get(tbl, []) if "id" in r}
        c = {r["id"]: r for r in curr.get(tbl, []) if "id" in r}
        only_base = set(b) - set(c)
        only_curr = set(c) - set(b)
        for rid in sorted(only_base):
            diffs += 1
            print(f"  [제거] {tbl} id={rid}")
        for rid in sorted(only_curr):
            diffs += 1
            print(f"  [추가] {tbl} id={rid}")
        for rid in sorted(set(b) & set(c)):
            if b[rid] != c[rid]:
                diffs += 1
                changed = [k for k in b[rid] if b[rid].get(k) != c[rid].get(k)]
                print(f"  [행 변경] {tbl} id={rid} 필드={changed}")

    print(f"\n총 차이: {diffs}")
    return 0 if diffs == 0 else 1


def main() -> int:
    p = argparse.ArgumentParser(description="골든 스냅샷 캡처/비교")
    sub = p.add_subparsers(dest="cmd", required=True)

    cap = sub.add_parser("capture", help="DB 상태를 JSON 으로 캡처")
    cap.add_argument("--db", required=True, help="배치 DB 경로")
    cap.add_argument("--label", required=True, help="스냅샷 라벨(예: baseline, wave3)")
    cap.add_argument("--out", default="tests/golden", help="출력 디렉토리")

    cmp = sub.add_parser("compare", help="두 스냅샷 비교")
    cmp.add_argument("--base", required=True, help="기준선 JSON")
    cmp.add_argument("--curr", required=True, help="현재 JSON")

    args = p.parse_args()
    if args.cmd == "capture":
        capture(args.db, args.label, args.out)
        return 0
    if args.cmd == "compare":
        return compare(args.base, args.curr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
