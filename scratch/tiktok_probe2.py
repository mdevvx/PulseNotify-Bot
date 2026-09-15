import asyncio, json, os
from playwright.async_api import async_playwright

OUT = os.path.join(os.path.dirname(__file__), "tiktok_universal_data.json")

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800},
        )
        page = await context.new_page()
        await page.goto("https://www.tiktok.com/@tiktok", wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(4000)
        raw = await page.evaluate("""
            () => {
                const el = document.getElementById('__UNIVERSAL_DATA_FOR_REHYDRATION__');
                return el ? el.textContent : null;
            }
        """)
        await browser.close()
        if raw is None:
            print("NOT FOUND")
            return
        data = json.loads(raw)
        user_detail = data["__DEFAULT_SCOPE__"]["webapp.user-detail"]
        print("user-detail KEYS:", list(user_detail.keys()))
        with open(OUT, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        print("Saved full JSON to", OUT)

asyncio.run(main())
