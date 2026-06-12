"""홈택스 파일 업로드 모듈

Raon K Uploader 파일 선택 + 파일검증 처리.
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))
from src.utils.log import log
from src.automation.hometax._constants import SELECTOR_BTN_CEN_STS
from src.automation.hometax._session import dismiss_modals


async def select_file(ht, file_path):
    """파일변환신고 화면에서 파일 선택 (Raon K Uploader iframe 내 hidden file input)

    Raon K Uploader가 raonkuploader_frame_fileList iframe에
    <input type="file">을 동적으로 생성함.
    파일 설정 후 change 이벤트를 발생시켜 컴포넌트가 파일을 인식하도록 함.
    """
    log(f"[3] 파일 선택: {os.path.basename(file_path)}")
    for _ in range(15):
        for frame in ht.frames:
            file_input = frame.locator('input[type="file"]')
            if await file_input.count() > 0:
                await file_input.set_input_files(file_path)
                try:
                    await frame.evaluate("""() => {
                        const fi = document.querySelector('input[type="file"]');
                        if (fi) fi.dispatchEvent(new Event('change', {bubbles: true}));
                    }""")
                except Exception:
                    pass
                log("  파일 설정 완료")
                await asyncio.sleep(2)
                return True
        await asyncio.sleep(2)
    log("  파일 input을 찾지 못함 (30초 대기 초과)")
    return False


async def verify_file(ht):
    """파일검증하기 버튼 클릭 후 후속 모달 자동 처리"""
    log("[4] 파일검증하기 클릭...")
    clicked = await ht.evaluate("""() => {
        const btn = document.querySelector('[id*="btn_cenSts"]');
        if (btn) { btn.click(); return true; }
        return false;
    }""")
    if not clicked:
        log("  파일검증 버튼을 찾지 못함")
        return False

    await asyncio.sleep(3)
    await dismiss_modals(ht)
    await asyncio.sleep(5)
    log("  파일검증 완료")
    return True
