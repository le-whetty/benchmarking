"""
Working In Tech NZ (workingintech.co.nz) scraper.

NZ-specific tech community job board. Server-rendered HTML; no Playwright needed.
Salary disclosure is moderate (~30-40%). Roles skew startup/scaleup NZ.

The board also lists AU remote roles. We capture both but tag country accordingly.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

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

SOURCE = "working_in_tech"
BASE_URL = "https://workingintech.co.nz"
REQUEST_DELAY = 1.5

SEARCH_URLS = [
    f"{BASE_URL}/jobs?search=revenue+operations",
    f"{BASE_URL}/jobs?search=revops",
    f"{BASE_URL}/jobs?search=gtm+operations",
    f"{BASE_URL}/jobs?search=sales+operations",
    f"{BASE_URL}/jobs?search=head+of+operations",
    f"{BASE_URL}/jobs?search=director+revenue",
    f"{BASE_URL}/jobs?category=operations",
    f"{BASE_URL}/jobs?category=business-operations",
]


async def _fetch(client: httpx.AsyncClient, url: str, retries: int = 3) -> Optional[str]:
    cache_key = f"working_in_tech:{url}"
    cached = _cache_get(cache_key)
    if cached:
        return cached

    for attempt in range(retries):
        try:
            resp = await client.get(url, headers=HEADERS, follow_redirects=True, timeout=20)
            if resp.status_code == 200:
                _cache_set(cache_key, resp.text)
                return resp.text
            if resp.status_code == 404:
                return None  # URL doesn't exist, don't retry
            if resp.status_code == 429:
                await asyncio.sleep(2 ** (attempt + 2))
            else:
                logger.warning("[working_in_tech] HTTP %d for %s", resp.status_code, url)
                return None
        except httpx.RequestError as exc:
            await asyncio.sleep(2 ** attempt)
            logger.warning("[working_in_tech] Request error: %s", exc)

    return None


def _parse_listings(html: str) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    results = []

    # workingintech.co.nz has changed layout a few times;
    # try multiple selectors in order of specificity
    cards = (
        soup.find_all("article", class_=re.compile(r"job|listing", re.I))
        or soup.find_all("div", class_=re.compile(r"job-listing|job-card|job-item", re.I))
        or soup.find_all("div", attrs={"data-job": True})
    )

    if not cards:
        # Broad fallback: any anchor matching /jobs/<slug>
        links = soup.find_all("a", href=re.compile(r"/jobs/[a-zA-Z0-9-]+/?$"))
        seen_parents = set()
        for lnk in links:
            parent = lnk.find_parent(["article", "li", "div"])
            if parent and id(parent) not in seen_parents:
                seen_parents.add(id(parent))
                cards.append(parent)

    for card in cards:
        link = card.find("a", href=re.compile(r"/jobs/"))
        if not link:
            continue
        href = link.get("href", "")
        job_url = href if href.startswith("http") else urljoin(BASE_URL, href)

        title_el = card.find(["h2", "h3", "h4"]) or card.find(class_=re.compile(r"title|role", re.I))
        title = title_el.get_text(strip=True) if title_el else link.get_text(strip=True)

        company_el = card.find(class_=re.compile(r"company|employer|org|brand", re.I))
        company = company_el.get_text(strip=True) if company_el else ""

        location_el = card.find(class_=re.compile(r"location|place|city|region", re.I))
        location = location_el.get_text(strip=True) if location_el else "New Zealand"

        # Salary on card
        salary_el = card.find(class_=re.compile(r"salary|pay|remuneration|comp", re.I))
        if salary_el:
            salary_text = salary_el.get_text(strip=True)
        else:
            m = re.search(
                r"(?:NZ\$|AU\$|\$|NZD|AUD)\s*[\d,]+[kKmM]?(?:\s*[-–]\s*(?:NZ\$|AU\$|\$)?\s*[\d,]+[kKmM]?)?",
                card.get_text(), re.I,
            )
            salary_text = m.group(0) if m else ""

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
    soup = BeautifulSoup(html, "html.parser")
    description = ""
    salary_text = ""

    desc_el = soup.find(class_=re.compile(r"description|content|body|jd", re.I)) or soup.find("main")
    if desc_el:
        description = desc_el.get_text(separator=" ", strip=True)

    for el in soup.find_all(class_=re.compile(r"salary|pay|remuneration|comp", re.I)):
        t = el.get_text(strip=True)
        if any(c.isdigit() for c in t):
            salary_text = t
            break

    if not salary_text:
        m = re.search(
            r"(?:NZ\$|AU\$|\$|NZD|AUD)\s*[\d,]+[kKmM]?\s*[-–—to]+\s*(?:NZ\$|AU\$|\$|NZD|AUD)?\s*[\d,]+[kKmM]?",
            soup.get_text(), re.I,
        )
        if m:
            salary_text = m.group(0)

    return {"description": description, "salary_text": salary_text}


def _parse_date(raw: str) -> Optional[date]:
    if not raw:
        return None
    try:
        return datetime.strptime(raw[:10], "%Y-%m-%d").date()
    except ValueError:
        pass
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
            logger.info("[working_in_tech] Fetching: %s", search_url)
            html = await _fetch(client, search_url)
            if not html:
                continue

            cards = _parse_listings(html)

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
                        "url": job_url, "title": title,
                        "reason": "title_excluded_or_unmatched", "source": SOURCE,
                    })
                    continue

                seniority, confidence = classification
                if confidence < min_confidence:
                    rejected_log.append({
                        "url": job_url, "title": title,
                        "reason": f"low_confidence_{confidence:.2f}", "source": SOURCE,
                    })
                    continue

                await asyncio.sleep(REQUEST_DELAY)
                detail_html = await _fetch(client, job_url)
                detail = _parse_detail(detail_html) if detail_html else {}

                description = detail.get("description", "") or card.get("description", "")
                salary_text = detail.get("salary_text", "") or card.get("salary_text", "")

                parsed_sal = parse_salary(salary_text, country="NZ")
                if parsed_sal.rejected:
                    rejected_log.append({
                        "url": job_url, "title": title,
                        "reason": parsed_sal.rejection_reason, "source": SOURCE,
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
                logger.info("[working_in_tech] ✓ %s | %s", title, company)

            await asyncio.sleep(REQUEST_DELAY)

    logger.info("[working_in_tech] Done. %d listings collected.", len(listings))
    return listings


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    rejected: List[Dict] = []
    results = asyncio.run(scrape(rejected))
    print(json.dumps([r.model_dump(mode="json") for r in results], indent=2))
    print(f"\n{len(results)} listings, {len(rejected)} rejected", file=sys.stderr)
