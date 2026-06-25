"""Playwright-backed BrowserEngine. Mechanics ported from the former GreenhouseSubmitter.

Two acquisition modes:
  * launch  — Chromium with an optional persistent user-data-dir (default via the factory).
  * cdp     — attach to the user's already-running real Chrome over CDP (close() never
              closes the user's browser in this mode).

Field-reading/selectors are verified against the live DOM (not unit-tested, per the
ChromeSubmitter precedent); the pure mapping logic lives in tests/test_form_fill.py and the
orchestration in tests/test_apply_driver.py.
"""

from __future__ import annotations

import logging
import os
import re

from backend.platforms.browser.engine import BrowserEngine, PageSnapshot, SelectOutcome
from backend.platforms.form_fill import FormField

logger = logging.getLogger(__name__)

# Holds (playwright, browser, page) for kept-open assisted windows so they aren't GC'd.
_OPEN_ASSISTED_SESSIONS: list[tuple[object, object, object]] = []

# JS run in-page to read labeled controls. Greenhouse associates labels via label[for=id].
_READ_FIELDS_JS = r"""
() => {
  const labelFor = (el) => {
    if (el.id) { const l = document.querySelector('label[for="'+CSS.escape(el.id)+'"]'); if (l) return l.innerText.trim(); }
    if (el.getAttribute('aria-label')) return el.getAttribute('aria-label');
    const lb = el.getAttribute('aria-labelledby');
    if (lb) { const l = document.getElementById(lb); if (l) return l.innerText.trim(); }
    const wl = el.closest('label'); if (wl) return wl.innerText.trim();
    return '';
  };
  const out = [];
  const scoped = document.querySelectorAll('form input, form textarea, form select');
  const els = scoped.length ? scoped : document.querySelectorAll('input, textarea, select');
  for (const el of els) {
    const type = (el.type || '').toLowerCase();
    if (['hidden','submit','button','reset'].includes(type)) continue;
    if (el.offsetParent === null) continue;
    if ((el.name || '') === 'g-recaptcha-response') continue;
    if ((el.className || '').toString().includes('requiredInput')) continue;
    const tag = el.tagName.toLowerCase();
    const role = el.getAttribute('role') || '';
    let label = labelFor(el).replace(/\s+/g, ' ').replace(/\*$/, '').trim();
    const kind = type === 'file' ? 'file'
               : role === 'combobox' ? 'combobox'
               : tag === 'textarea' ? 'textarea'
               : tag === 'select' ? 'select' : 'text';
    if (kind === 'file' && (label === '' || label.toLowerCase() === 'attach')) label = (el.id || 'attachment');
    const required = !!el.required || el.getAttribute('aria-required') === 'true';
    out.push({label, kind, required, id: el.id || '', name: el.name || '', options: []});
  }
  return out;
}
"""


class PlaywrightEngine(BrowserEngine):
    def __init__(self, *, mode: str = "launch", headless: bool = False,
                 fill_delay_ms: int = 300, keep_open: bool = False,
                 cdp_url: str | None = None, user_data_dir: str | None = None) -> None:
        self.mode = mode
        self.headless = headless
        self.fill_delay_ms = fill_delay_ms
        self.keep_open = keep_open
        self.cdp_url = cdp_url
        self.user_data_dir = user_data_dir
        self._p = None
        self._browser = None
        self._page = None

    async def goto(self, url: str) -> None:
        from playwright.async_api import async_playwright

        self._p = await async_playwright().start()
        if self.mode == "cdp":
            self._browser = await self._p.chromium.connect_over_cdp(self.cdp_url)
            ctx = (self._browser.contexts[0] if self._browser.contexts
                   else await self._browser.new_context())
            self._page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        elif self.user_data_dir:
            self._browser = await self._p.chromium.launch_persistent_context(
                self.user_data_dir, headless=self.headless)
            self._page = (self._browser.pages[0] if self._browser.pages
                          else await self._browser.new_page())
        else:
            self._browser = await self._p.chromium.launch(headless=self.headless)
            self._page = await self._browser.new_page()

        page = self._page
        await page.goto(url, wait_until="domcontentloaded", timeout=45_000)
        await page.wait_for_timeout(2500)
        # The engine is host-agnostic (the apply driver resolves Ashby job URLs to their
        # `/application` form before calling goto), so we key the extra client-side render
        # wait off the `/application` suffix rather than the source's rewrite-detected check.
        if url.split("?", 1)[0].rstrip("/").endswith("/application"):
            try:
                await page.wait_for_selector("input, textarea", timeout=8000)
            except Exception:  # noqa: BLE001
                pass
            await page.wait_for_timeout(1500)

    async def snapshot(self) -> PageSnapshot:
        page = self._page
        raw = await page.evaluate(_READ_FIELDS_JS)
        fields = [FormField(label=r["label"], required=r["required"], kind=r["kind"],
                            id=r["id"], name=r["name"], options=r.get("options", []))
                  for r in raw]
        for f in fields:
            if f.kind == "combobox" and f.key:
                f.options = await self._read_combobox_options(f)
        # Dismiss any stray open dropdown overlay so later fills aren't blocked.
        try:
            await page.keyboard.press("Escape")
            await page.evaluate("() => document.activeElement && document.activeElement.blur()")
        except Exception:  # noqa: BLE001
            pass
        return PageSnapshot(fields=fields)

    async def fill(self, key: str, value: str) -> None:
        try:
            loc = self._key_locator(key)
            await loc.first.fill(value, timeout=5_000)
            await self._page.wait_for_timeout(self.fill_delay_ms)
        except Exception:  # noqa: BLE001 — a single field miss isn't fatal
            logger.warning("could not fill %s", key)

    async def select(self, key: str, option: str) -> SelectOutcome:
        try:
            loc = self._key_locator(key)
            await loc.first.click(timeout=5_000)
            await self._page.wait_for_timeout(self.fill_delay_ms)
            cid = key[1:] if key.startswith("#") else ""
            if cid:
                exact = re.compile(rf"^\s*{re.escape(option)}\s*$")
                opt = self._page.locator(f'[id^="react-select-{cid}-option"]',
                                         has_text=exact).first
                await opt.click(timeout=5_000)
            else:
                await self._page.get_by_role("option", name=option,
                                             exact=True).first.click(timeout=5_000)
            await self._page.wait_for_timeout(self.fill_delay_ms)
            return SelectOutcome(ok=True, available_options=[])
        except Exception:  # noqa: BLE001
            logger.warning("could not select %s for %s", option, key)
            try:
                await self._page.keyboard.press("Escape")
            except Exception:  # noqa: BLE001
                pass
            return SelectOutcome(ok=False, available_options=[])

    async def upload(self, key: str, path: str) -> bool:
        try:
            loc = self._key_locator(key)
            await loc.first.set_input_files(path, timeout=5_000)
            base = os.path.basename(path)
            try:
                await self._page.wait_for_function(
                    "(n) => document.body.innerText.includes(n)", arg=base, timeout=5_000)
                return True
            except Exception:  # noqa: BLE001 — filename never appeared -> unconfirmed
                logger.warning("file %s upload unconfirmed (filename %s not shown)", key, base)
                return False
        except Exception:  # noqa: BLE001
            logger.warning("could not upload %s", key)
            return False

    async def click(self, key: str) -> None:
        # Unlike fill()/select(), click() propagates errors — callers that need a
        # best-effort click should guard it themselves.
        loc = self._key_locator(key)
        await loc.first.click(timeout=5_000)

    async def has_visible_captcha(self) -> bool:
        for sel in ("iframe[src*='bframe']", "iframe[title*='challenge']"):
            loc = self._page.locator(sel)
            try:
                if await loc.count() > 0 and await loc.first.is_visible():
                    return True
            except Exception:  # noqa: BLE001
                continue
        return False

    async def screenshot(self) -> bytes:
        return await self._page.screenshot()

    async def await_human(self, reason: str) -> None:
        logger.info("awaiting human: %s", reason)
        if self.keep_open and not self.headless and self._page is not None:
            try:
                await self._page.bring_to_front()
            except Exception:  # noqa: BLE001
                pass
            _OPEN_ASSISTED_SESSIONS.append((self._p, self._browser, self._page))
            return  # leave the browser open for the human to review + submit
        await self.close()

    async def close(self) -> None:
        try:
            # In cdp mode the browser is the user's real Chrome — never close it.
            if self._browser is not None and self.mode != "cdp":
                await self._browser.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            if self._p is not None:
                await self._p.stop()
        except Exception:  # noqa: BLE001
            pass
        self._browser = None
        self._p = None
        self._page = None

    # --- helpers -------------------------------------------------------------

    def _key_locator(self, key: str, label: str | None = None):
        """`#<id>` → `[id="<id>"]` (id may start with a digit); else label text."""
        if key.startswith("#"):
            return self._page.locator(f'[id="{key[1:]}"]')
        return self._page.get_by_label(label if label is not None else key, exact=False)

    async def _read_combobox_options(self, field) -> list[str]:
        page = self._page
        try:
            loc = self._key_locator(field.key, field.label)
            await loc.first.click(timeout=5_000)
            await page.wait_for_timeout(self.fill_delay_ms)
            if field.id:
                opts = await page.locator(
                    f'[id^="react-select-{field.id}-option"]').all_inner_texts()
            else:
                opts = await page.locator(
                    '[class*="select__menu"] [role="option"]').all_inner_texts()
            await page.keyboard.press("Escape")
            await page.wait_for_timeout(self.fill_delay_ms)
            return [o.strip() for o in opts if o.strip()]
        except Exception:  # noqa: BLE001 — unreadable dropdown stays unfilled -> escalates
            logger.warning("could not read options for combobox %s", field.label)
            try:
                await page.keyboard.press("Escape")
            except Exception:  # noqa: BLE001
                pass
            return []
