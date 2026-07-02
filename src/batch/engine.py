"""배치 엔진 오케스트레이터

포털별 자동화 워크플로우를 순차 실행하고,
SQLite에 상태를 기록하여 크래시 복구를 지원.

Usage:
    engine = BatchEngine("batch.db", portal="wehago")
    engine.initialize()
    engine.run(workflow_func=my_workflow)
"""
from __future__ import annotations

import os
import traceback
from datetime import datetime
from typing import Callable, Optional, Awaitable

from src.batch.models import (
    Batch, BatchStatus, Client, Job, JobStatus, Portal,
    get_management_number, make_batch_key, now_iso,
)
from src.batch.db import (
    BatchDB, BatchRepository, ClientRepository, JobRepository, StepRepository,
)
from src.batch.state import StateManager


# 워크플로우 함수 타입: (page, context, job, state_manager) -> bool
WorkflowFunc = Callable[..., Awaitable[bool]]


class BatchEngine:
    """배치 자동화 메인 오케스트레이터

    책임:
    1. 월간 배치 생성/관리
    2. 수임처 목록을 잡 큐에 등록
    3. 순차 실행 + 상태 추적
    4. 크래시 감지 및 복구
    5. 결과 리포트 생성

    특징:
    - 단일 스레드 asyncio에서만 동작
    - SQLite WAL 모드로 일관성 보장
    - 잡 단위 체크포인트로 크래시 복구
    """

    def __init__(self, db_path: str, portal: str) -> None:
        """
        Args:
            db_path: SQLite 데이터베이스 파일 경로
            portal: Portal enum value ("wehago", "nhis_edi", ...)
        """
        self.portal = portal
        self.db = BatchDB(db_path)

        # 저장소
        self._batch_repo: Optional[BatchRepository] = None
        self._client_repo: Optional[ClientRepository] = None
        self._job_repo: Optional[JobRepository] = None
        self._step_repo: Optional[StepRepository] = None
        self._state: Optional[StateManager] = None

        # 현재 배치
        self._current_batch: Optional[Batch] = None

    # ── 초기화 ─────────────────────────────────────────────────────

    def initialize(self) -> None:
        """엔진 초기화: DB 연결, 크래시 복구, 배치 준비"""
        self.db.connect()

        self._batch_repo = BatchRepository(self.db)
        self._client_repo = ClientRepository(self.db)
        self._job_repo = JobRepository(self.db)
        self._step_repo = StepRepository(self.db)
        self._state = StateManager(self._step_repo)

        # 크래시 복구: 이전 실행이 비정상 종료되었는지 확인
        crashed = self._batch_repo.mark_crashed_as_recoverable()
        if crashed:
            portal_names = [b.portal for b in crashed]
            print(f"  크래시 배치 감지: {portal_names}")

    def close(self) -> None:
        """엔진 종료"""
        self.db.close()

    @property
    def batch_repo(self) -> BatchRepository:
        assert self._batch_repo is not None
        return self._batch_repo

    @property
    def client_repo(self) -> ClientRepository:
        assert self._client_repo is not None
        return self._client_repo

    @property
    def job_repo(self) -> JobRepository:
        assert self._job_repo is not None
        return self._job_repo

    @property
    def step_repo(self) -> StepRepository:
        assert self._step_repo is not None
        return self._step_repo

    @property
    def state(self) -> StateManager:
        assert self._state is not None
        return self._state

    @property
    def current_batch(self) -> Optional[Batch]:
        return self._current_batch

    # ── 배치 관리 ──────────────────────────────────────────────────

    def prepare_batch(self, year: int | None = None,
                      month: int | None = None) -> Batch:
        """월간 배치 준비

        1. 이전 완료 배치 archived 처리
        2. 새 배치 생성 또는 기존 크래시/created 배치 재사용
        3. 활성 수임처를 잡 큐에 등록

        Args:
            year: 대상 연도 (기본: 현재 년도)
            month: 대상 월 (기본: 이전 월)

        Returns:
            준비된 Batch 객체
        """
        now = datetime.now()
        if year is None:
            year = now.year
        if month is None:
            month = now.month - 1 if now.month > 1 else 12
            if now.month == 1:
                year = now.year - 1

        # 이전 완료 배치 archived
        self.batch_repo.archive_completed(self.portal)

        # 활성 수임처 조회
        clients = self.client_repo.list_active(self.portal)
        if not clients:
            print(f"  경고: {self.portal}에 등록된 활성 수임처가 없습니다.")

        # 배치 생성 또는 재사용
        batch = self.batch_repo.create(self.portal, year, month)

        # 상태에 따라 처리
        if batch.status == BatchStatus.CRASHED:
            print(f"  크래시 배치 복구: {batch.batch_key}")
            # 실패한 잡 재시도 대기로 변경
            retried = self.job_repo.enqueue_failed_for_retry(batch.id)
            if retried:
                print(f"  {retried}개 잡 재시도 대기로 변경")
        elif batch.status == BatchStatus.CREATED:
            # 잡 큐에 수임처 등록
            enqueued = self.job_repo.enqueue_all(batch.id, clients)
            total = self.job_repo.count_by_status(batch.id)
            self.batch_repo.update_total_clients(
                batch.id, sum(total.values())
            )
            if enqueued:
                print(f"  {enqueued}개 수임처 등록")
        elif batch.status == BatchStatus.COMPLETED:
            print(f"  이미 완료된 배치: {batch.batch_key}")
        elif batch.status in (BatchStatus.RUNNING, BatchStatus.PAUSED):
            # 계속 진행
            pass

        self._current_batch = batch
        return batch

    # ── 실행 ───────────────────────────────────────────────────────

    async def run(self, workflow_func: WorkflowFunc, *,
                  page=None, context=None) -> Batch:
        """배치 실행 메인 루프

        대기 중인 잡을 순차적으로 가져와 workflow_func에 전달.
        각 잡의 성공/실패를 기록하고 다음 잡으로 진행.

        Args:
            workflow_func: 비동기 워크플로우 함수
                시그니처: async def my_workflow(page, context, job, state_manager) -> bool
            page: Playwright page 객체
            context: Playwright browser context

        Returns:
            완료된 Batch 객체
        """
        batch = self._current_batch
        if not batch:
            raise RuntimeError("prepare_batch()을 먼저 호출하세요")

        if batch.status in (BatchStatus.COMPLETED, BatchStatus.ARCHIVED):
            print(f"  배치가 이미 {batch.status} 상태입니다.")
            return batch

        # 배치를 running 상태로
        self.batch_repo.update_status(batch.id, BatchStatus.RUNNING)

        print(f"\n{'='*55}")
        print(f"  배치 시작: {batch.batch_key}")
        print(f"  포털: {self.portal}")
        print(f"{'='*55}\n")

        try:
            while True:
                job = self.job_repo.get_next_pending(batch.id)
                if not job:
                    break

                await self._run_job(
                    job, workflow_func,
                    page=page or (context.pages[0] if context and context.pages else None),
                    context=context,
                )

        except KeyboardInterrupt:
            print("\n  사용자 중단 (Ctrl+C). 배치를 paused 상태로 저장합니다.")
            self.batch_repo.update_status(batch.id, BatchStatus.PAUSED)
            return batch

        # 완료 확인
        counts = self.job_repo.count_by_status(batch.id)
        all_done = counts.get("pending", 0) == 0 and counts.get("running", 0) == 0

        if all_done:
            self.batch_repo.update_status(batch.id, BatchStatus.COMPLETED)
            batch = self.batch_repo.get(batch.id)
            print(f"\n{'='*55}")
            print(f"  배치 완료: {batch.batch_key}")
            print(f"  완료: {batch.completed_count} / 실패: {batch.failed_count} / 건너뜀: {batch.skipped_count}")
            print(f"{'='*55}")
        else:
            self.batch_repo.update_status(batch.id, BatchStatus.PAUSED)

        return self.batch_repo.get(batch.id)

    async def _run_job(self, job: Job, workflow_func: WorkflowFunc,
                       page=None, context=None) -> None:
        """단일 잡 실행"""
        self.job_repo.mark_running(job.id)

        # 사업장관리번호(override 우선) + 사업자등록번호 + 신고주기 조회
        mgmt_no = ""
        biz_no = ""
        report_cycle = ""
        if job.client_id:
            client = self.client_repo.get(job.client_id)
            if client:
                mgmt_no = get_management_number(client)
                biz_no = client.business_number or ""
                report_cycle = client.report_cycle or ""

        print(f"\n{'─'*55}")
        print(f"  [{job.client_name}] 처리 시작")
        if mgmt_no:
            print(f"  사업장관리번호: {mgmt_no}")
        print(f"  잡 ID: {job.id}, 재시도: {job.retry_count}")
        print(f"{'─'*55}")

        # 부분 실행된 단계 리셋
        partial = self.state.detect_partial_execution(job.id)
        if partial:
            print(f"  부분 실행 단계 감지: {partial}")
            self.state.reset_partial_steps(job.id)

        try:
            success = await workflow_func(
                page, context, job, self.state,
                management_number=mgmt_no,
                business_number=biz_no,
                report_cycle=report_cycle,
                client_id=job.client_id,
            )

            if success:
                self.job_repo.mark_completed(job.id)
                print(f"  [{job.client_name}] 완료")
            else:
                self.job_repo.mark_failed(job.id, "워크플로우 False 반환")
                print(f"  [{job.client_name}] 실패 (워크플로우 False 반환)")

        except Exception as e:
            tb = traceback.format_exc()
            err_msg = f"{type(e).__name__}: {e}"
            print(f"  [{job.client_name}] 예외 발생: {err_msg}")
            print(tb)
            self.job_repo.mark_failed(job.id, err_msg, tb)

    # ── 재시도 ─────────────────────────────────────────────────────

    def retry_failed(self, batch_id: int | None = None) -> int:
        """실패한 잡을 재시도 대기로 변경

        Args:
            batch_id: 배치 ID (기본: 현재 배치)

        Returns:
            재시도 대기로 변경된 잡 수
        """
        bid = batch_id or (self._current_batch.id if self._current_batch else None)
        if not bid:
            raise RuntimeError("배치 ID가 필요합니다")
        return self.job_repo.enqueue_failed_for_retry(bid)

    # ── 리포트 ─────────────────────────────────────────────────────

    def get_progress(self, batch_id: int | None = None) -> dict:
        """배치 진행 상황 반환"""
        bid = batch_id or (self._current_batch.id if self._current_batch else None)
        if not bid:
            return {}

        batch = self.batch_repo.get(bid)
        if not batch:
            return {}

        counts = self.job_repo.count_by_status(bid)
        total = sum(counts.values())

        return {
            "batch_key": batch.batch_key,
            "portal": batch.portal,
            "status": batch.status,
            "total": total,
            "completed": counts.get("completed", 0),
            "failed": counts.get("failed", 0),
            "skipped": counts.get("skipped", 0),
            "pending": counts.get("pending", 0),
            "running": counts.get("running", 0),
            "started_at": batch.started_at,
            "completed_at": batch.completed_at,
        }

    def get_failed_jobs(self, batch_id: int | None = None) -> list[Job]:
        """실패한 잡 목록 반환"""
        bid = batch_id or (self._current_batch.id if self._current_batch else None)
        if not bid:
            return []
        return self.job_repo.list_failed(bid)

    # ── 컨텍스트 매니저 ───────────────────────────────────────────

    async def __aenter__(self) -> "BatchEngine":
        self.initialize()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()
