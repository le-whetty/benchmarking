"""
Wellfound (wellfound.com, formerly AngelList Talent) scraper.

Wellfound is JS-rendered — we use Playwright. It has a structured
job search with location and role filters. Salary disclosure is common
for funded startups (often USD, occasionally AUD/NZD).

Search strategy: hit the public /jobs search filtered to ANZ locations,
extract the embedded JSON payload from the page (Wellfound inlines job
data as window.__PRELOADED_STATE__ or similar). Fall back to card parsing.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from scraper.schema import Listing, make_id
from scraper.salary_parser import parse_salary
from scraper.normaliser import (
    classify_title,
    extract_city,
    extract_scope_signals,
    infer_company_size,
    infer_country,
)
from scraper.sources.seek_nz import _cache_get, _cache_set

logger = logging.getLogger(__name__)

SOURCE = "wellfound"
BASE_URL = "https://wellfound.com"
REQUEST_DELAY = 3.0

# (search query, display location, country hint)
SEARCH_CONFIG = [
    ("revenue operations", "New Zealand", "NZ"),
    ("revenue operations", "Australia", "AU"),
    ("gtm operations", "New Zealand", "NZ"),
    ("gtm operations", "Australia", "AU"),
    ("sales operations", "New Zealand", "NZ"),
    ("sales operations", "Australia", "AU"),
    ("head of operations", "New Zealand", "NZ"),
    ("head of operations", "Australia", "AU"),
]


def _build_search_url(query: str, location: str) -> str:
    from urllib.parse import quote_plus
    q = quote_plus(query)
    loc = quote_plus(location)
    return f"{BASE_URL}/jobs?q={q}&l={loc}"


async def _fetch_with_playwright(url: str) -> Optional[str]:
    try:
        from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout
    except ImportError:
        logger.warning("[wellfound] Playwright not installed — skipping source")
        return None

    cache_key = f"wellfound:{url}"
    cached = _cache_get(cache_key)
    if cached:
        logger.debug("Cache hit: %s", url[:80])
        return cached

    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                )
            )
            page = await context.new_page()
            try:
                await page.goto(url, timeout=30_000, wait_until="networkidle")
                await asyncio.sleep(2)
                html = await page.content()
                _cache_set(cache_key, html)
                return html
            except PlaywrightTimeout:
                logger.warning("[wellfound] Timeout: %s", url[:80])
                return None
            finally:
                await browser.close()
    except Exception as exc:
        logger.warning("[wellfound] Playwright error: %s", exc)
        return None


def _extract_jobs(html: str, country_hint: str) -> List[Dict[str, Any]]:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    results = []

    # Try inline JSON state first — Wellfound embeds job data as
    # window.__APOLLO_STATE__ or similar hydration payloads
    for script in soup.find_all("script"):
        text = script.string or ""
        if '"jobListings"' in text or '"startupRoles"' in text:
            # Look for job entries in the JSON
            matches = re.findall(
                r'\{[^{}]*"title"\s*:\s*"[^"]+[Oo]peration[^"]*"[^{}]*\}',
                text, re.S,
            )
            for m in matches:
                try:
                    obj = json.loads(m)
                    results.append({
                        "url": obj.get("jobUrl") or obj.get("url", ""),
                        "title": obj.get("title", ""),
                        "company": obj.get("startupName") or obj.get("company", ""),
                        "location": obj.get("locationNames") or obj.get("location", ""),
                        "salary_text": _extract_salary_from_obj(obj),
                        "description": obj.get("description", ""),
                        "posted_date": None,
                    })
                except (json.JSONDecodeError, ValueError):
                    continue

    if results:
        return results

    # Fallback: CSS card parsing
    # Wellfound job cards have data-test or class patterns
    for card in soup.find_all("div", attrs={"data-test": re.compile(r"StartupResult|JobListing")}):
        link = card.find("a", href=re.compile(r"/jobs/|/l/"))
        if not link:
            continue
        href = link.get("href", "")
        url = href if href.startswith("http") else f"{BASE_URL}{href}"

        title_el = card.find(class_=re.compile(r"title|role", re.I))
        company_el = card.find(class_=re.compile(r"company|startup", re.I))
        location_el = card.find(class_=re.compile(r"location", re.I))
        salary_el = card.find(class_=re.compile(r"salary|compensation|comp", re.I))

        results.append({
            "url": url,
            "title": title_el.get_text(strip=True) if title_el else "",
            "company": company_el.get_text(strip=True) if company_el else "",
            "location": location_el.get_text(strip=True) if location_el else country_hint,
            "salary_text": salary_el.get_text(strip=True) if salary_el else "",
            "description": card.get_text(separator=" ", strip=True)[:2000],
            "posted_date": None,
        })

    return results


def _extract_salary_from_obj(obj: Dict) -> str:
    """Build a salary string from a Wellfound job object."""
    salary_min = obj.get("salary") or obj.get("salaryMin") or obj.get("minSalary")
    salary_max = obj.get("salaryMax") or obj.get("maxSalary")
    currency = obj.get("currency") or obj.get("salaryCurrency", "USD")
    if salary_min and salary_max:
        return f"{currency} {salary_min}–{salary_max}"
    if salary_min:
        return f"{currency} {salary_min}"
    return obj.get("compensation", "") or ""


async def scrape(
    rejected_log: List[Dict],
    min_confidence: float = 0.65,
) -> List[Listing]:
    listings: List[Listing] = []
    seen_urls: set = set()

    for query, location, country_hint in SEARCH_CONFIG:
        logger.info("[wellfound] Searching '%s' in %s", query, location)
        url = _build_search_url(query, location)
        html = await _fetch_with_playwright(url)
        if not html:
            logger.warning("[wellfound] No HTML for '%s' / %s", query, location)
            await asyncio.sleep(REQUEST_DELAY)
            continue

        cards = _extract_jobs(html, country_hint)
        if not cards:
            logger.debug("[wellfound] No cards parsed for '%s' / %s", query, location)

        for card in cards:
            job_url = card.get("url", "")
            if not job_url or job_url in seen_urls:
                continue
            seen_urls.add(job_url)

            # Ensure absolute URL
            if not job_url.startswith("http"):
                job_url = f"{BASE_URL}{job_url}"

            title = card.get("title", "").strip()
            if not title:
                continue

            classification = classify_title(title)
            if classification is None:
                rejected_log.append({
                    "url": job_url,
                    "title": title,
                    "reason": "title_excluded_or_unmatched",
                    "source": SOURCE,
                })
                continue

            seniority, confidence = classification
            if confidence < min_confidence:
                rejected_log.append({
                    "url": job_url,
                    "title": title,
                    "reason": f"low_confidence_{confidence:.2f}",
                    "source": SOURCE,
                })
                continue

            description = card.get("description", "")
            salary_text = card.get("salary_text", "")

            # Wellfound typically quotes USD; infer from text or default to country
            parsed_sal = parse_salary(salary_text, country=country_hint)
            if parsed_sal.rejected:
                rejected_log.append({
                    "url": job_url,
                    "title": title,
                    "reason": parsed_sal.rejection_reason,
                    "source": SOURCE,
                })

            raw_location = card.get("location") or location
            if isinstance(raw_location, list):
                raw_location = ", ".join(raw_location)

            scope_signals = extract_scope_signals(description)
            company = card.get("company", "Unknown")
            country = infer_country(raw_location, f"wellfound_{country_hint.lower()}")
            city = extract_city(str(raw_location))
            company_size = infer_company_size(description)

            listing = Listing(
                id=make_id(SOURCE, job_url),
                source=SOURCE,
                url=job_url,
                title=title,
                company=company,
                company_size=company_size,
                location=str(raw_location),
                country=country,
                city=city,
                salary_min=parsed_sal.salary_min,
                salary_max=parsed_sal.salary_max,
                salary_currency=parsed_sal.currency,
                salary_includes_super=parsed_sal.includes_super if country_hint == "AU" else None,
                ote_min=parsed_sal.ote_min,
                ote_max=parsed_sal.ote_max,
                seniority=seniority,
                title_match_confidence=confidence,
                scope_signals=scope_signals,
                description_excerpt=description[:500],
                posted_date=None,
                scraped_date=date.today(),
            )
            listings.append(listing)
            logger.info("[wellfound] ✓ %s | %s", title, company)

        await asyncio.sleep(REQUEST_DELAY)

    logger.info("[wellfound] Done. %d listings collected.", len(listings))
    return listings


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    rejected: List[Dict] = []
    results = asyncio.run(scrape(rejected))
    print(json.dumps([r.model_dump(mode="json") for r in results], indent=2))
    print(f"\n{len(results)} listings, {len(rejected)} rejected", file=sys.stderr)
