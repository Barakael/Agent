import concurrent.futures
import logging
import re
from typing import Any, Callable, Dict, Optional, TypeVar
from urllib.parse import quote_plus, urlparse

from playwright.sync_api import Browser, BrowserContext, Page, Playwright, sync_playwright

from config import settings

logger = logging.getLogger(__name__)

T = TypeVar("T")
_BROWSER_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="wayda-browser")


def run_browser_task(action: Callable[[], T]) -> T:
    """Run Playwright sync code outside FastAPI's asyncio event loop."""
    future = _BROWSER_EXECUTOR.submit(action)
    return future.result(timeout=settings.BROWSER_TIMEOUT + 90)


class BrowserAutomation:
    """Playwright-backed browser for typing, clicking, and media playback."""

    _playwright: Optional[Playwright] = None
    _browser: Optional[Browser] = None
    _context: Optional[BrowserContext] = None
    _page: Optional[Page] = None

    def navigate(self, url: str) -> Dict[str, Any]:
        page = self._ensure_page()
        page.goto(url, wait_until="domcontentloaded", timeout=self._timeout_ms())
        return {
            "url": page.url,
            "title": page.title(),
            "message": f"Navigated to {page.url}.",
        }

    def type_text(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        page = self._page_for(payload)
        selector = str(payload.get("selector", "")).strip()
        text = str(payload.get("text", ""))
        if not selector:
            raise ValueError("browser.type requires a CSS 'selector'.")
        if text == "":
            raise ValueError("browser.type requires 'text' to type.")

        locator = page.locator(selector).first
        locator.wait_for(state="visible", timeout=self._timeout_ms())
        locator.click()
        locator.fill(text)
        if payload.get("press_enter", True):
            locator.press("Enter")

        page.wait_for_timeout(800)
        return {
            "url": page.url,
            "selector": selector,
            "typed": text,
            "title": page.title(),
            "message": f"Typed into {selector} on {page.url}.",
        }

    def click(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        page = self._page_for(payload)
        selector = str(payload.get("selector", "")).strip()
        if not selector:
            raise ValueError("browser.click requires a CSS 'selector'.")

        locator = page.locator(selector).first
        locator.wait_for(state="visible", timeout=self._timeout_ms())
        label = locator.inner_text(timeout=2000) if payload.get("capture_label", True) else ""
        locator.click()
        page.wait_for_timeout(int(payload.get("wait_ms", 1200)))

        return {
            "url": page.url,
            "selector": selector,
            "clicked_label": label[:200] if label else None,
            "title": page.title(),
            "message": f"Clicked {selector} on {page.url}.",
        }

    def search(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        engine = str(payload.get("engine", "google")).strip().lower()
        query = str(payload.get("query", "")).strip()
        if not query:
            raise ValueError("browser.search requires a 'query'.")

        if engine == "youtube":
            return self._search_youtube(query, bool(payload.get("play_first", False)))
        if engine == "google":
            return self._search_google(query)

        raise ValueError("browser.search engine must be 'youtube' or 'google'.")

    def _search_google(self, query: str) -> Dict[str, Any]:
        page = self._ensure_page()
        page.goto("https://www.google.com", wait_until="domcontentloaded", timeout=self._timeout_ms())
        self._dismiss_consent(page)

        search_box = page.locator('textarea[name="q"], input[name="q"]').first
        search_box.wait_for(state="visible", timeout=self._timeout_ms())
        search_box.fill(query)
        search_box.press("Enter")
        page.wait_for_load_state("domcontentloaded", timeout=self._timeout_ms())

        return {
            "engine": "google",
            "query": query,
            "url": page.url,
            "title": page.title(),
            "message": f"Searched Google for '{query}'.",
        }

    def _search_youtube(self, query: str, play_first: bool) -> Dict[str, Any]:
        page = self._ensure_page()
        search_url = f"https://www.youtube.com/results?search_query={quote_plus(query)}"
        page.goto(search_url, wait_until="domcontentloaded", timeout=self._timeout_ms())
        self._dismiss_consent(page)

        video_links = page.locator("ytd-video-renderer a#video-title")
        video_links.first.wait_for(state="attached", timeout=self._timeout_ms())

        result: Dict[str, Any] = {
            "engine": "youtube",
            "query": query,
            "url": page.url,
            "title": page.title(),
            "message": f"Searched YouTube for '{query}'.",
        }

        if not play_first:
            return result

        video_link = video_links.first
        video_title = video_link.inner_text(timeout=5000).strip()
        video_link.click()
        page.wait_for_url(re.compile(r"youtube\.com/watch"), timeout=self._timeout_ms())
        self._ensure_youtube_playing(page)

        result.update(
            {
                "played": True,
                "video_title": video_title,
                "video_url": page.url,
                "message": f"Searched YouTube for '{query}' and started playing '{video_title}'.",
            }
        )
        return result

    def _ensure_youtube_playing(self, page: Page) -> None:
        page.wait_for_selector("video.html5-main-video", timeout=self._timeout_ms())
        page.bring_to_front()
        self._dismiss_youtube_overlays(page)
        page.wait_for_timeout(1200)

        if not self._youtube_is_paused(page):
            logger.info("YouTube video already playing; skipping play controls.")
            return

        # Only use the large overlay play button — never click the main pause/play toggle.
        try:
            large_play = page.locator("button.ytp-large-play-button").first
            if large_play.is_visible(timeout=2000):
                large_play.click()
                page.wait_for_timeout(800)
                if not self._youtube_is_paused(page):
                    return
        except Exception:
            pass

        page.evaluate(
            """async () => {
                const video = document.querySelector('video.html5-main-video');
                if (video && video.paused) {
                    try { await video.play(); } catch (_) {}
                }
            }"""
        )
        page.wait_for_timeout(800)

        if self._youtube_is_paused(page):
            page.keyboard.press("k")

    @staticmethod
    def _youtube_is_paused(page: Page) -> bool:
        return bool(
            page.evaluate(
                """() => {
                    const video = document.querySelector('video.html5-main-video');
                    return video ? video.paused : true;
                }"""
            )
        )

    @staticmethod
    def _dismiss_youtube_overlays(page: Page) -> None:
        patterns = [
            re.compile(r"reject all", re.I),
            re.compile(r"no thanks", re.I),
            re.compile(r"skip", re.I),
            re.compile(r"not now", re.I),
        ]
        for pattern in patterns:
            try:
                page.get_by_role("button", name=pattern).click(timeout=800)
            except Exception:
                continue

    def _page_for(self, payload: Dict[str, Any]) -> Page:
        url = str(payload.get("url", "")).strip()
        page = self._ensure_page()
        if url:
            if not url.startswith(("http://", "https://")):
                url = f"https://{url}"
            parsed = urlparse(url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError("Invalid URL for browser action.")
            if page.url != url:
                page.goto(url, wait_until="domcontentloaded", timeout=self._timeout_ms())
        return page

    def _ensure_page(self) -> Page:
        if self._page and not self._page.is_closed():
            return self._page

        if self._playwright is None:
            self._playwright = sync_playwright().start()

        if self._browser is None:
            launch_kwargs: Dict[str, Any] = {
                "headless": settings.BROWSER_HEADLESS,
                "args": ["--autoplay-policy=no-user-gesture-required"],
            }
            if settings.BROWSER_CHANNEL:
                launch_kwargs["channel"] = settings.BROWSER_CHANNEL
            try:
                self._browser = self._playwright.chromium.launch(**launch_kwargs)
            except Exception:
                logger.warning("Failed to launch %s; falling back to bundled Chromium.", settings.BROWSER_CHANNEL)
                self._browser = self._playwright.chromium.launch(headless=settings.BROWSER_HEADLESS)

        if self._context is None:
            self._context = self._browser.new_context(
                viewport={"width": 1280, "height": 800},
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
                ),
            )

        if self._context.pages:
            self._page = self._context.pages[-1]
        else:
            self._page = self._context.new_page()
        return self._page

    @staticmethod
    def _dismiss_consent(page: Page) -> None:
        patterns = [
            re.compile(r"accept all", re.I),
            re.compile(r"agree", re.I),
            re.compile(r"I agree", re.I),
        ]
        for pattern in patterns:
            try:
                page.get_by_role("button", name=pattern).click(timeout=1500)
                return
            except Exception:
                continue

    @staticmethod
    def _timeout_ms() -> int:
        return int(settings.BROWSER_TIMEOUT) * 1000


_browser_automation: Optional[BrowserAutomation] = None


def get_browser_automation() -> BrowserAutomation:
    global _browser_automation
    if _browser_automation is None:
        _browser_automation = BrowserAutomation()
    return _browser_automation
