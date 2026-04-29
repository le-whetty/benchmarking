"""
LinkedIn Jobs scraper — public search interface (no auth, no API).

LinkedIn's search results are JavaScript-rendered, so we use Playwright
to load each search URL and extract the structured JSON-LD or visible card data.
Falls back gracefully if Playwright isn't installed.

Note: LinkedIn aggressively rate-limits and may require CAPTCHA. We keep
delays conservative and cache heavily. If blocked, results will be empty
for that run; re-run after 24h cache expiry.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus, urlencode

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

SOURCE = "linkedin"
BASE_URL = "https://www.linkedin.com/jobs/search"
REQUEST_DELAY = 3.0  # LI is more sensitive to rate limits
CACHE_DIR = Path("data/cache/linkedin")

# (query, location, geo_id) — LinkedIn uses geoId for location filtering
SEARCH_CONFIG = [
    ("head of revenue operations", "New Zealand", "105490917"),
    ("head of revenue operations", "Australia", "101452733"),
    ("director revenue operations", "New Zealand", "105490917"),
    ("director revenue operations", "Australia", "101452733"),
    ("head of GTM operations", "New Zealand", "105490917"),
    ("head of GTM operations", "Australia", "101452733"),
    ("VP revenue operations", "Australia", "101452733"),
    ("director sales operations", "Australia", "101452733"),
    ("head commercial operations", "New Zealand", "105490917"),
]


def _build_search_url(query: str, location: str, geo_id: str, start: int = 0) -> str:
    params = {
        "keywords": query,
        "location": location,
        "geoId": geo_id,
        "f_TPR": "r2592000",  # last 30 days
        "start": start,
        "position": 1,
        "pageNum": 0,
    }
    return f"{BASE_URL}?" + urlencode(params)


async def _fetch_with_playwright(url: str) -> Optional[str]:
    """Use Playwright to fetch JS-rendered page. Returns HTML or None."""
    try:
        from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout
    except ImportError:
        logger.warning("Playwright not installed. Run: pip install playwright && playwright install chromium")
        return None

    cache_key = f"linkedin:{url}"
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
                ),
                locale="en-US",
            )
            page = await context.new_page()
            try:
                await page.goto(url, timeout=30_000, wait_until="networkidle")
                await asyncio.sleep(2)  # let dynamic content settle
                html = await page.content()
                _cache_set(cache_key, html)
                return html
            except PlaywrightTimeout:
                logger.warning("Playwright timeout for: %s", url[:80])
                return None
            finally:
                await browser.close()
    except Exception as exc:
        logger.warning("Playwright error: %s", exc)
        return None


def _extract_jobs_from_html(html: str, source_country: str) -> List[Dict[str, Any]]:
    """
    Extract job cards from LinkedIn search results HTML.
    LinkedIn embeds job data in JSON-LD scripts and/or data-entity-urn attributes.
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    results = []

    # Try JSON-LD structured data first
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
            if isinstance(data, dict) and data.get("@type") == "JobPosting":
                results.append(_parse_json_ld(data))
            elif isinstance(data, list):
                for item in data:
                    if isinstance(item, dict) and item.get("@type") == "JobPosting":
                        results.append(_parse_json_ld(item))
        except (json.JSONDecodeError, AttributeError):
            continue

    if results:
        return [r for r in results if r]

    # Fallback: parse visible job cards
    for card in soup.find_all("div", class_=re.compile(r"job-search-card|jobs-search__results-list")):
        link = card.find("a", href=re.compile(r"/jobs/view/"))
        if not link:
            continue
        href = link.get("href", "").split("?")[0]
        title_el = card.find(class_=re.compile(r"job-card.*title|base-search-card__title"))
        company_el = card.find(class_=re.compile(r"job-card.*company|base-search-card__subtitle"))
        location_el = card.find(class_=re.compile(r"job-card.*location|job-search-card__location"))
        results.append({
            "url": href if href.startswith("http") else f"https://www.linkedin.com{href}",
            "title": title_el.get_text(strip=True) if title_el else "",
            "company": company_el.get_text(strip=True) if company_el else "",
            "location": location_el.get_text(strip=True) if location_el else "",
            "salary_text": "",
            "description": "",
            "posted_date": None,
        })

    return results


def _parse_json_ld(data: Dict) -> Optional[Dict[str, Any]]:
    """Parse a JSON-LD JobPosting object into our card format."""
    try:
        salary = data.get("baseSalary") or {}
        salary_text = ""
        if salary:
            value = salary.get("value") or {}
            min_val = value.get("minValue")
            max_val = value.get("maxValue")
            currency = salary.get("currency", "")
            if min_val and max_val:
                salary_text = f"{currency} {min_val}–{max_val}"
            elif min_val:
                salary_text = f"{currency} {min_val}"

        posted_raw = data.get("datePosted", "")
        posted = None
        if posted_raw:
            try:
                posted = datetime.fromisoformat(posted_raw.replace("Z", "+00:00")).date()
            except ValueError:
                pass

        return {
            "url": data.get("url", ""),
            "title": data.get("title", ""),
            "company": (data.get("hiringOrganization") or {}).get("name", ""),
            "location": (data.get("jobLocation") or {}).get("address", {}).get("addressLocality", ""),
            "salary_text": salary_text,
            "description": data.get("description", "")[:2000],
            "posted_date": posted,
        }
    except Exception:
        return None


def _parse_date(raw: Any) -> Optional[date]:
    if isinstance(raw, date):
        return raw
    if not raw:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d"):
        try:
            return datetime.strptime(str(raw)[:19], fmt).date()
        except ValueError:
            continue
    return None


async def scrape(
    rejected_log: List[Dict],
    min_confidence: float = 0.65,
) -> List[Listing]:
    listings: List[Listing] = []
    seen_urls: set = set()

    for query, location, geo_id in SEARCH_CONFIG:
        source_country = "NZ" if "New Zealand" in location else "AU"
        logger.info("[linkedin] Searching '%s' in %s", query, location)

        for start in range(0, 50, 25):  # two pages of 25
            url = _build_search_url(query, location, geo_id, start)
            html = await _fetch_with_playwright(url)
            if not html:
                logger.warning("[linkedin] No HTML for '%s' page start=%d", query, start)
                break

            cards = _extract_jobs_from_html(html, source_country)
            if not cards:
                break

            for card in cards:
                job_url = card.get("url", "")
                if not job_url or job_url in seen_urls:
                    continue
                seen_urls.add(job_url)

                title = card.get("title", "").strip()
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
                parsed_sal = parse_salary(salary_text, country=source_country)
                if parsed_sal.rejected:
                    rejected_log.append({
                        "url": job_url,
                        "title": title,
                        "reason": parsed_sal.rejection_reason,
                        "source": SOURCE,
                    })

                scope_signals = extract_scope_signals(description)
                company = card.get("company", "Unknown")
                raw_location = card.get("location", location)
                country = infer_country(raw_location, f"linkedin_{source_country.lower()}")
                city = extract_city(raw_location)
                company_size = infer_company_size(description)
                posted_date = _parse_date(card.get("posted_date"))

                listing = Listing(
                    id=make_id(SOURCE, job_url),
                    source=SOURCE,
                    url=job_url,
                    title=title,
                    company=company,
                    company_size=company_size,
                    location=raw_location,
                    country=country,
                    city=city,
                    salary_min=parsed_sal.salary_min,
                    salary_max=parsed_sal.salary_max,
                    salary_currency=parsed_sal.currency,
                    salary_includes_super=parsed_sal.includes_super if source_country == "AU" else None,
                    ote_min=parsed_sal.ote_min,
                    ote_max=parsed_sal.ote_max,
                    seniority=seniority,
                    title_match_confidence=confidence,
                    scope_signals=scope_signals,
                    description_excerpt=description[:500],
                    posted_date=posted_date,
                    scraped_date=date.today(),
                )
                listings.append(listing)
                logger.info("[linkedin] ✓ %s | %s", title, company)

            await asyncio.sleep(REQUEST_DELAY)

    logger.info("[linkedin] Done. %d listings collected.", len(listings))
    return listings


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    rejected: List[Dict] = []
    results = asyncio.run(scrape(rejected))
    print(json.dumps([r.model_dump(mode="json") for r in results], indent=2))
    print(f"\n{len(results)} listings, {len(rejected)} rejected", file=sys.stderr)
