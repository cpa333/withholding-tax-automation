"""배치 엔진 데이터 모델

배치 실행 상태, 작업, 단계, 수임처 정보를 표현하는 dataclass.
SQLite 행과 1:1 매핑.
"""
from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


# ═══════════════════════════════════════════════════════════════════════
# Enum
# ═══════════════════════════════════════════════════════════════════════

class Portal(str, enum.Enum):
    """자동화 포털 구분"""
    WEHAGO = "wehago"
    NHIS_EDI = "nhis_edi"
    NPS_EDI = "nps_edi"
    HOMETAX = "hometax"

    @property
    def display_name(self) -> str:
        names = {
            "wehago": "WEHAGO",
            "nhis_edi": "국민건강보험 EDI",
            "nps_edi": "국민연금 EDI",
            "hometax": "홈택스",
        }
        return names.get(self.value, self.value)


class BatchStatus(str, enum.Enum):
    """배치 실행 상태

    상태 전이:
        created -> running -> completed
                   |  |
                   |  +-> paused -> running (재개)
                   |
                   +-> crashed  (비정상 종료, 재시작 시 자동 감지)

        completed -> archived (다음 월 배치 생성 시)
    """
    CREATED = "created"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    ARCHIVED = "archived"
    CRASHED = "crashed"


class JobStatus(str, enum.Enum):
    """개별 수임처 작업 상태

    상태 전이:
        pending -> running -> completed
                         |  +-> failed  (오류, 재시도 가능)
                         |  +-> skipped (건너뜀)
                         +-> skipped
    """
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class StepStatus(str, enum.Enum):
    """작업 내 개별 단계 상태

    상태 전이:
        pending -> running -> completed
                         +-> failed
    """
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


# ═══════════════════════════════════════════════════════════════════════
# Dataclass
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class Client:
    """수임처 등록 정보

    수임처 마스터 테이블. 포털별로 별도 등록.
    enabled=False이면 배치에서 제외.
    priority가 낮을수록 먼저 처리.
    """
    id: Optional[int] = None
    name: str = ""
    portal: str = ""                # Portal enum value
    business_number: str = ""       # 사업자등록번호 (선택)
    enabled: bool = True
    priority: int = 100             # 정렬 우선순위 (낮을수록 우선)
    notes: str = ""                 # 메모
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


@dataclass
class Batch:
    """배치 실행 단위

    월 1회 생성. 포털별로 별도 배치.
    예: 2026-05 WEHAGO 배치, 2026-05 NHIS EDI 배치.
    """
    id: Optional[int] = None
    batch_key: str = ""             # "2026-05__wehago" 형식 (고유)
    portal: str = ""                # Portal enum value
    target_year: int = 0
    target_month: int = 0
    status: str = BatchStatus.CREATED
    total_clients: int = 0          # 활성 수임처 총수
    completed_count: int = 0
    failed_count: int = 0
    skipped_count: int = 0
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


@dataclass
class Job:
    """수임처별 작업 실행 기록

    1 배치에 N개의 Job. 각 Job은 1개 수임처의 워크플로우.
    """
    id: Optional[int] = None
    batch_id: int = 0
    client_id: int = 0
    client_name: str = ""           # client.name 스냅샷 (조인 최소화)
    status: str = JobStatus.PENDING
    current_step: str = ""          # 현재/마지막 실행 단계명
    retry_count: int = 0
    max_retries: int = 3
    error_message: str = ""
    error_traceback: str = ""
    output_files: str = ""          # JSON 배열 문자열: ["file1.pdf", "file2.xlsx"]
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    duration_secs: Optional[float] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


@dataclass
class Step:
    """작업 내 개별 단계 체크포인트

    Job이 "로그인" -> "기간설정" -> "다운로드" 등 여러 단계로 구성될 때
    각 단계의 완료 상태를 기록.
    크래시 후 재시작 시 마지막 완료 단계부터 재개.
    """
    id: Optional[int] = None
    job_id: int = 0
    step_name: str = ""             # 단계명 (예: "login", "set_period", "download_pdf")
    step_index: int = 0             # 실행 순서 (0-based)
    status: str = StepStatus.PENDING
    step_data: str = ""             # JSON 문자열: 단계별 부가 데이터
    error_message: str = ""
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    duration_secs: Optional[float] = None
    created_at: Optional[str] = None


# ═══════════════════════════════════════════════════════════════════════
# 편의 함수
# ═══════════════════════════════════════════════════════════════════════

def make_batch_key(year: int, month: int, portal: str) -> str:
    """배치 고유키 생성

    >>> make_batch_key(2026, 5, "wehago")
    '2026-05__wehago'
    """
    return f"{year:04d}-{month:02d}__{portal}"


def now_iso() -> str:
    """현재 시각 ISO 형식 반환"""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
