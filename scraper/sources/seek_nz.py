"""
Seek.co.nz scraper — GTM Ops / Revenue Ops roles in New Zealand.

Seek renders search results server-side, so we get by with httpx + BS4
for the listing index. Individual job pages use a JSON blob embedded in
a <script> tag (window.SEEK_REDUX_DATA or __REDUX_STORE__), which we
extract without Playwright.

Rate-limit: 1–2 s between requests; cache raw HTML for 24 h.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode, urljoin

import httpx
from bs4 import BeautifulSoup

from scraper.schema import Listing, make_id
from scraper.salary_parser import parse_salary
from scraper.normaliser import (
    classify_title,
    extract_city,
    extract_scope_signals,
    infer_company_size,
    infer_country,
)

logger = logging.getLogger(__name__)

SOURCE = "seek_nz"
BASE_URL = "https://www.seek.co.nz"
CACHE_DIR = Path("data/cache/seek_nz")
CACHE_TTL = timedelta(hours=24)

SEARCH_QUERIES = [
    "head of revenue operations",
    "head of revops",
    "head of GTM operations",
    "director revenue operations",
    "director sales operations",
    "VP revenue operations",
    "head of commercial operations",
    "head of sales operations",
    "GTM strategy lead",
    "revenue operations manager",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-NZ,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

MAX_PAGES = 3        # per query; Seek shows ~22 listings/page
REQUEST_DELAY = 1.5  # seconds between requests


# ── cache helpers ─────────────────────────────────────────────────────────────

def _cache_path(key: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / (hashlib.sha1(key.encode()).hexdigest() + ".html")


def _cache_get(key: str) -> Optional[str]:
    path = _cache_path(key)
    if path.exists():
        age = datetime.now() - datetime.fromtimestamp(path.stat().st_mtime)
        if age < CACHE_TTL:
            return path.read_text(encoding="utf-8")
    return None


def _cache_set(key: str, content: str) -> None:
    _cache_path(key).write_text(content, encoding="utf-8")


# ── HTTP ──────────────────────────────────────────────────────────────────────

async def _fetch(client: httpx.AsyncClient, url: str, retries: int = 3) -> Optional[str]:
    cached = _cache_get(url)
    if cached:
        logger.debug("Cache hit: %s", url)
        return cached

    for attempt in range(retries):
        try:
            resp = await client.get(url, headers=HEADERS, follow_redirects=True, timeout=20)
            if resp.status_code == 200:
                _cache_set(url, resp.text)
                return resp.text
            if resp.status_code == 429:
                wait = 2 ** (attempt + 2)
                logger.warning("Rate-limited by Seek, waiting %ds", wait)
                await asyncio.sleep(wait)
            else:
                logger.warning("HTTP %d for %s", resp.status_code, url)
                return None
        except httpx.RequestError as exc:
            wait = 2 ** attempt
            logger.warning("Request error (%s), retry in %ds", exc, wait)
            await asyncio.sleep(wait)

    return None


# ── search result parsing ─────────────────────────────────────────────────────

def _build_search_url(query: str, page: int) -> str:
    params = {
        "keywords": query,
        "location": "New Zealand",
        "page": page,
        "daterange": 90,    # last 90 days
        "salarytype": "annual",
    }
    return f"{BASE_URL}/jobs?" + urlencode(params)


def _extract_job_links_from_search(html: str) -> List[Dict[str, Any]]:
    """
    Seek embeds job data in a JSON blob inside a <script id="SEEK_REDUX_DATA">.
    Fall back to link parsing if the structure changes.
    """
    soup = BeautifulSoup(html, "html.parser")
    results = []

    # Try JSON blob first (most reliable)
    for script in soup.find_all("script"):
        text = script.string or ""
        if "jobId" in text and "jobTitle" in text:
            # Look for the JSON array of job ads
            match = re.search(r'"jobAds"\s*:\s*(\[.*?\])\s*,\s*"', text, re.S)
            if match:
                try:
                    jobs = json.loads(match.group(1))
                    for job in jobs:
                        link = job.get("listingDate", "")
                        job_id = job.get("id") or job.get("jobId")
                        title = job.get("title") or job.get("jobTitle", "")
                        company = (job.get("advertiser") or {}).get("description", "")
                        location_obj = job.get("location") or {}
                        location = location_obj if isinstance(location_obj, str) else (
                            location_obj.get("label") or location_obj.get("description", "")
                        )
                        salary_label = job.get("salary", "")
                        listed_date = job.get("listingDate", "")
                        if job_id:
                            results.append({
                                "url": f"{BASE_URL}/job/{job_id}",
                                "title": title,
                                "company": company,
                                "location": location,
                                "salary_label": salary_label,
                                "listed_date": listed_date,
                            })
                    if results:
                        return results
                except json.JSONDecodeError:
                    pass

    # Fallback: parse <article> tags from the search results page
    for article in soup.find_all("article", attrs={"data-card-type": "JobCard"}):
        a_tag = article.find("a", href=re.compile(r"/job/\d+"))
        if not a_tag:
            continue
        href = a_tag.get("href", "")
        url = urljoin(BASE_URL, href.split("?")[0])
        title_el = article.find(attrs={"data-automation": "jobTitle"})
        company_el = article.find(attrs={"data-automation": "jobCompany"})
        location_el = article.find(attrs={"data-automation": "jobLocation"})
        salary_el = article.find(attrs={"data-automation": "jobSalary"})
        date_el = article.find("time")
        results.append({
            "url": url,
            "title": title_el.get_text(strip=True) if title_el else "",
            "company": company_el.get_text(strip=True) if company_el else "",
            "location": location_el.get_text(strip=True) if location_el else "",
            "salary_label": salary_el.get_text(strip=True) if salary_el else "",
            "listed_date": date_el.get("datetime", "") if date_el else "",
        })

    return results


# ── job detail parsing ────────────────────────────────────────────────────────

def _parse_job_detail(html: str, url: str) -> Optional[Dict[str, Any]]:
    """Extract description text and richer salary from the job detail page."""
    soup = BeautifulSoup(html, "html.parser")

    # Seek embeds a __REDUX_STORE__ or similar JSON object
    description = ""
    salary_text = ""

    for script in soup.find_all("script"):
        text = script.string or ""
        if '"jobDetails"' in text or '"description"' in text:
            # Try to extract description
            desc_match = re.search(r'"description"\s*:\s*"((?:[^"\\]|\\.)*)"', text)
            if desc_match:
                try:
                    description = json.loads(f'"{desc_match.group(1)}"')
                except Exception:
                    description = desc_match.group(1)
            sal_match = re.search(r'"salary"\s*:\s*"([^"]*)"', text)
            if sal_match:
                salary_text = sal_match.group(1)
            break

    # Fallback: grab the visible description div
    if not description:
        desc_div = soup.find(attrs={"data-automation": "jobAdDetails"})
        if desc_div:
            description = desc_div.get_text(separator=" ", strip=True)

    if not salary_text:
        sal_el = soup.find(attrs={"data-automation": "job-detail-salary"})
        if sal_el:
            salary_text = sal_el.get_text(strip=True)

    return {
        "description": description,
        "salary_text": salary_text,
    }


# ── date parsing ──────────────────────────────────────────────────────────────

def _parse_date(raw: str) -> Optional[date]:
    if not raw:
        return None
    raw = raw.strip()
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw[:19], fmt[:len(raw[:19])]).date()
        except ValueError:
            continue
    # "X days ago" style
    m = re.search(r"(\d+)\s+day", raw, re.I)
    if m:
        return (datetime.now() - timedelta(days=int(m.group(1)))).date()
    return None


# ── main scrape function ──────────────────────────────────────────────────────

async def scrape(
    rejected_log: List[Dict],
    min_confidence: float = 0.65,
) -> List[Listing]:
    listings: List[Listing] = []
    seen_urls: set = set()

    async with httpx.AsyncClient() as client:
        for query in SEARCH_QUERIES:
            logger.info("[seek_nz] Searching: %s", query)
            for page in range(1, MAX_PAGES + 1):
                url = _build_search_url(query, page)
                html = await _fetch(client, url)
                if not html:
                    break

                job_cards = _extract_job_links_from_search(html)
                if not job_cards:
                    logger.debug("[seek_nz] No results on page %d for '%s'", page, query)
                    break

                for card in job_cards:
                    job_url = card["url"]
                    if job_url in seen_urls:
                        continue
                    seen_urls.add(job_url)

                    title = card.get("title", "").strip()
                    classification = classify_title(title)
                    if classification is None:
                        logger.debug("[seek_nz] Skipping excluded title: %s", title)
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

                    # Fetch detail page for description + richer salary
                    await asyncio.sleep(REQUEST_DELAY)
                    detail_html = await _fetch(client, job_url)
                    detail = _parse_job_detail(detail_html, job_url) if detail_html else {}

                    description = detail.get("description", "")
                    salary_text = detail.get("salary_text", "") or card.get("salary_label", "")

                    parsed_sal = parse_salary(salary_text, country="NZ")
                    if parsed_sal.rejected:
                        rejected_log.append({
                            "url": job_url,
                            "title": title,
                            "reason": parsed_sal.rejection_reason,
                            "source": SOURCE,
                        })
                        # Keep the listing but clear salary fields (already cleared by parser)

                    scope_signals = extract_scope_signals(description)
                    company = card.get("company", "Unknown")
                    location = card.get("location", "New Zealand")
                    country = infer_country(location, SOURCE)
                    city = extract_city(location)
                    company_size = infer_company_size(description)
                    posted_date = _parse_date(card.get("listed_date", ""))

                    listing = Listing(
                        id=make_id(SOURCE, job_url),
                        source=SOURCE,
                        url=job_url,
                        title=title,
                        company=company,
                        company_size=company_size,
                        location=location,
                        country=country,
                        city=city,
                        salary_min=parsed_sal.salary_min,
                        salary_max=parsed_sal.salary_max,
                        salary_currency=parsed_sal.currency,
                        salary_includes_super=None,  # NZ — not applicable
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
                    logger.info(
                        "[seek_nz] ✓ %s | %s | salary: %s–%s %s",
                        title, company,
                        parsed_sal.salary_min, parsed_sal.salary_max, parsed_sal.currency,
                    )

                await asyncio.sleep(REQUEST_DELAY)

    logger.info("[seek_nz] Done. %d listings collected.", len(listings))
    return listings


# ── standalone entrypoint ─────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    rejected: List[Dict] = []
    results = asyncio.run(scrape(rejected))
    print(json.dumps([r.model_dump(mode="json") for r in results], indent=2))
    print(f"\n{len(results)} listings, {len(rejected)} rejected", file=sys.stderr)
