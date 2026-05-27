"""SQLite 데이터베이스 계층 — 스키마 생성, CRUD, 잡 큐

배치 엔진의 모든 영속 상태를 관리.
단일 파일 SQLite 데이터베이스. 외부 의존성 없이 stdlib sqlite3만 사용.

스레드 안전성:
    asyncio 단일 스레드에서만 사용. 동시성은 asyncio 이벤트 루프로 보장.
    SQLite 연결은 check_same_thread=False로 열지만,
    실제로는 메인 스레드에서만 접근함.

크래시 복구:
    모든 쓰기 작업은 즉시 커밋(connection.autocommit = OFF, 수동 COMMIT).
    배치 상태 변경 전 WAL 체크포인트를 수행하여
    크래시 후 재시작 시 일관된 상태 보장.
"""
from __future__ import annotations

import json
import os
import sqlite3
from typing import Optional

from src.batch.models import (
    Batch, BatchStatus, Client, Job, JobStatus,
    Step, StepStatus, make_batch_key, now_iso,
)


# ═══════════════════════════════════════════════════════════════════════
# 스키마 버전
# ═══════════════════════════════════════════════════════════════════════

SCHEMA_VERSION = 1

SCHEMA_SQL = """
-- ═══════════════════════════════════════════════════════════════════════
-- 메타
-- ═══════════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY
);

-- ═══════════════════════════════════════════════════════════════════════
-- 수임처 마스터
-- ═══════════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS clients (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT    NOT NULL,
    portal          TEXT    NOT NULL,     -- Portal enum value
    business_number TEXT    DEFAULT '',   -- 사업자등록번호
    enabled         INTEGER DEFAULT 1,   -- 1=활성, 0=비활성
    priority        INTEGER DEFAULT 100, -- 낮을수록 우선 처리
    notes           TEXT    DEFAULT '',
    created_at      TEXT    DEFAULT (strftime('%Y-%m-%d %H:%M:%S', 'now')),
    updated_at      TEXT    DEFAULT (strftime('%Y-%m-%d %H:%M:%S', 'now')),

    CONSTRAINT uq_client_portal UNIQUE (name, portal)
);

CREATE INDEX IF NOT EXISTS idx_clients_portal ON clients(portal);
CREATE INDEX IF NOT EXISTS idx_clients_enabled ON clients(enabled, priority);

-- ═══════════════════════════════════════════════════════════════════════
-- 배치 실행 단위
-- ═══════════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS batches (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_key       TEXT    NOT NULL UNIQUE,  -- "2026-05__wehago"
    portal          TEXT    NOT NULL,
    target_year     INTEGER NOT NULL,
    target_month    INTEGER NOT NULL,
    status          TEXT    NOT NULL DEFAULT 'created',
    total_clients   INTEGER DEFAULT 0,
    completed_count INTEGER DEFAULT 0,
    failed_count    INTEGER DEFAULT 0,
    skipped_count   INTEGER DEFAULT 0,
    started_at      TEXT,
    completed_at    TEXT,
    created_at      TEXT    DEFAULT (strftime('%Y-%m-%d %H:%M:%S', 'now')),
    updated_at      TEXT    DEFAULT (strftime('%Y-%m-%d %H:%M:%S', 'now'))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_batches_key ON batches(batch_key);
CREATE INDEX IF NOT EXISTS idx_batches_status ON batches(status);
CREATE INDEX IF NOT EXISTS idx_batches_portal ON batches(portal);

-- ═══════════════════════════════════════════════════════════════════════
-- 수임처별 작업
-- ═══════════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS jobs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id        INTEGER NOT NULL REFERENCES batches(id),
    client_id       INTEGER NOT NULL REFERENCES clients(id),
    client_name     TEXT    NOT NULL,        -- clients.name 스냅샷
    status          TEXT    NOT NULL DEFAULT 'pending',
    current_step    TEXT    DEFAULT '',
    retry_count     INTEGER DEFAULT 0,
    max_retries     INTEGER DEFAULT 3,
    error_message   TEXT    DEFAULT '',
    error_traceback TEXT    DEFAULT '',
    output_files    TEXT    DEFAULT '[]',    -- JSON 배열
    started_at      TEXT,
    completed_at    TEXT,
    duration_secs   REAL,
    created_at      TEXT    DEFAULT (strftime('%Y-%m-%d %H:%M:%S', 'now')),
    updated_at      TEXT    DEFAULT (strftime('%Y-%m-%d %H:%M:%S', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_jobs_batch ON jobs(batch_id);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(batch_id, status);
CREATE INDEX IF NOT EXISTS idx_jobs_client ON jobs(batch_id, client_id);

-- ═══════════════════════════════════════════════════════════════════════
-- 작업 내 단계 체크포인트
-- ═══════════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS steps (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id          INTEGER NOT NULL REFERENCES jobs(id),
    step_name       TEXT    NOT NULL,
    step_index      INTEGER NOT NULL DEFAULT 0,
    status          TEXT    NOT NULL DEFAULT 'pending',
    step_data       TEXT    DEFAULT '{}',   -- JSON
    error_message   TEXT    DEFAULT '',
    started_at      TEXT,
    completed_at    TEXT,
    duration_secs   REAL,
    created_at      TEXT    DEFAULT (strftime('%Y-%m-%d %H:%M:%S', 'now'))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_steps_job_name ON steps(job_id, step_name);
CREATE INDEX IF NOT EXISTS idx_steps_status ON steps(job_id, status);
"""


# ═══════════════════════════════════════════════════════════════════════
# BatchDB — SQLite 연결 관리 + 스키마 + 마이그레이션
# ═══════════════════════════════════════════════════════════════════════

class BatchDB:
    """배치 엔진 SQLite 데이터베이스 관리

    Usage:
        db = BatchDB("batch.db")
        db.connect()
        # ... 작업 ...
        db.close()

    또는 컨텍스트 매니저:
        with BatchDB("batch.db") as db:
            ...
    """

    def __init__(self, db_path: str) -> None:
        self.db_path = os.path.abspath(db_path)
        self.conn: Optional[sqlite3.Connection] = None

    # ── 연결 관리 ──────────────────────────────────────────────────

    def connect(self) -> None:
        """데이터베이스 연결 및 스키마 초기화

        WAL 모드로 열어 동시 읽기 허용.
        foreign_keys 활성화로 참조 무결성 보장.
        """
        os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
        self.conn = sqlite3.connect(
            self.db_path,
            check_same_thread=False,
            isolation_level=None,   # 자동 커밋 비활성화 → 수동 제어
        )
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.execute("PRAGMA busy_timeout=5000")
        self._ensure_schema()

    def close(self) -> None:
        """연결 종료"""
        if self.conn:
            try:
                self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            except sqlite3.Error:
                pass
            self.conn.close()
            self.conn = None

    def __enter__(self) -> "BatchDB":
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    # ── Repository 접근 ────────────────────────────────────────────

    @property
    def clients(self) -> "ClientRepository":
        if not hasattr(self, "_clients_repo"):
            self._clients_repo = ClientRepository(self)
        return self._clients_repo

    @property
    def batches(self) -> "BatchRepository":
        if not hasattr(self, "_batches_repo"):
            self._batches_repo = BatchRepository(self)
        return self._batches_repo

    @property
    def jobs(self) -> "JobRepository":
        if not hasattr(self, "_jobs_repo"):
            self._jobs_repo = JobRepository(self)
        return self._jobs_repo

    @property
    def steps(self) -> "StepRepository":
        if not hasattr(self, "_steps_repo"):
            self._steps_repo = StepRepository(self)
        return self._steps_repo

    # ── 스키마 관리 ────────────────────────────────────────────────

    def _ensure_schema(self) -> None:
        """스키마 생성 및 마이그레이션"""
        # 버전 확인
        try:
            row = self.conn.execute(
                "SELECT version FROM schema_version LIMIT 1"
            ).fetchone()
            current_version = row[0] if row else 0
        except sqlite3.OperationalError:
            current_version = 0

        if current_version < SCHEMA_VERSION:
            self.conn.execute("BEGIN")
            try:
                if current_version == 0:
                    # 최초 생성
                    for stmt in SCHEMA_SQL.split(";"):
                        stmt = stmt.strip()
                        if stmt:
                            self.conn.execute(stmt)
                    self.conn.execute(
                        "INSERT INTO schema_version (version) VALUES (?)",
                        (SCHEMA_VERSION,),
                    )
                # 향후 마이그레이션은 여기에 추가:
                # if current_version < 2:
                #     self.conn.execute("ALTER TABLE ...")
                #     self.conn.execute("UPDATE schema_version SET version = 2")

                self.conn.execute("COMMIT")
            except Exception:
                self.conn.execute("ROLLBACK")
                raise

    # ── 트랜잭션 헬퍼 ─────────────────────────────────────────────

    def begin(self) -> None:
        """트랜잭션 시작"""
        self.conn.execute("BEGIN")

    def commit(self) -> None:
        """트랜잭션 커밋"""
        self.conn.execute("COMMIT")

    def rollback(self) -> None:
        """트랜잭션 롤백"""
        self.conn.execute("ROLLBACK")


# ═══════════════════════════════════════════════════════════════════════
# ClientRepository — 수임처 CRUD
# ═══════════════════════════════════════════════════════════════════════

class ClientRepository:
    """수임처 마스터 테이블 CRUD"""

    def __init__(self, db: BatchDB) -> None:
        self.db = db

    def upsert(self, client: Client) -> int:
        """수임처 등록 또는 업데이트

        (name, portal) UNIQUE 제약으로 중복 방지.
        enabled, priority, notes만 업데이트.

        Returns:
            client.id
        """
        now = now_iso()
        self.db.begin()
        try:
            # 기존 조회
            row = self.db.conn.execute(
                "SELECT id FROM clients WHERE name = ? AND portal = ?",
                (client.name, client.portal),
            ).fetchone()

            if row:
                client_id = row[0]
                self.db.conn.execute(
                    """UPDATE clients
                       SET enabled = ?, priority = ?, notes = ?,
                           business_number = ?, updated_at = ?
                       WHERE id = ?""",
                    (int(client.enabled), client.priority, client.notes,
                     client.business_number, now, client_id),
                )
            else:
                cur = self.db.conn.execute(
                    """INSERT INTO clients (name, portal, business_number,
                       enabled, priority, notes, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (client.name, client.portal, client.business_number,
                     int(client.enabled), client.priority, client.notes,
                     now, now),
                )
                client_id = cur.lastrowid

            self.db.commit()
            return client_id
        except Exception:
            self.db.rollback()
            raise

    def get(self, client_id: int) -> Optional[Client]:
        """ID로 수임처 조회"""
        row = self.db.conn.execute(
            "SELECT * FROM clients WHERE id = ?", (client_id,)
        ).fetchone()
        return self._row_to_client(row) if row else None

    def get_by_name(self, name: str, portal: str) -> Optional[Client]:
        """이름 + 포털로 수임처 조회"""
        row = self.db.conn.execute(
            "SELECT * FROM clients WHERE name = ? AND portal = ?",
            (name, portal),
        ).fetchone()
        return self._row_to_client(row) if row else None

    def list_active(self, portal: str) -> list[Client]:
        """활성 수임처 목록 (priority 순)"""
        rows = self.db.conn.execute(
            """SELECT * FROM clients
               WHERE portal = ? AND enabled = 1
               ORDER BY priority, name""",
            (portal,),
        ).fetchall()
        return [self._row_to_client(r) for r in rows]

    def list_all(self, portal: str = "") -> list[Client]:
        """전체 수임처 목록"""
        if portal:
            rows = self.db.conn.execute(
                "SELECT * FROM clients WHERE portal = ? ORDER BY priority, name",
                (portal,),
            ).fetchall()
        else:
            rows = self.db.conn.execute(
                "SELECT * FROM clients ORDER BY portal, priority, name"
            ).fetchall()
        return [self._row_to_client(r) for r in rows]

    def delete(self, client_id: int) -> None:
        """수임처 삭제 (비활성화 권장)"""
        self.db.conn.execute("DELETE FROM clients WHERE id = ?", (client_id,))

    @staticmethod
    def _row_to_client(row: tuple) -> Client:
        return Client(
            id=row[0],
            name=row[1],
            portal=row[2],
            business_number=row[3] or "",
            enabled=bool(row[4]),
            priority=row[5],
            notes=row[6] or "",
            created_at=row[7],
            updated_at=row[8],
        )


# ═══════════════════════════════════════════════════════════════════════
# BatchRepository — 배치 CRUD
# ═══════════════════════════════════════════════════════════════════════

class BatchRepository:
    """배치 실행 단위 CRUD"""

    def __init__(self, db: BatchDB) -> None:
        self.db = db

    def create(self, portal: str, year: int, month: int) -> Batch:
        """새 배치 생성

        batch_key로 중복 체크. 이미 존재하면 기존 배치 반환.

        Returns:
            Batch 객체
        """
        key = make_batch_key(year, month, portal)
        now = now_iso()

        self.db.begin()
        try:
            # 기존 배치 확인
            row = self.db.conn.execute(
                "SELECT id FROM batches WHERE batch_key = ?", (key,)
            ).fetchone()

            if row:
                batch_id = row[0]
            else:
                cur = self.db.conn.execute(
                    """INSERT INTO batches
                       (batch_key, portal, target_year, target_month,
                        status, started_at, created_at, updated_at)
                       VALUES (?, ?, ?, ?, 'created', NULL, ?, ?)""",
                    (key, portal, year, month, now, now),
                )
                batch_id = cur.lastrowid

            self.db.commit()
            return self.get(batch_id)
        except Exception:
            self.db.rollback()
            raise

    def get(self, batch_id: int) -> Optional[Batch]:
        """ID로 배치 조회"""
        row = self.db.conn.execute(
            "SELECT * FROM batches WHERE id = ?", (batch_id,)
        ).fetchone()
        return self._row_to_batch(row) if row else None

    def get_by_key(self, batch_key: str) -> Optional[Batch]:
        """batch_key로 배치 조회"""
        row = self.db.conn.execute(
            "SELECT * FROM batches WHERE batch_key = ?", (batch_key,)
        ).fetchone()
        return self._row_to_batch(row) if row else None

    def get_active(self, portal: str) -> Optional[Batch]:
        """포털의 활성 배치 조회 (created/running/paused)"""
        row = self.db.conn.execute(
            """SELECT * FROM batches
               WHERE portal = ? AND status IN ('created', 'running', 'paused')
               ORDER BY created_at DESC LIMIT 1""",
            (portal,),
        ).fetchone()
        return self._row_to_batch(row) if row else None

    def get_latest(self, portal: str) -> Optional[Batch]:
        """포털의 최근 배치 (상태 무관)"""
        row = self.db.conn.execute(
            """SELECT * FROM batches
               WHERE portal = ?
               ORDER BY target_year DESC, target_month DESC LIMIT 1""",
            (portal,),
        ).fetchone()
        return self._row_to_batch(row) if row else None

    def update_status(self, batch_id: int, status: str) -> None:
        """배치 상태 변경"""
        now = now_iso()
        extra = ""
        params: list = [status, now, batch_id]

        if status == BatchStatus.RUNNING:
            extra = ", started_at = COALESCE(started_at, ?)"
            params.insert(2, now)
        elif status in (BatchStatus.COMPLETED, BatchStatus.ARCHIVED):
            extra = ", completed_at = ?"
            params.insert(2, now)

        self.db.conn.execute(
            f"UPDATE batches SET status = ?, updated_at = ?{extra} WHERE id = ?",
            params,
        )

    def increment_counts(
        self, batch_id: int,
        completed: int = 0, failed: int = 0, skipped: int = 0,
    ) -> None:
        """배치 카운터 증가"""
        now = now_iso()
        self.db.conn.execute(
            """UPDATE batches
               SET completed_count = completed_count + ?,
                   failed_count = failed_count + ?,
                   skipped_count = skipped_count + ?,
                   updated_at = ?
               WHERE id = ?""",
            (completed, failed, skipped, now, batch_id),
        )

    def update_total_clients(self, batch_id: int, total: int) -> None:
        """활성 수임처 총수 설정"""
        self.db.conn.execute(
            "UPDATE batches SET total_clients = ?, updated_at = ? WHERE id = ?",
            (total, now_iso(), batch_id),
        )

    def mark_crashed_as_recoverable(self) -> list[Batch]:
        """비정상 종료된 배치를 crashed로 표시

        재시작 시 호출. running/paused 상태의 배치가 있으면
        크래시로 간주하고 상태를 crashed로 변경.

        Returns:
            크래시로 표시된 배치 목록
        """
        crashed = []
        self.db.begin()
        try:
            rows = self.db.conn.execute(
                """SELECT * FROM batches
                   WHERE status IN ('running', 'paused')"""
            ).fetchall()

            for row in rows:
                batch = self._row_to_batch(row)
                self.update_status(batch.id, BatchStatus.CRASHED)
                crashed.append(batch)

            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

        return crashed

    def archive_completed(self, portal: str) -> int:
        """완료된 이전 배치를 archived로 변경

        현재 활성 배치를 제외한 모든 completed 배치를 archived 처리.

        Returns:
            archived된 배치 수
        """
        self.db.begin()
        try:
            cur = self.db.conn.execute(
                """UPDATE batches
                   SET status = 'archived', updated_at = ?
                   WHERE portal = ? AND status = 'completed'""",
                (now_iso(), portal),
            )
            count = cur.rowcount
            self.db.commit()
            return count
        except Exception:
            self.db.rollback()
            raise

    def list_by_status(self, status: str, portal: str = "") -> list[Batch]:
        """상태별 배치 목록"""
        if portal:
            rows = self.db.conn.execute(
                "SELECT * FROM batches WHERE status = ? AND portal = ? ORDER BY created_at DESC",
                (status, portal),
            ).fetchall()
        else:
            rows = self.db.conn.execute(
                "SELECT * FROM batches WHERE status = ? ORDER BY created_at DESC",
                (status,),
            ).fetchall()
        return [self._row_to_batch(r) for r in rows]

    @staticmethod
    def _row_to_batch(row: tuple) -> Batch:
        return Batch(
            id=row[0],
            batch_key=row[1],
            portal=row[2],
            target_year=row[3],
            target_month=row[4],
            status=row[5],
            total_clients=row[6],
            completed_count=row[7],
            failed_count=row[8],
            skipped_count=row[9],
            started_at=row[10],
            completed_at=row[11],
            created_at=row[12],
            updated_at=row[13],
        )


# ═══════════════════════════════════════════════════════════════════════
# JobRepository — 잡 CRUD + 큐
# ═══════════════════════════════════════════════════════════════════════

class JobRepository:
    """수임처별 작업 CRUD 및 큐 관리"""

    def __init__(self, db: BatchDB) -> None:
        self.db = db

    # ── 생성 ───────────────────────────────────────────────────────

    def enqueue_all(self, batch_id: int, clients: list[Client]) -> int:
        """배치에 수임처 목록을 일괄 등록

        이미 등록된 수임처(client_id)는 건너뜀.

        Returns:
            새로 등록된 잡 수
        """
        if not clients:
            return 0

        now = now_iso()
        self.db.begin()
        try:
            # 기존 잡의 client_id 집합
            existing_rows = self.db.conn.execute(
                "SELECT client_id FROM jobs WHERE batch_id = ?", (batch_id,)
            ).fetchall()
            existing_ids = {r[0] for r in existing_rows}

            count = 0
            for client in clients:
                if client.id in existing_ids:
                    continue
                self.db.conn.execute(
                    """INSERT INTO jobs
                       (batch_id, client_id, client_name, status,
                        created_at, updated_at)
                       VALUES (?, ?, ?, 'pending', ?, ?)""",
                    (batch_id, client.id, client.name, now, now),
                )
                count += 1

            self.db.commit()
            return count
        except Exception:
            self.db.rollback()
            raise

    def enqueue_failed_for_retry(self, batch_id: int) -> int:
        """실패한 잡을 재시도 대기 상태로 변경

        retry_count < max_retries인 잡만 재시도.

        Returns:
            재시도 대기로 변경된 잡 수
        """
        now = now_iso()
        self.db.begin()
        try:
            cur = self.db.conn.execute(
                """UPDATE jobs
                   SET status = 'pending', error_message = '',
                       error_traceback = '', updated_at = ?,
                       started_at = NULL, completed_at = NULL,
                       duration_secs = NULL,
                       retry_count = retry_count + 1
                   WHERE batch_id = ? AND status = 'failed'
                       AND retry_count < max_retries""",
                (now, batch_id),
            )
            count = cur.rowcount

            # 배치 카운터 재계산
            self._recalculate_batch_counts(batch_id)

            self.db.commit()
            return count
        except Exception:
            self.db.rollback()
            raise

    # ── 조회 ───────────────────────────────────────────────────────

    def get(self, job_id: int) -> Optional[Job]:
        """ID로 잡 조회"""
        row = self.db.conn.execute(
            "SELECT * FROM jobs WHERE id = ?", (job_id,)
        ).fetchone()
        return self._row_to_job(row) if row else None

    def get_next_pending(self, batch_id: int) -> Optional[Job]:
        """다음 대기 중인 잡 반환 (FIFO)

        client priority 순서로 처리.
        """
        row = self.db.conn.execute(
            """SELECT j.* FROM jobs j
               LEFT JOIN clients c ON j.client_id = c.id
               WHERE j.batch_id = ? AND j.status = 'pending'
               ORDER BY c.priority, j.id
               LIMIT 1""",
            (batch_id,),
        ).fetchone()
        return self._row_to_job(row) if row else None

    def list_by_batch(self, batch_id: int, status: str = "") -> list[Job]:
        """배치 내 잡 목록"""
        if status:
            rows = self.db.conn.execute(
                """SELECT * FROM jobs
                   WHERE batch_id = ? AND status = ?
                   ORDER BY id""",
                (batch_id, status),
            ).fetchall()
        else:
            rows = self.db.conn.execute(
                "SELECT * FROM jobs WHERE batch_id = ? ORDER BY id",
                (batch_id,),
            ).fetchall()
        return [self._row_to_job(r) for r in rows]

    def list_failed(self, batch_id: int) -> list[Job]:
        """실패한 잡 목록"""
        return self.list_by_batch(batch_id, status=JobStatus.FAILED)

    def get_by_client(self, batch_id: int, client_id: int) -> Optional[Job]:
        """배치 내 특정 수임처의 잡 조회"""
        row = self.db.conn.execute(
            "SELECT * FROM jobs WHERE batch_id = ? AND client_id = ?",
            (batch_id, client_id),
        ).fetchone()
        return self._row_to_job(row) if row else None

    def count_by_status(self, batch_id: int) -> dict[str, int]:
        """상태별 잡 수"""
        rows = self.db.conn.execute(
            """SELECT status, COUNT(*) FROM jobs
               WHERE batch_id = ? GROUP BY status""",
            (batch_id,),
        ).fetchall()
        return {r[0]: r[1] for r in rows}

    # ── 상태 변경 ──────────────────────────────────────────────────

    def mark_running(self, job_id: int) -> None:
        """잡을 running 상태로 변경"""
        now = now_iso()
        self.db.conn.execute(
            """UPDATE jobs
               SET status = 'running', started_at = COALESCE(started_at, ?),
                   updated_at = ?
               WHERE id = ?""",
            (now, now, job_id),
        )

    def mark_completed(self, job_id: int, output_files: list[str] | None = None) -> None:
        """잡을 completed 상태로 변경"""
        now = now_iso()
        files_json = json.dumps(output_files or [], ensure_ascii=False)

        self.db.begin()
        try:
            row = self.db.conn.execute(
                "SELECT started_at FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
            started = row[0] if row else None

            duration = None
            if started:
                try:
                    from datetime import datetime as _dt
                    t1 = _dt.strptime(now, "%Y-%m-%d %H:%M:%S")
                    t2 = _dt.strptime(started, "%Y-%m-%d %H:%M:%S")
                    duration = (t1 - t2).total_seconds()
                except (ValueError, TypeError):
                    pass

            self.db.conn.execute(
                """UPDATE jobs
                   SET status = 'completed', completed_at = ?,
                       duration_secs = ?, output_files = ?, updated_at = ?
                   WHERE id = ?""",
                (now, duration, files_json, now, job_id),
            )

            # 배치 카운터 업데이트
            batch_row = self.db.conn.execute(
                "SELECT batch_id FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
            if batch_row:
                self.db.conn.execute(
                    """UPDATE batches
                       SET completed_count = completed_count + 1, updated_at = ?
                       WHERE id = ?""",
                    (now, batch_row[0]),
                )

            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

    def mark_failed(
        self, job_id: int, error_message: str, error_traceback: str = "",
    ) -> None:
        """잡을 failed 상태로 변경"""
        now = now_iso()

        self.db.begin()
        try:
            row = self.db.conn.execute(
                "SELECT started_at FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
            started = row[0] if row else None

            duration = None
            if started:
                try:
                    from datetime import datetime as _dt
                    t1 = _dt.strptime(now, "%Y-%m-%d %H:%M:%S")
                    t2 = _dt.strptime(started, "%Y-%m-%d %H:%M:%S")
                    duration = (t1 - t2).total_seconds()
                except (ValueError, TypeError):
                    pass

            self.db.conn.execute(
                """UPDATE jobs
                   SET status = 'failed', error_message = ?,
                       error_traceback = ?, completed_at = ?,
                       duration_secs = ?, updated_at = ?
                   WHERE id = ?""",
                (error_message[:2000], error_traceback[:10000],
                 now, duration, now, job_id),
            )

            # 배치 카운터 업데이트
            batch_row = self.db.conn.execute(
                "SELECT batch_id FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
            if batch_row:
                self.db.conn.execute(
                    """UPDATE batches
                       SET failed_count = failed_count + 1, updated_at = ?
                       WHERE id = ?""",
                    (now, batch_row[0]),
                )

            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

    def mark_skipped(self, job_id: int, reason: str = "") -> None:
        """잡을 skipped 상태로 변경"""
        now = now_iso()

        self.db.begin()
        try:
            self.db.conn.execute(
                """UPDATE jobs
                   SET status = 'skipped', error_message = ?,
                       completed_at = ?, updated_at = ?
                   WHERE id = ?""",
                (reason[:2000], now, now, job_id),
            )

            batch_row = self.db.conn.execute(
                "SELECT batch_id FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
            if batch_row:
                self.db.conn.execute(
                    """UPDATE batches
                       SET skipped_count = skipped_count + 1, updated_at = ?
                       WHERE id = ?""",
                    (now, batch_row[0]),
                )

            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

    def set_current_step(self, job_id: int, step_name: str) -> None:
        """현재 실행 단계 설정"""
        self.db.conn.execute(
            "UPDATE jobs SET current_step = ?, updated_at = ? WHERE id = ?",
            (step_name, now_iso(), job_id),
        )

    def set_output_files(self, job_id: int, files: list[str]) -> None:
        """출력 파일 목록 설정"""
        self.db.conn.execute(
            "UPDATE jobs SET output_files = ?, updated_at = ? WHERE id = ?",
            (json.dumps(files, ensure_ascii=False), now_iso(), job_id),
        )

    def increment_retry(self, job_id: int) -> None:
        """재시도 횟수 증가"""
        self.db.conn.execute(
            "UPDATE jobs SET retry_count = retry_count + 1, updated_at = ? WHERE id = ?",
            (now_iso(), job_id),
        )

    # ── 내부 유틸 ─────────────────────────────────────────────────

    def _recalculate_batch_counts(self, batch_id: int) -> None:
        """배치 카운터 재계산 (집계 쿼리)"""
        now = now_iso()
        self.db.conn.execute(
            """UPDATE batches
               SET completed_count = (SELECT COUNT(*) FROM jobs WHERE batch_id = ? AND status = 'completed'),
                   failed_count = (SELECT COUNT(*) FROM jobs WHERE batch_id = ? AND status = 'failed'),
                   skipped_count = (SELECT COUNT(*) FROM jobs WHERE batch_id = ? AND status = 'skipped'),
                   updated_at = ?
               WHERE id = ?""",
            (batch_id, batch_id, batch_id, now, batch_id),
        )

    @staticmethod
    def _row_to_job(row: tuple) -> Job:
        return Job(
            id=row[0],
            batch_id=row[1],
            client_id=row[2],
            client_name=row[3],
            status=row[4],
            current_step=row[5] or "",
            retry_count=row[6],
            max_retries=row[7],
            error_message=row[8] or "",
            error_traceback=row[9] or "",
            output_files=row[10] or "[]",
            started_at=row[11],
            completed_at=row[12],
            duration_secs=row[13],
            created_at=row[14],
            updated_at=row[15],
        )


# ═══════════════════════════════════════════════════════════════════════
# StepRepository — 단계 체크포인트 CRUD
# ═══════════════════════════════════════════════════════════════════════

class StepRepository:
    """작업 내 단계 체크포인트 CRUD"""

    def __init__(self, db: BatchDB) -> None:
        self.db = db

    def create(self, job_id: int, step_name: str, step_index: int,
               step_data: dict | None = None) -> int:
        """단계 생성

        이미 존재하면 무시 (idempotent).

        Returns:
            step.id
        """
        data_json = json.dumps(step_data or {}, ensure_ascii=False)

        self.db.begin()
        try:
            existing = self.db.conn.execute(
                "SELECT id FROM steps WHERE job_id = ? AND step_name = ?",
                (job_id, step_name),
            ).fetchone()

            if existing:
                step_id = existing[0]
            else:
                cur = self.db.conn.execute(
                    """INSERT INTO steps
                       (job_id, step_name, step_index, step_data, created_at)
                       VALUES (?, ?, ?, ?, ?)""",
                    (job_id, step_name, step_index, data_json, now_iso()),
                )
                step_id = cur.lastrowid

            self.db.commit()
            return step_id
        except Exception:
            self.db.rollback()
            raise

    def mark_running(self, job_id: int, step_name: str,
                     step_data: dict | None = None) -> None:
        """단계를 running 상태로 변경

        단계가 없으면 생성. step_data가 제공되면 업데이트.
        """
        now = now_iso()
        data_json = json.dumps(step_data or {}, ensure_ascii=False)

        self.db.conn.execute(
            """INSERT INTO steps (job_id, step_name, step_index, status,
               step_data, started_at, created_at)
               VALUES (?, ?, 0, 'running', ?, ?, ?)
               ON CONFLICT(job_id, step_name) DO UPDATE SET
                   status = 'running', started_at = ?,
                   step_data = ?""",
            (job_id, step_name, data_json, now, now, now, data_json),
        )

    def mark_completed(self, job_id: int, step_name: str,
                       step_data: dict | None = None) -> None:
        """단계를 completed 상태로 변경"""
        now = now_iso()
        data_json = json.dumps(step_data or {}, ensure_ascii=False)

        self.db.begin()
        try:
            # duration 계산
            row = self.db.conn.execute(
                "SELECT started_at FROM steps WHERE job_id = ? AND step_name = ?",
                (job_id, step_name),
            ).fetchone()
            duration = None
            if row and row[0]:
                try:
                    from datetime import datetime as _dt
                    t1 = _dt.strptime(now, "%Y-%m-%d %H:%M:%S")
                    t2 = _dt.strptime(row[0], "%Y-%m-%d %H:%M:%S")
                    duration = (t1 - t2).total_seconds()
                except (ValueError, TypeError):
                    pass

            self.db.conn.execute(
                """UPDATE steps
                   SET status = 'completed', completed_at = ?,
                       duration_secs = ?, step_data = ?
                   WHERE job_id = ? AND step_name = ?""",
                (now, duration, data_json, job_id, step_name),
            )
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

    def mark_failed(self, job_id: int, step_name: str,
                    error_message: str = "") -> None:
        """단계를 failed 상태로 변경"""
        now = now_iso()
        self.db.conn.execute(
            """UPDATE steps
               SET status = 'failed', error_message = ?, completed_at = ?
               WHERE job_id = ? AND step_name = ?""",
            (error_message[:2000], now, job_id, step_name),
        )

    def get_last_completed(self, job_id: int) -> Optional[Step]:
        """마지막 완료된 단계 반환 (재개 지점)"""
        row = self.db.conn.execute(
            """SELECT * FROM steps
               WHERE job_id = ? AND status = 'completed'
               ORDER BY step_index DESC, id DESC
               LIMIT 1""",
            (job_id,),
        ).fetchone()
        return self._row_to_step(row) if row else None

    def get_resume_index(self, job_id: int) -> int:
        """재개할 단계 인덱스 반환

        마지막 완료 단계의 다음 인덱스.
        완료된 단계가 없으면 0.
        """
        step = self.get_last_completed(job_id)
        if step:
            return step.step_index + 1
        return 0

    def list_by_job(self, job_id: int) -> list[Step]:
        """잡의 모든 단계 목록"""
        rows = self.db.conn.execute(
            "SELECT * FROM steps WHERE job_id = ? ORDER BY step_index",
            (job_id,),
        ).fetchall()
        return [self._row_to_step(r) for r in rows]

    def get_step(self, job_id: int, step_name: str) -> Optional[Step]:
        """특정 단계 조회"""
        row = self.db.conn.execute(
            "SELECT * FROM steps WHERE job_id = ? AND step_name = ?",
            (job_id, step_name),
        ).fetchone()
        return self._row_to_step(row) if row else None

    def is_completed(self, job_id: int, step_name: str) -> bool:
        """단계가 완료되었는지 확인"""
        row = self.db.conn.execute(
            "SELECT status FROM steps WHERE job_id = ? AND step_name = ?",
            (job_id, step_name),
        ).fetchone()
        return row is not None and row[0] == StepStatus.COMPLETED

    def mark_pending(self, job_id: int, step_name: str) -> None:
        """단계를 pending 상태로 리셋 (크래시 복구용)"""
        self.db.conn.execute(
            """UPDATE steps
               SET status = 'pending', started_at = NULL,
                   duration_secs = NULL, error_message = ''
               WHERE job_id = ? AND step_name = ?""",
            (job_id, step_name),
        )

    @staticmethod
    def _row_to_step(row: tuple) -> Step:
        return Step(
            id=row[0],
            job_id=row[1],
            step_name=row[2],
            step_index=row[3],
            status=row[4],
            step_data=row[5] or "{}",
            error_message=row[6] or "",
            started_at=row[7],
            completed_at=row[8],
            duration_secs=row[9],
            created_at=row[10],
        )
