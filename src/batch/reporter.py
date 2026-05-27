"""배치 실행 결과 리포트 생성기

콘솔 출력, CSV, HTML 리포트를 생성.
"""
from __future__ import annotations

import csv
import html
import io
import os
from datetime import datetime
from typing import Optional

from src.batch.models import Batch, Job, Step, Portal


class BatchReporter:
    """배치 실행 결과 리포트

    Usage:
        reporter = BatchReporter(db)
        reporter.print_console(batch_id)
        reporter.save_csv(batch_id, "report.csv")
        reporter.save_html(batch_id, "report.html")
    """

    def __init__(self, db) -> None:
        """
        Args:
            db: BatchDB 인스턴스
        """
        self.db = db

    def _load_batch_data(self, batch_id: int) -> dict:
        """리포트용 데이터 로드"""
        from src.batch.db import BatchRepository, JobRepository, StepRepository

        batch_repo = BatchRepository(self.db)
        job_repo = JobRepository(self.db)
        step_repo = StepRepository(self.db)

        batch = batch_repo.get(batch_id)
        if not batch:
            return {}

        jobs = job_repo.list_by_batch(batch_id)
        job_details = []
        for job in jobs:
            steps = step_repo.list_by_job(job.id)
            job_details.append({"job": job, "steps": steps})

        return {
            "batch": batch,
            "jobs": job_details,
        }

    # ── 콘솔 출력 ─────────────────────────────────────────────────

    def print_console(self, batch_id: int) -> None:
        """콘솔에 진행 상황 출력"""
        data = self._load_batch_data(batch_id)
        if not data:
            print("  배치를 찾을 수 없습니다.")
            return

        batch = data["batch"]
        jobs = data["jobs"]

        print(f"\n{'='*60}")
        print(f"  배치: {batch.batch_key}")
        print(f"  상태: {batch.status}")
        print(f"  총 {len(jobs)}건 | "
              f"완료 {batch.completed_count} | "
              f"실패 {batch.failed_count} | "
              f"건너뜀 {batch.skipped_count}")
        print(f"{'='*60}")

        status_icons = {
            "completed": "+",
            "failed": "X",
            "skipped": "-",
            "pending": ".",
            "running": "*",
        }

        for item in jobs:
            job = item["job"]
            icon = status_icons.get(job.status, "?")
            duration = ""
            if job.duration_secs is not None:
                duration = f" ({job.duration_secs:.1f}초)"

            print(f"  [{icon}] {job.client_name}{duration}", end="")

            if job.error_message:
                print(f" - {job.error_message[:60]}", end="")
            print()

        print(f"{'='*60}\n")

    # ── CSV ────────────────────────────────────────────────────────

    def save_csv(self, batch_id: int, output_path: str) -> str:
        """CSV 리포트 저장

        Returns:
            저장된 파일 경로
        """
        data = self._load_batch_data(batch_id)
        if not data:
            return ""

        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

        with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow([
                "수임처", "상태", "현재단계", "재시도",
                "소요시간(초)", "오류메시지", "시작시각", "완료시각",
            ])

            for item in data["jobs"]:
                job = item["job"]
                writer.writerow([
                    job.client_name,
                    job.status,
                    job.current_step,
                    job.retry_count,
                    f"{job.duration_secs:.1f}" if job.duration_secs else "",
                    job.error_message[:200],
                    job.started_at or "",
                    job.completed_at or "",
                ])

        return output_path

    # ── HTML ───────────────────────────────────────────────────────

    def save_html(self, batch_id: int, output_path: str) -> str:
        """HTML 리포트 저장

        Returns:
            저장된 파일 경로
        """
        data = self._load_batch_data(batch_id)
        if not data:
            return ""

        batch = data["batch"]
        jobs = data["jobs"]

        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

        status_colors = {
            "completed": "#4CAF50",
            "failed": "#F44336",
            "skipped": "#9E9E9E",
            "pending": "#FFC107",
            "running": "#2196F3",
        }

        status_labels = {
            "completed": "완료",
            "failed": "실패",
            "skipped": "건너뜀",
            "pending": "대기",
            "running": "실행중",
        }

        rows_html = ""
        for item in jobs:
            job = item["job"]
            steps = item["steps"]
            color = status_colors.get(job.status, "#999")
            label = status_labels.get(job.status, job.status)

            steps_html = ""
            for s in steps:
                sc = status_colors.get(s.status, "#999")
                sl = status_labels.get(s.status, s.status)
                dur = f"{s.duration_secs:.1f}초" if s.duration_secs else ""
                steps_html += (
                    f'<span style="background:{sc};color:white;padding:1px 6px;'
                    f'border-radius:3px;margin:2px;font-size:11px">'
                    f'{html.escape(s.step_name)} {sl} {dur}</span> '
                )

            duration = f"{job.duration_secs:.1f}초" if job.duration_secs else ""
            err = html.escape(job.error_message[:100]) if job.error_message else ""

            rows_html += f"""
            <tr>
                <td>{html.escape(job.client_name)}</td>
                <td><span style="background:{color};color:white;padding:2px 8px;
                    border-radius:4px;font-size:12px">{label}</span></td>
                <td>{duration}</td>
                <td>{steps_html or '-'}</td>
                <td style="color:#F44336;font-size:12px">{err}</td>
            </tr>"""

        try:
            portal_display = Portal(batch.portal).display_name
        except ValueError:
            portal_display = batch.portal

        html_content = f"""<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <title>배치 실행 결과 — {html.escape(batch.batch_key)}</title>
    <style>
        body {{ font-family: 'Malgun Gothic', sans-serif; margin: 20px; background: #f5f5f5; }}
        .header {{ background: #333; color: white; padding: 20px; border-radius: 8px; margin-bottom: 20px; }}
        table {{ width: 100%; border-collapse: collapse; background: white; border-radius: 8px; overflow: hidden; }}
        th {{ background: #455A64; color: white; padding: 10px; text-align: left; }}
        td {{ padding: 8px 10px; border-bottom: 1px solid #eee; }}
        tr:hover {{ background: #f0f0f0; }}
        .stats {{ display: flex; gap: 15px; margin: 15px 0; }}
        .stat {{ background: white; padding: 15px 20px; border-radius: 8px; text-align: center; }}
        .stat-value {{ font-size: 24px; font-weight: bold; }}
        .stat-label {{ font-size: 12px; color: #666; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>{html.escape(portal_display)} 배치 결과</h1>
        <p>{html.escape(batch.batch_key)} | {html.escape(batch.status)}</p>
        <p>시작: {batch.started_at or '-'} | 완료: {batch.completed_at or '-'}</p>
    </div>
    <div class="stats">
        <div class="stat"><div class="stat-value">{batch.total_clients}</div><div class="stat-label">전체</div></div>
        <div class="stat"><div class="stat-value" style="color:#4CAF50">{batch.completed_count}</div><div class="stat-label">완료</div></div>
        <div class="stat"><div class="stat-value" style="color:#F44336">{batch.failed_count}</div><div class="stat-label">실패</div></div>
        <div class="stat"><div class="stat-value" style="color:#9E9E9E">{batch.skipped_count}</div><div class="stat-label">건너뜀</div></div>
    </div>
    <table>
        <thead>
            <tr>
                <th>수임처</th>
                <th>상태</th>
                <th>소요시간</th>
                <th>단계</th>
                <th>오류</th>
            </tr>
        </thead>
        <tbody>
            {rows_html}
        </tbody>
    </table>
    <p style="margin-top:15px;color:#999;font-size:11px">
        생성: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
    </p>
</body>
</html>"""

        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html_content)

        return output_path
