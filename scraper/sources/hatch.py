"""
Hatch (hatch.team) scraper — NZ startup job board.

Hatch is NZ-focused, startup/scaleup heavy, and has unusually high salary
disclosure rates (~60% of listings). HTML is server-rendered; no Playwright needed.

Job listing URL pattern: https://hatch.team/jobs
Category filter: /jobs?category=operations or search by keyword.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, urlencode

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
from scraper.sources.seek_nz import _cache_get, _cache_set, HEADERS

logger = logging.getLogger(__name__)

SOURCE = "hatch"
BASE_URL = "https://hatch.team"
REQUEST_DELAY = 1.5

SEARCH_URLS = [
    f"{BASE_URL}/jobs?search=revenue+operations",
    f"{BASE_URL}/jobs?search=revops",
    f"{BASE_URL}/jobs?search=gtm+operations",
    f"{BASE_URL}/jobs?search=sales+operations",
    f"{BASE_URL}/jobs?search=head+of+operations",
    f"{BASE_URL}/jobs?search=director+revenue",
    f"{BASE_URL}/jobs?category=operations",
]


async def _fetch(client: httpx.AsyncClient, url: str, retries: int = 3) -> Optional[str]:
    cache_key = f"hatch:{url}"
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
                await asyncio.sleep(2 ** (attempt + 2))
            else:
                logger.warning("[hatch] HTTP %d for %s", resp.status_code, url)
                return None
        except httpx.RequestError as exc:
            await asyncio.sleep(2 ** attempt)
            logger.warning("[hatch] Request error: %s", exc)

    return None


def _parse_listings(html: str) -> List[Dict[str, Any]]:
    """
    Parse Hatch job listing cards from search results page.
    Hatch renders cards server-side with consistent class names.
    """
    soup = BeautifulSoup(html, "html.parser")
    results = []

    # Hatch job cards are typically <article> or <div> with data attributes
    # or a consistent card component structure
    cards = (
        soup.find_all("article", class_=re.compile(r"job|listing|role", re.I))
        or soup.find_all("div", class_=re.compile(r"job-card|listing-card|role-card", re.I))
        or soup.find_all("div", attrs={"data-job-id": True})
        or soup.find_all("li", class_=re.compile(r"job|listing", re.I))
    )

    # Broader fallback: any card with a link matching /jobs/<slug>
    if not cards:
        cards = [
            a.find_parent(["article", "div", "li"])
            for a in soup.find_all("a", href=re.compile(r"/jobs/[a-z0-9-]+"))
            if a.find_parent(["article", "div", "li"])
        ]
        # Deduplicate by parent element
        seen = set()
        unique = []
        for c in cards:
            cid = id(c)
            if cid not in seen:
                seen.add(cid)
                unique.append(c)
        cards = unique

    for card in cards:
        link = card.find("a", href=re.compile(r"/jobs/"))
        if not link:
            continue
        href = link.get("href", "")
        job_url = href if href.startswith("http") else urljoin(BASE_URL, href)

        # Title: usually an <h2> or <h3> or the link text
        title_el = (
            card.find(["h2", "h3"])
            or card.find(class_=re.compile(r"title|role|position", re.I))
        )
        title = title_el.get_text(strip=True) if title_el else link.get_text(strip=True)

        # Company
        company_el = card.find(class_=re.compile(r"company|employer|org", re.I))
        company = company_el.get_text(strip=True) if company_el else ""

        # Location
        location_el = card.find(class_=re.compile(r"location|city|place", re.I))
        location = location_el.get_text(strip=True) if location_el else "New Zealand"

        # Salary — Hatch often shows it directly on the card
        salary_el = card.find(class_=re.compile(r"salary|pay|comp|remuneration", re.I))
        if not salary_el:
            # Look for text patterns like "$120k–$160k"
            card_text = card.get_text()
            salary_match = re.search(
                r"(?:NZ\$|AU\$|\$)\s*[\d,]+[kKmM]?\s*[-–]\s*(?:NZ\$|AU\$|\$)?\s*[\d,]+[kKmM]?",
                card_text,
            )
            salary_text = salary_match.group(0) if salary_match else ""
        else:
            salary_text = salary_el.get_text(strip=True)

        # Posted date
        date_el = card.find("time")
        posted_raw = date_el.get("datetime", "") if date_el else ""

        results.append({
            "url": job_url,
            "title": title,
            "company": company,
            "location": location,
            "salary_text": salary_text,
            "description": card.get_text(separator=" ", strip=True)[:2000],
            "posted_raw": posted_raw,
        })

    return results


def _parse_detail(html: str) -> Dict[str, Any]:
    """Extract fuller description and salary from an individual job page."""
    soup = BeautifulSoup(html, "html.parser")

    description = ""
    salary_text = ""

    # Description body
    desc_el = (
        soup.find(class_=re.compile(r"description|content|body|details", re.I))
        or soup.find("main")
    )
    if desc_el:
        description = desc_el.get_text(separator=" ", strip=True)

    # Salary — look for explicit salary section
    for el in soup.find_all(class_=re.compile(r"salary|pay|compensation|remuneration", re.I)):
        text = el.get_text(strip=True)
        if any(c.isdigit() for c in text):
            salary_text = text
            break

    if not salary_text:
        # Scan full page for salary patterns
        page_text = soup.get_text()
        m = re.search(
            r"(?:NZ\$|AU\$|\$|NZD|AUD)\s*[\d,]+[kKmM]?\s*[-–—to]+\s*"
            r"(?:NZ\$|AU\$|\$|NZD|AUD)?\s*[\d,]+[kKmM]?",
            page_text, re.I,
        )
        if m:
            salary_text = m.group(0)

    return {"description": description, "salary_text": salary_text}


def _parse_date(raw: str) -> Optional[date]:
    if not raw:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw[:10], "%Y-%m-%d").date()
        except ValueError:
            continue
    m = re.search(r"(\d+)\s+day", raw, re.I)
    if m:
        return (datetime.now() - timedelta(days=int(m.group(1)))).date()
    return None


async def scrape(
    rejected_log: List[Dict],
    min_confidence: float = 0.65,
) -> List[Listing]:
    listings: List[Listing] = []
    seen_urls: set = set()

    async with httpx.AsyncClient() as client:
        for search_url in SEARCH_URLS:
            logger.info("[hatch] Fetching: %s", search_url)
            html = await _fetch(client, search_url)
            if not html:
                continue

            cards = _parse_listings(html)
            if not cards:
                logger.debug("[hatch] No cards from %s", search_url)

            for card in cards:
                job_url = card["url"]
                if job_url in seen_urls:
                    continue
                seen_urls.add(job_url)

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

                # Fetch detail page for richer description + salary
                await asyncio.sleep(REQUEST_DELAY)
                detail_html = await _fetch(client, job_url)
                detail = _parse_detail(detail_html) if detail_html else {}

                description = detail.get("description", "") or card.get("description", "")
                salary_text = detail.get("salary_text", "") or card.get("salary_text", "")

                parsed_sal = parse_salary(salary_text, country="NZ")
                if parsed_sal.rejected:
                    rejected_log.append({
                        "url": job_url,
                        "title": title,
                        "reason": parsed_sal.rejection_reason,
                        "source": SOURCE,
                    })

                raw_location = card.get("location", "New Zealand")
                scope_signals = extract_scope_signals(description)
                company = card.get("company", "Unknown")
                country = infer_country(raw_location, SOURCE)
                city = extract_city(raw_location)
                company_size = infer_company_size(description)
                posted_date = _parse_date(card.get("posted_raw", ""))

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
                    salary_includes_super=None,
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
                logger.info("[hatch] ✓ %s | %s | salary: %s–%s", title, company,
                            parsed_sal.salary_min, parsed_sal.salary_max)

            await asyncio.sleep(REQUEST_DELAY)

    logger.info("[hatch] Done. %d listings collected.", len(listings))
    return listings


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    rejected: List[Dict] = []
    results = asyncio.run(scrape(rejected))
    print(json.dumps([r.model_dump(mode="json") for r in results], indent=2))
    print(f"\n{len(results)} listings, {len(rejected)} rejected", file=sys.stderr)
