import asyncio
from playwright.async_api import async_playwright

async def run():
    async with async_playwright() as p:
        try:
            browser = await p.chromium.connect_over_cdp('http://localhost:9222')
            page = browser.contexts[0].pages[0]
            print("페이지 새로고침 중...")
            await page.reload()
            print("페이지 새로고침 완료.")
        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(run())
