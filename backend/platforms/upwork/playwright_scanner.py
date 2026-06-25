"""Playwright-based scanner for Upwork contract listings.

Navigates Upwork search pages headlessly, extracts structured listing data
from the DOM, and returns ContractCreate models for ingestion.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable
from urllib.parse import urlencode

from playwright.async_api import async_playwright, Page

from backend.core.models import ContractCreate

logger = logging.getLogger(__name__)

# Countries for location matching
_COUNTRIES = [
    "United States", "United Kingdom", "Canada", "Germany", "France", "Netherlands",
    "Australia", "India", "Pakistan", "Philippines", "Brazil", "Spain", "Italy",
    "Poland", "Romania", "Ukraine", "Argentina", "Mexico", "Israel", "Singapore",
    "Ireland", "Sweden", "Switzerland", "Japan", "South Korea", "Turkey", "Egypt",
    "Nigeria", "South Africa", "Kenya", "Colombia", "Chile",
]


async def _extract_jobs_from_page(page: Page) -> list[dict]:
    """Extract job listing data from an Upwork search results page."""
    return await page.evaluate("""() => {
        const articles = document.querySelectorAll('article.job-tile');
        const jobs = [];

        articles.forEach(card => {
            const titleLink = card.querySelector('a[href*="_~"]');
            if (!titleLink) return;

            const href = titleLink.getAttribute('href');
            const idMatch = href.match(/_~(\\d+)/);
            if (!idMatch) return;

            const text = card.innerText;
            const title = titleLink.textContent.trim();

            // Budget
            const hourlyMatch = text.match(/\\$(\\d[\\d,.]+)\\s*-\\s*\\$(\\d[\\d,.]+)/);
            const fixedMatch = text.match(/Est\\.\\s*budget:\\s*\\$(\\d[\\d,.]+)/i);
            const isHourly = text.includes('Hourly:') || (text.includes('Hourly') && !fixedMatch);

            // Client info
            const spentMatch = text.match(/\\$(\\d[\\d,.]*[KMB]?\\+?)\\s*spent/i);
            const hireMatch = text.match(/(\\d+)%\\s*hire/i);

            // Location
            const countries = """ + str(_COUNTRIES) + """;
            let location = null;
            for (const c of countries) {
                if (text.includes(c)) { location = c; break; }
            }

            // Proposals
            const propMatch = text.match(/Proposals:\\s*(.*?)$/im);

            // Duration
            const durMatch = text.match(/Est\\.\\s*time:\\s*(.*?)$/im);

            // Skills from skill tag links
            const skillEls = card.querySelectorAll('a[href*="ontology_skill_uid"]');
            const skills = Array.from(skillEls).map(s => s.textContent.trim()).filter(s => s.length > 0);

            // Description
            const descEl = card.querySelector('[data-test="job-description-text"]');
            let desc = '';
            if (descEl) {
                desc = descEl.textContent.trim();
            } else {
                const lines = text.split('\\n').map(l => l.trim()).filter(l => l.length > 80);
                desc = lines[0] || title;
            }

            // Parse spent as a number
            let spentNum = 0;
            if (spentMatch) {
                let s = spentMatch[1].replace(/[+$,]/g, '');
                if (s.includes('K')) spentNum = parseFloat(s.replace('K','')) * 1000;
                else if (s.includes('M')) spentNum = parseFloat(s.replace('M','')) * 1000000;
                else spentNum = parseFloat(s) || 0;
            }

            // Parse proposals count
            let propCount = null;
            if (propMatch) {
                const p = propMatch[1].trim();
                const numMatch = p.match(/^(\\d+)/);
                if (numMatch) propCount = parseInt(numMatch[1]);
            }

            jobs.push({
                title,
                external_id: '~' + idMatch[1],
                url: 'https://www.upwork.com/jobs/~' + idMatch[1],
                description: desc.substring(0, 1000),
                budget_min: hourlyMatch ? parseFloat(hourlyMatch[1].replace(/,/g,'')) : (fixedMatch ? parseFloat(fixedMatch[1].replace(/,/g,'')) : null),
                budget_max: hourlyMatch ? parseFloat(hourlyMatch[2].replace(/,/g,'')) : (fixedMatch ? parseFloat(fixedMatch[1].replace(/,/g,'')) : null),
                contract_type: isHourly ? 'hourly' : 'fixed',
                duration: durMatch ? durMatch[1].trim() : null,
                skills,
                proposals_count: propCount,
                client_total_spent: spentNum,
                client_location: location,
                client_hire_rate: hireMatch ? parseInt(hireMatch[1]) / 100 : null,
            });
        });

        return jobs;
    }""")


async def _extract_jobs_from_best_matches(page: Page) -> list[dict]:
    """Extract job listing data from Upwork's Best Matches feed.

    Best Matches uses a different DOM layout than search results.
    Scrolls down to lazy-load additional listings.
    """
    # Scroll down multiple times to load more results
    for _ in range(5):
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await page.wait_for_timeout(1500)

    return await page.evaluate("""() => {
        const jobs = [];
        const jobLinks = document.querySelectorAll('a[href*="/jobs/"][href*="~"]');
        const seen = new Set();

        jobLinks.forEach(link => {
            const href = link.getAttribute('href');
            const idMatch = href.match(/~(\\d+)/);
            if (!idMatch) return;

            const externalId = '~' + idMatch[1];
            if (seen.has(externalId)) return;
            seen.add(externalId);

            const title = link.textContent.trim();
            if (title.length < 15) return;

            let container = link.closest('article') || link.closest('[data-test]') || link.parentElement?.parentElement?.parentElement?.parentElement;
            if (!container) return;

            const text = container.innerText || '';

            const hourlyMatch = text.match(/\\$(\\d[\\d,.]+)\\s*-\\s*\\$(\\d[\\d,.]+)/);
            const fixedMatch = text.match(/Est\\.\\s*budget:\\s*\\$(\\d[\\d,.]+)/i)
                             || text.match(/\\$(\\d[\\d,.]+)\\s*Fixed/i);
            const isHourly = text.includes('Hourly') && !fixedMatch;

            const spentMatch = text.match(/\\$(\\d[\\d,.]*[KMB]?\\+?)\\s*spent/i);
            const hireMatch = text.match(/(\\d+)%\\s*hire/i);

            const propMatch = text.match(/Proposals:\\s*(.*?)$/im)
                            || text.match(/(\\d+)\\s*to\\s*(\\d+)\\s*proposals/i);

            const skillEls = container.querySelectorAll('a[href*="ontology_skill_uid"]');
            const skills = Array.from(skillEls).map(s => s.textContent.trim()).filter(s => s.length > 0 && s.length < 50);

            const descEl = container.querySelector('[data-test="job-description-text"]');
            let desc = '';
            if (descEl) {
                desc = descEl.textContent.trim();
            } else {
                const lines = text.split('\\n').map(l => l.trim()).filter(l => l.length > 80);
                desc = lines[0] || title;
            }

            let spentNum = 0;
            if (spentMatch) {
                let s = spentMatch[1].replace(/[+$,]/g, '');
                if (s.includes('K')) spentNum = parseFloat(s.replace('K','')) * 1000;
                else if (s.includes('M')) spentNum = parseFloat(s.replace('M','')) * 1000000;
                else spentNum = parseFloat(s) || 0;
            }

            let propCount = null;
            if (propMatch) {
                const p = propMatch[1] || propMatch[0];
                const numMatch = p.match(/(\\d+)/);
                if (numMatch) propCount = parseInt(numMatch[1]);
            }

            jobs.push({
                title,
                external_id: externalId,
                url: 'https://www.upwork.com/jobs/' + externalId,
                description: desc.substring(0, 1000),
                budget_min: hourlyMatch ? parseFloat(hourlyMatch[1].replace(/,/g,'')) : (fixedMatch ? parseFloat(fixedMatch[1].replace(/,/g,'')) : null),
                budget_max: hourlyMatch ? parseFloat(hourlyMatch[2].replace(/,/g,'')) : (fixedMatch ? parseFloat(fixedMatch[1].replace(/,/g,'')) : null),
                contract_type: isHourly ? 'hourly' : 'fixed',
                skills,
                proposals_count: propCount,
                client_total_spent: spentNum,
                client_hire_rate: hireMatch ? parseInt(hireMatch[1]) / 100 : null,
            });
        });

        return jobs;
    }""")


def _build_search_url(search: dict) -> str:
    """Build an Upwork search URL from a search config dict."""
    base = "https://www.upwork.com/nx/search/jobs/"
    params: dict[str, str] = {"sort": "recency"}

    query = search.get("query", "")
    if query:
        params["q"] = query

    return base + "?" + urlencode(params)


async def run_playwright_scan(
    search_config: dict,
    on_contract: Callable[[ContractCreate], None],
    *,
    headless: bool = False,
) -> int:
    """Run a Playwright-based scan across all configured searches.

    Defaults to non-headless mode because Upwork uses Cloudflare bot
    detection that blocks headless browsers. In non-headless mode the
    user can pass the CAPTCHA challenge once, then the scanner continues.

    Returns the total number of contracts found.
    """
    searches = search_config.get("searches", [])
    if not searches:
        searches = [search_config]

    total_found = 0

    async with async_playwright() as p:
        # Use the system Chrome with a persistent profile so Cloudflare
        # sessions and Upwork login cookies carry over between scans.
        user_data_dir = str(Path.home() / ".config" / "contract-finder-chrome")
        context = await p.chromium.launch_persistent_context(
            user_data_dir,
            headless=headless,
            channel="chrome",
            args=["--disable-blink-features=AutomationControlled"],
            viewport={"width": 1400, "height": 900},
            java_script_enabled=True,
        )
        # Remove webdriver flag to reduce bot detection
        await context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        page = context.pages[0] if context.pages else await context.new_page()

        # ── Scrape Best Matches feed first ──────────────────────────────
        best_matches_url = "https://www.upwork.com/nx/find-work/best-matches"
        logger.info("Scanning Best Matches: %s", best_matches_url)

        try:
            await page.goto(best_matches_url, wait_until="domcontentloaded", timeout=30000)

            page_title = await page.title()
            if "challenge" in page_title.lower() or "just a moment" in page_title.lower():
                logger.info("  Cloudflare challenge detected — waiting for user to resolve...")
                await page.wait_for_selector('a[href*="/jobs/"]', timeout=120000)
            else:
                await page.wait_for_selector('a[href*="/jobs/"]', timeout=20000)

            raw_best = await _extract_jobs_from_best_matches(page)
            logger.info("  Found %d Best Matches listings", len(raw_best))

            for job in raw_best:
                contract = ContractCreate(
                    platform="upwork",
                    external_id=job["external_id"],
                    url=job["url"],
                    title=job["title"],
                    description=job.get("description"),
                    skills_required=job.get("skills", []),
                    budget_min=job.get("budget_min"),
                    budget_max=job.get("budget_max"),
                    contract_type=job.get("contract_type"),
                    proposals_count=job.get("proposals_count"),
                    client_hire_rate=job.get("client_hire_rate"),
                    client_total_spent=job.get("client_total_spent"),
                    source="best_matches",
                    posted_at=datetime.now(UTC),
                    fetched_at=datetime.now(UTC),
                )
                on_contract(contract)
                total_found += 1

            await page.wait_for_timeout(3000)

        except Exception as exc:
            logger.warning("Failed to scrape Best Matches: %s", str(exc)[:200])

        for search in searches:
            search_name = search.get("name", search.get("query", "unknown"))
            url = _build_search_url(search)
            logger.info("Scanning: %s -> %s", search_name, url)

            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)

                # Check for Cloudflare challenge and wait for user to resolve
                page_title = await page.title()
                if "challenge" in page_title.lower() or "just a moment" in page_title.lower():
                    logger.info("  Cloudflare challenge detected — waiting for user to resolve...")
                    await page.wait_for_selector("article.job-tile", timeout=120000)

                # Wait for job tiles to render
                await page.wait_for_selector("article.job-tile", timeout=20000)
            except Exception as exc:
                logger.warning("Failed to load search page: %s (%s)", search_name, str(exc)[:100])
                continue

            raw_jobs = await _extract_jobs_from_page(page)
            logger.info("  Found %d listings for '%s'", len(raw_jobs), search_name)

            for job in raw_jobs:
                contract = ContractCreate(
                    platform="upwork",
                    external_id=job["external_id"],
                    url=job["url"],
                    title=job["title"],
                    description=job.get("description"),
                    skills_required=job.get("skills", []),
                    budget_min=job.get("budget_min"),
                    budget_max=job.get("budget_max"),
                    contract_type=job.get("contract_type"),
                    duration=job.get("duration"),
                    proposals_count=job.get("proposals_count"),
                    client_hire_rate=job.get("client_hire_rate"),
                    client_total_spent=job.get("client_total_spent"),
                    client_location=job.get("client_location"),
                    source="search",
                    posted_at=datetime.now(UTC),
                    fetched_at=datetime.now(UTC),
                )
                on_contract(contract)
                total_found += 1

            # Pause between searches to avoid rate limiting
            if len(searches) > 1:
                await page.wait_for_timeout(3000)

        await context.close()

    return total_found
