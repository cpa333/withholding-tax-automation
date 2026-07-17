"""상태 관리자 — 체크포인트, 재개, 멱등성 보장

각 포털 자동화의 단계별 체크포인트를 관리.
크래시 후 재시작 시 마지막 완료 단계부터 재개.

사용 예:
    sm = StateManager(step_repo)

    # 단계 실행 전 체크포인트
    sm.before_step(job_id, "download_pdf")

    # ... 실제 다운로드 로직 ...

    # 단계 완료 체크포인트
    sm.after_step(job_id, "download_pdf")

    # 재개 지점 확인
    resume_at = sm.get_resume_index(job_id)
"""
from __future__ import annotations

import json
from typing import Optional

from src.batch.db import StepRepository
from src.batch.models import StepStatus


class StateManager:
    """체크포인트 기반 상태 관리

    단계 실행 전/후로 체크포인트를 기록하여:
    1. 크래시 후 마지막 완료 단계 파악
    2. 이미 완료된 단계의 재실행 방지 (멱등성)
    3. 단계별 부가 데이터(예: 다운로드 파일 경로) 저장
    """

    def __init__(self, step_repo: StepRepository) -> None:
        self.step_repo = step_repo

    # ── 체크포인트 ─────────────────────────────────────────────────

    def before_step(self, job_id: int, step_name: str,
                    step_index: int = 0, step_data: dict | None = None) -> None:
        """단계 실행 전 체크포인트

        단계를 'running' 상태로 기록.
        크래시 발생 시 이 상태가 남아있으면 부분 실행으로 판단.

        Args:
            job_id: 잡 ID
            step_name: 단계명 (예: "login", "download_pdf")
            step_index: 실행 순서 (0-based)
            step_data: 단계 부가 데이터
        """
        self.step_repo.mark_running(job_id, step_name, step_data)

    def after_step(self, job_id: int, step_name: str,
                   step_data: dict | None = None) -> None:
        """단계 완료 후 체크포인트

        단계를 'completed' 상태로 변경.
        step_data에 결과(예: 파일 경로, 다운로드 수)를 저장.

        Args:
            job_id: 잡 ID
            step_name: 단계명
            step_data: 단계 결과 데이터
        """
        self.step_repo.mark_completed(job_id, step_name, step_data)

    def fail_step(self, job_id: int, step_name: str,
                  error_message: str = "") -> None:
        """단계 실패 기록

        Args:
            job_id: 잡 ID
            step_name: 단계명
            error_message: 오류 메시지
        """
        self.step_repo.mark_failed(job_id, step_name, error_message)

    # ── 재개 ───────────────────────────────────────────────────────

    def get_resume_index(self, job_id: int) -> int:
        """재개할 단계 인덱스 반환

        마지막으로 완료된 단계의 다음 인덱스.
        완료된 단계가 없으면 0.

        Returns:
            0-based 단계 인덱스
        """
        return self.step_repo.get_resume_index(job_id)

    def get_last_completed_step(self, job_id: int) -> Optional[str]:
        """마지막 완료 단계명 반환

        Returns:
            단계명 또는 None
        """
        step = self.step_repo.get_last_completed(job_id)
        return step.step_name if step else None

    def should_skip_step(self, job_id: int, step_name: str) -> bool:
        """단계를 건너뛰어야 하는지 확인

        이미 완료된 단계면 True 반환 (멱등성 보장).

        Args:
            job_id: 잡 ID
            step_name: 단계명

        Returns:
            True면 이미 완료되어 건너뛰어야 함
        """
        return self.step_repo.is_completed(job_id, step_name)

    # ── 워크플로우 정의 ────────────────────────────────────────────

    def define_workflow(self, job_id: int, steps: list[dict]) -> None:
        """워크플로우 단계 정의

        잡 실행 전에 전체 단계를 미리 등록.
        아직 실행되지 않은 단계는 pending 상태로 생성.

        Args:
            job_id: 잡 ID
            steps: [{"name": "login", "index": 0}, ...] 리스트
        """
        for step_def in steps:
            self.step_repo.create(
                job_id=job_id,
                step_name=step_def["name"],
                step_index=step_def.get("index", 0),
            )

    # ── 부분 실행 감지 ─────────────────────────────────────────────

    def detect_partial_execution(self, job_id: int) -> list[str]:
        """부분 실행된(running 상태) 단계 감지

        크래시 발생 시 running 상태로 남아있는 단계를 찾음.
        이 단계들은 크래시 직전에 실행 중이었음.

        Args:
            job_id: 잡 ID

        Returns:
            부분 실행된 단계명 목록
        """
        all_steps = self.step_repo.list_by_job(job_id)
        return [
            s.step_name for s in all_steps
            if s.status == StepStatus.RUNNING
        ]

    def reset_partial_steps(self, job_id: int) -> int:
        """부분 실행된 단계를 pending으로 리셋

        재시작 시 호출. running 상태의 단계를 pending으로 되돌려
        재실행 가능하게 만듦.

        Args:
            job_id: 잡 ID

        Returns:
            리셋된 단계 수
        """
        partial = self.detect_partial_execution(job_id)
        for step_name in partial:
            self.step_repo.mark_pending(job_id, step_name)
        return len(partial)

    # ── 데이터 조회 ────────────────────────────────────────────────

    def get_step_data(self, job_id: int, step_name: str) -> dict:
        """단계 부가 데이터 조회

        Args:
            job_id: 잡 ID
            step_name: 단계명

        Returns:
            단계 데이터 dict (빈 dict if not found)
        """
        step = self.step_repo.get_step(job_id, step_name)
        if step and step.step_data:
            try:
                return json.loads(step.step_data)
            except (json.JSONDecodeError, TypeError):
                return {}
        return {}

    def get_all_step_data(self, job_id: int) -> dict[str, dict]:
        """잡의 모든 단계 데이터 조회

        Returns:
            {step_name: step_data, ...}
        """
        steps = self.step_repo.list_by_job(job_id)
        result = {}
        for s in steps:
            try:
                result[s.step_name] = json.loads(s.step_data) if s.step_data else {}
            except (json.JSONDecodeError, TypeError):
                result[s.step_name] = {}
        return result


class NoopStateManager:
    """단건 실행용 상태 관리자 (DB 기록 없음)

    메서드가 no-op이며 should_skip_step은 항상 False.
    BatchEngine 없이 단일 수임처만 실행할 때 사용.
    예외: fail_step은 DB 기록이 없으면 실패 사유가 어디에도 남지 않으므로
    사유를 log()로 방출한다(선택건 실행 시 GUI 로그 패널에 표시).
    """

    def before_step(self, job_id, step_name, step_index=0, step_data=None):
        pass

    def after_step(self, job_id, step_name, step_data=None):
        pass

    def fail_step(self, job_id, step_name, error_message=""):
        if error_message:
            from src.utils.log import log
            log(f"  [단계 실패] {step_name}: {error_message}")

    def get_resume_index(self, job_id):
        return 0

    def should_skip_step(self, job_id, step_name):
        return False

    def define_workflow(self, job_id, steps):
        pass

    def detect_partial_execution(self, job_id):
        return []

    def reset_partial_steps(self, job_id):
        return 0
