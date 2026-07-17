import sys, asyncio, logging
sys.stdout.reconfigure(encoding="utf-8")
logger = logging.getLogger("douyin_playwright")
_browser = None
_context = None
_playwright = None

async def _ensure_browser():
    global _browser, _context, _playwright
    if _browser is None:
        from playwright.async_api import async_playwright
        _playwright = await async_playwright().start()
        _browser = await _playwright.chromium.launch(headless=True)
        _context = await _browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
            locale="zh-CN",
            viewport={"width": 1280, "height": 720},
        )
        logger.info("Playwright browser started")
    return _context

async def async_parse(url: str) -> dict:
    try:
        ctx = await _ensure_browser()
        page = await ctx.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=20000)
            await page.wait_for_timeout(3000)
            result = await page.evaluate("""() => { const sources = document.querySelectorAll("source"); for (const s of sources) { if (s.src && s.src.includes("video_mp4")) return s.src; } const v = document.querySelector("video"); return v ? v.src : ""; }""")
            title = await page.title()
            if result and "douyinvod" in result:
                cover = await page.evaluate("""() => { const v = document.querySelector("video"); return v ? (v.poster || "") : ""; }""")
                return {"success": True, "data": {"title": (title or "").strip() or "抖音视频", "video_url": result, "cover_url": cover or "", "duration": 0, "platform": "douyin"}}
            else:
                return {"success": False, "error": "未找到视频地址"}
        finally:
            await page.close()
    except Exception as e:
        return {"success": False, "error": f"Playwright解析失败: {str(e)[:100]}"}

def parse(url: str) -> dict:
    """同步入口，兼容多线程环境"""
    try:
        loop = asyncio.get_running_loop()
        # Already in a running event loop - create a new one
        import threading
        result = {}
        def _run():
            new_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(new_loop)
            try:
                r = new_loop.run_until_complete(async_parse(url))
                result["r"] = r
            finally:
                new_loop.close()
        t = threading.Thread(target=_run, daemon=True)
        t.start()
        t.join(timeout=25)
        return result.get("r") or {"success": False, "error": "Playwright解析超时"}
    except RuntimeError:
        # No running loop - use current or new
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(async_parse(url))
        finally:
            loop.close()

