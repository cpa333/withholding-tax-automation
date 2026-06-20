"""Phase 1: 수임처 리스트 확보 — WEHAGO에서 수임처 목록을 가져와 DB에 등록"""

from src.config import DB_PATH
from src.workflows.registry import register
from src.workflows.base import BaseWorkflow
from src.batch.state import StateManager


@register(
    phase_id=1,
    portal="wehago",
    display_name="수임처 리스트 확보",
    is_list_phase=True,
)
class WehagoListClientsWorkflow(BaseWorkflow):
    steps = [
        {"name": "goto_taxagent", "index": 0},
        {"name": "dismiss_dialogs", "index": 1},
        {"name": "scrape_clients", "index": 2},
        {"name": "save_to_db", "index": 3},
    ]

    async def run_single(
        self, page, context, client_name: str, job_id: int,
        state: StateManager, **kwargs,
    ) -> bool:
        """Phase 1은 수임처별 Job이 아니라 전체 목록 조회.

        수임처관리(/tedge/#/taxagent) 페이지로 직접 이동하여 스크래핑.
        """
        import asyncio
        from src.automation.wehago._common import (
            WEHAGO_TAXAGENT_URL, dismiss_dialogs,
            get_all_clients_from_management,
        )
        from src.batch.db import BatchDB, ClientRepository
        from src.batch.models import Client
        import os

        # 수임처관리 페이지로 직접 이동
        if not state.should_skip_step(job_id, "goto_taxagent"):
            state.before_step(job_id, "goto_taxagent", 0)
            await page.goto(WEHAGO_TAXAGENT_URL, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(1)
            await dismiss_dialogs(page)
            state.after_step(job_id, "goto_taxagent")

        # 모달/팝업 닫기
        if not state.should_skip_step(job_id, "dismiss_dialogs"):
            state.before_step(job_id, "dismiss_dialogs", 1)
            await dismiss_dialogs(page)
            state.after_step(job_id, "dismiss_dialogs")

        # 전체 수임처 스크래핑
        companies = []
        if not state.should_skip_step(job_id, "scrape_clients"):
            state.before_step(job_id, "scrape_clients", 2)
            companies = await get_all_clients_from_management(page)
            # 테스트 태그 제거
            companies = [n.replace("[테스트] ", "") for n in companies]
            companies = [n for n in companies if n]  # 빈 문자열 제거
            state.after_step(job_id, "scrape_clients", {"count": len(companies)})

        # DB에 저장
        if not state.should_skip_step(job_id, "save_to_db"):
            state.before_step(job_id, "save_to_db", 3)
            db_path = kwargs.get("db_path", DB_PATH)
            os.makedirs(os.path.dirname(db_path), exist_ok=True)

            db = BatchDB(db_path)
            db.connect()
            try:
                client_repo = ClientRepository(db)
                # WEHAGO 단일 소스로만 저장
                for name in companies:
                    client_repo.upsert(Client(
                        name=name,
                        portal="wehago",
                        enabled=True,
                    ))
            finally:
                db.close()

            state.after_step(job_id, "save_to_db", {"saved": len(companies)})

        return True
