"""비동기 폴링/대기 공통 유틸리티

Playwright page.evaluate 기반 조건 대기, 새 탭 감지, DOM 요소 대기 등
반복되는 폴링 패턴을 공통 함수로 제공.
"""

import asyncio


async def wait_for_element(page, element_id, timeout=10, interval=1):
    """DOM 요소가 나타날 때까지 대기

    Args:
        page: Playwright page
        element_id: document.getElementById로 찾을 요소 ID
        timeout: 최대 대기 시간(초)
        interval: 폴링 간격(초)

    Returns:
        bool: 요소 발견 여부
    """
    for i in range(timeout):
        try:
            found = await page.evaluate(
                '(elId) => !!document.getElementById(elId)', element_id
            )
            if found:
                return True
        except Exception:
            pass  # 페이지 이동 중 evaluate 실패 — 재시도
        await asyncio.sleep(interval)
    return False


async def wait_for_new_tab(context, url_pattern, timeout=10, interval=1):
    """새 브라우저 탭이 열릴 때까지 대기

    context.pages 중 이전에 없던 새 탭에서 url_pattern이 매칭되는 것을 찾음.

    Args:
        context: Browser context
        url_pattern: 탭 URL에 포함되어야 할 문자열
        timeout: 최대 대기 시간(초)
        interval: 폴링 간격(초)

    Returns:
        tuple[Page | None, set]: (발견된 새 탭, 기존 탭 ID 집합)
    """
    pages_before = set(id(pg) for pg in context.pages)

    for i in range(timeout):
        await asyncio.sleep(interval)
        for pg in context.pages:
            try:
                if id(pg) not in pages_before and url_pattern in pg.url:
                    return pg, pages_before
            except Exception:
                continue

    return None, pages_before


async def wait_for_new_tab_any(context, url_patterns, timeout=10, interval=1):
    """여러 URL 패턴 중 하나에 매칭되는 새 탭 대기

    Args:
        context: Browser context
        url_patterns: 탭 URL에 포함되어야 할 문자열 목록
        timeout: 최대 대기 시간(초)
        interval: 폴링 간격(초)

    Returns:
        tuple[Page | None, set]: (발견된 새 탭, 기존 탭 ID 집합)
    """
    pages_before = set(id(pg) for pg in context.pages)

    for i in range(timeout):
        await asyncio.sleep(interval)
        for pg in context.pages:
            try:
                if id(pg) not in pages_before:
                    if any(pat in pg.url for pat in url_patterns):
                        return pg, pages_before
            except Exception:
                continue

    return None, pages_before
