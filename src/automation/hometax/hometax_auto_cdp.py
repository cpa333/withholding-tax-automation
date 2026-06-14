"""홈택스 원천세 파일변환신고 자동화 — CLI 진입점

하위 모듈로 분할 관리:
- _constants.py: 상수
- _session.py:   세션 연장 + 모달 처리
- _navigation.py: 메뉴 이동
- _upload.py:    파일 선택 + 검증
- _common.py:    재export 허브 + 연결

이 파일은 CLI 실행 + backward-compat re-export만 담당.
"""
import asyncio
import sys
import os

if sys.platform == "win32":
    import io
    # CLI 단독 실행 시 Windows 콘솔 UTF-8 보정.
    # GUI에서는 sys.stdout이 LogCapture로 교체돼 detach()를 지원하지 않으므로
    # (io.UnsupportedOperation) 안전하게 건너뛴다.
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.detach(), encoding='utf-8')
        sys.stderr = io.TextIOWrapper(sys.stderr.detach(), encoding='utf-8')
    except (io.UnsupportedOperation, AttributeError, ValueError):
        pass

# PROJECT_ROOT to sys.path for src.* imports
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, PROJECT_ROOT)

from src.automation.hometax._common import (
    connect_browser,
    auto_session_extend,
    goto_withholding_tax,
    goto_file_convert,
    select_file,
    verify_file,
    HOMETAX_URL,
)

# ─── backward-compat: 기존 import 경로 유지 ──────────────────────────────────
from src.automation.hometax._session import (
    auto_session_extend,
    trigger_session_popup_soon,
    dismiss_modals,
)
from src.automation.hometax._navigation import wait_element
from src.automation.hometax._upload import select_file, verify_file

_session_extend_task = None


async def run(file_path, dry_run=True):
    """홈택스 원천세 파일변환신고 자동화 실행

    Args:
        file_path: 업로드할 엑셀 파일 경로
        dry_run: True면 검증까지만, False면 제출까지 진행
    """
    from playwright.async_api import async_playwright
    from src.utils.log import log

    async with async_playwright() as p:
        log("Chrome 연결...")
        browser, context, ht = await connect_browser(p)
        log(f"현재: {await ht.title()}\n")

        # 세션 연장 백그라운드 태스크 시작
        global _session_extend_task
        _session_extend_task = asyncio.create_task(auto_session_extend(ht))

        # Raon K Uploader 파일 설정 시 JS dialog 자동 처리
        def _dismiss_dialog(dialog):
            try:
                asyncio.get_event_loop().create_task(dialog.dismiss())
            except Exception:
                pass
        ht.on("dialog", _dismiss_dialog)

        if not await goto_withholding_tax(ht):
            return
        if not await goto_file_convert(ht):
            return
        if not await select_file(ht, file_path):
            return
        if not await verify_file(ht):
            return

        if dry_run:
            log("\n[dry_run] 검증까지만 완료. 제출은 건너뜀.")
        else:
            log("\n[실운영] 제출 진행...")
            # TODO: 비밀번호 입력 → 제출 단계 구현

        # 세션 연장 태스크 정리
        if _session_extend_task:
            _session_extend_task.cancel()

        log("\n완료.")


if __name__ == "__main__":
    from playwright.async_api import async_playwright
    from src.utils.log import log

    if len(sys.argv) < 2:
        print("사용법: python hometax_auto_cdp.py <업로드엑셀경로> [--dry-run|--submit]")
        sys.exit(1)

    excel_path = sys.argv[1]
    dry = "--submit" not in sys.argv
    asyncio.run(run(excel_path, dry_run=dry))
