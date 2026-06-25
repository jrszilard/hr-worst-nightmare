"""Open a non-GLA posting in a kept-open headed browser for manual apply. No fill, no submit."""

from __future__ import annotations

import logging

from backend.core.platform import SubmitResult

logger = logging.getLogger(__name__)

# Holds (playwright, browser, page) so kept-open windows aren't garbage-collected.
_OPEN_POSTING_SESSIONS: list[tuple[object, object, object]] = []


async def open_posting_for_review(*, url: str, headless: bool = False) -> SubmitResult:
    """Navigate to the posting and leave the window open for the human to apply manually."""
    from playwright.async_api import async_playwright

    p = await async_playwright().start()
    browser = await p.chromium.launch(headless=headless)
    page = await browser.new_page()
    keep_open = False
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=45_000)
        if not headless:
            try:
                await page.bring_to_front()
            except Exception:  # noqa: BLE001
                pass
            keep_open = True
            _OPEN_POSTING_SESSIONS.append((p, browser, page))
        return SubmitResult(
            filled=False, submitted=False,
            detail="opened posting for manual apply; paste the generated cover letter and submit",
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("failed to open posting %s", url)
        return SubmitResult(filled=False, submitted=False, detail=f"error: {exc}")
    finally:
        if not keep_open:
            await browser.close()
            await p.stop()
