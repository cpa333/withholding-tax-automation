"""BatchEngine 회귀 테스트 — Wave 3(engine↔runner 통합)의 기준선.

목적: engine.run()/_run_job 이 현재 프로덕션에서는 호출되지 않지만,
Wave 3 에서 runner가 engine.run()을 호출하게 만들 때 이 동작이 보존되어야 함.
특히 (1) 완료/실패 전이, (2) 예외 시 traceback DB 저장,
(3) 부분 실행(partial) 단계 리셋 — 크래시 복구의 절반.
"""
import asyncio

from src.batch.db import BatchDB, StepRepository
from src.batch.models import BatchStatus, JobStatus


def _run(coro):
    return asyncio.run(coro)


def test_prepare_batch_enqueues_active_clients(engine_with_jobs):
    engine, batch = engine_with_jobs
    assert batch.status == BatchStatus.CREATED
    counts = engine.job_repo.count_by_status(batch.id)
    assert counts.get("pending", 0) == 2          # 시드한 활성 수임처 2명
    # total_clients 는 update_total_clients 로 DB 에 기록됨.
    # (주의: prepare_batch 반환 객체는 갱신 전 스냅샷이라 stale — DB 재조회 필요)
    refreshed = engine.batch_repo.get(batch.id)
    assert refreshed.total_clients == 2


def test_run_completes_all_jobs_when_workflow_succeeds(engine_with_jobs):
    engine, batch = engine_with_jobs

    async def wf(page, context, job, state, *, management_number):
        return True

    result = _run(engine.run(wf))
    assert result.status == BatchStatus.COMPLETED
    counts = engine.job_repo.count_by_status(batch.id)
    assert counts.get("completed") == 2
    assert counts.get("failed", 0) == 0
    assert counts.get("pending", 0) == 0


def test_run_marks_failed_when_workflow_returns_false(engine_with_jobs):
    engine, batch = engine_with_jobs

    async def wf(page, context, job, state, *, management_number):
        return False

    result = _run(engine.run(wf))
    # pending==0 이므로 all_done → COMPLETED (잡 자체는 failed)
    assert result.status == BatchStatus.COMPLETED
    counts = engine.job_repo.count_by_status(batch.id)
    assert counts.get("failed") == 2
    assert counts.get("completed", 0) == 0


def test_run_records_traceback_on_exception(engine_with_jobs):
    """Wave 3 복원 대상: 예외 시 error_traceback 이 DB 에 저장되는지."""
    engine, batch = engine_with_jobs

    async def wf(page, context, job, state, *, management_number):
        raise RuntimeError("boom-unique-marker")

    _run(engine.run(wf))
    failed = engine.job_repo.list_failed(batch.id)
    assert len(failed) == 2
    for job in failed:
        assert job.status == JobStatus.FAILED
        assert "boom-unique-marker" in (job.error_message or "")
        assert job.error_traceback, "traceback 이 DB 에 저장되어야 함"
        assert "Traceback" in job.error_traceback


def test_run_resets_partial_execution_steps(engine_with_jobs, db_path):
    """Wave 3 복원 대상: 크래시 직전 running 단계가 _run_job 에서 pending 리셋되는지."""
    engine, batch = engine_with_jobs

    # 크래시 직전 상태 시뮬: 첫 pending 잡의 단계를 running 으로 남김
    job = engine.job_repo.get_next_pending(batch.id)
    with BatchDB(db_path) as db:
        StepRepository(db).mark_running(job.id, "download_pdf")

    async def wf(page, context, job, state, *, management_number):
        # _run_job 이 reset_partial_steps 를 호출했다면 running 단계는 더 없음
        assert state.detect_partial_execution(job.id) == []
        return True

    _run(engine.run(wf))


def test_get_progress_reports_counts(engine_with_jobs):
    engine, batch = engine_with_jobs

    async def wf(page, context, job, state, *, management_number):
        return True

    _run(engine.run(wf))
    progress = engine.get_progress(batch.id)
    assert progress["status"] == BatchStatus.COMPLETED
    assert progress["completed"] == 2
    assert progress["total"] == 2
