"""
Seek.com.au scraper — GTM Ops / Revenue Ops roles in Australia.
Mirrors seek_nz.py but targets seek.com.au and applies AU salary defaults.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

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
# Reuse helpers from seek_nz
from scraper.sources.seek_nz import (
    _cache_get, _cache_set, CACHE_TTL,
    _extract_job_links_from_search,
    _parse_job_detail,
    _parse_date,
    HEADERS,
    REQUEST_DELAY,
    MAX_PAGES,
)

logger = logging.getLogger(__name__)

SOURCE = "seek_au"
BASE_URL = "https://www.seek.com.au"
CACHE_DIR = Path("data/cache/seek_au")

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


def _build_search_url(query: str, page: int) -> str:
    params = {
        "keywords": query,
        "where": "All Australia",
        "page": page,
        "daterange": 90,
        "salarytype": "annual",
    }
    return f"{BASE_URL}/jobs?" + urlencode(params)


async def _fetch(client: httpx.AsyncClient, url: str, retries: int = 3) -> Optional[str]:
    # Use a seek_au-namespaced cache key
    cache_key = f"seek_au:{url}"
    cached = _cache_get(cache_key)
    if cached:
        logger.debug("Cache hit: %s", url)
        return cached

    for attempt in range(retries):
        try:
            resp = await client.get(url, headers=HEADERS, follow_redirects=True, timeout=20)
            if resp.status_code == 200:
                _cache_set(cache_key, resp.text)
                return resp.text
            if resp.status_code == 429:
                wait = 2 ** (attempt + 2)
                logger.warning("Rate-limited by Seek AU, waiting %ds", wait)
                await asyncio.sleep(wait)
            else:
                logger.warning("HTTP %d for %s", resp.status_code, url)
                return None
        except httpx.RequestError as exc:
            wait = 2 ** attempt
            logger.warning("Request error (%s), retry in %ds", exc, wait)
            await asyncio.sleep(wait)
    return None


async def scrape(
    rejected_log: List[Dict],
    min_confidence: float = 0.65,
) -> List[Listing]:
    listings: List[Listing] = []
    seen_urls: set = set()

    async with httpx.AsyncClient() as client:
        for query in SEARCH_QUERIES:
            logger.info("[seek_au] Searching: %s", query)
            for page in range(1, MAX_PAGES + 1):
                url = _build_search_url(query, page)
                html = await _fetch(client, url)
                if not html:
                    break

                job_cards = _extract_job_links_from_search(html)
                if not job_cards:
                    break

                # Rewrite URLs to seek.com.au domain
                for card in job_cards:
                    card["url"] = card["url"].replace(
                        "www.seek.co.nz", "www.seek.com.au"
                    )

                for card in job_cards:
                    job_url = card["url"]
                    if job_url in seen_urls:
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

                    await asyncio.sleep(REQUEST_DELAY)
                    detail_html = await _fetch(client, job_url)
                    detail = _parse_job_detail(detail_html, job_url) if detail_html else {}

                    description = detail.get("description", "")
                    salary_text = detail.get("salary_text", "") or card.get("salary_label", "")

                    parsed_sal = parse_salary(salary_text, country="AU")
                    if parsed_sal.rejected:
                        rejected_log.append({
                            "url": job_url,
                            "title": title,
                            "reason": parsed_sal.rejection_reason,
                            "source": SOURCE,
                        })

                    scope_signals = extract_scope_signals(description)
                    company = card.get("company", "Unknown")
                    location = card.get("location", "Australia")
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
                        salary_includes_super=parsed_sal.includes_super,
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
                        "[seek_au] ✓ %s | %s | salary: %s–%s %s%s",
                        title, company,
                        parsed_sal.salary_min, parsed_sal.salary_max, parsed_sal.currency,
                        " +super" if parsed_sal.includes_super else "",
                    )

                await asyncio.sleep(REQUEST_DELAY)

    logger.info("[seek_au] Done. %d listings collected.", len(listings))
    return listings


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    rejected: List[Dict] = []
    results = asyncio.run(scrape(rejected))
    print(json.dumps([r.model_dump(mode="json") for r in results], indent=2))
    print(f"\n{len(results)} listings, {len(rejected)} rejected", file=sys.stderr)
