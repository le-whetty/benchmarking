"""
VC portfolio job board scraper.

Covers Blackbird Ventures, AirTree Ventures, and Icehouse Ventures — three of
the most active ANZ VC firms. Their portfolio companies are disproportionately
early adopters of RevOps/GTM Ops as a function, and many post comp publicly.

Board platforms used:
- Blackbird: pallet.xyz hosted board  (jobs.blackbird.vc)
- AirTree:   pallet.xyz hosted board  (jobs.airtree.vc)
- Icehouse:  custom or pallet.xyz     (jobs.icehouse.co.nz or icehouseventures.co.nz/jobs)

Pallet boards are server-rendered HTML — no Playwright needed.
Each board has a keyword search and optional category filter.

Adding a new VC board:
  Add an entry to VC_BOARDS below. That's it.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import date, datetime, timedelta
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
from scraper.sources.seek_nz import _cache_get, _cache_set, HEADERS

logger = logging.getLogger(__name__)

SOURCE = "vc_boards"
REQUEST_DELAY = 1.5

# ── VC board registry ─────────────────────────────────────────────────────────
# Each entry:
#   name:         short display name (used in source field: "vc_blackbird" etc.)
#   base_url:     root of the job board
#   search_path:  path template where {query} is the URL-encoded search term
#   country:      default country hint if location is ambiguous
#   platform:     "pallet" | "custom" — affects parser strategy
VC_BOARDS = [
    {
        "name": "blackbird",
        "base_url": "https://jobs.blackbird.vc",
        "search_path": "/jobs?search={query}",
        "country": "AU",   # Blackbird is primarily AU-based
        "platform": "pallet",
    },
    {
        "name": "airtree",
        "base_url": "https://jobs.airtree.vc",
        "search_path": "/jobs?search={query}",
        "country": "AU",
        "platform": "pallet",
    },
    {
        "name": "icehouse",
        "base_url": "https://jobs.icehouse.co.nz",
        "search_path": "/jobs?search={query}",
        "country": "NZ",
        "platform": "pallet",
    },
]

SEARCH_QUERIES = [
    "revenue operations",
    "revops",
    "gtm operations",
    "sales operations",
    "head of operations",
    "director revenue",
    "commercial operations",
]


async def _fetch(
    client: httpx.AsyncClient, url: str, board_name: str, retries: int = 3
) -> Optional[str]:
    cache_key = f"vc_{board_name}:{url}"
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
                logger.debug("[vc_%s] 404: %s", board_name, url)
                return None
            if resp.status_code == 429:
                await asyncio.sleep(2 ** (attempt + 2))
            else:
                logger.warning("[vc_%s] HTTP %d: %s", board_name, resp.status_code, url)
                return None
        except httpx.RequestError as exc:
            await asyncio.sleep(2 ** attempt)
            logger.warning("[vc_%s] Request error: %s", board_name, exc)

    return None


# ── Pallet board parser ───────────────────────────────────────────────────────
# Pallet (pallet.xyz) boards render job cards consistently across hosted boards.
# Cards are <article> or <li> elements; salary is sometimes in a badge.

def _parse_pallet(html: str, base_url: str) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    results = []

    # Pallet cards have class patterns like "job-listing", "role-card", or use
    # data-testid attributes. The link always goes to /jobs/<slug>.
    cards = (
        soup.find_all("article")
        or soup.find_all("li", class_=re.compile(r"job|role|listing", re.I))
        or soup.find_all("div", class_=re.compile(r"job-card|role-card|listing-card", re.I))
    )

    # Broad fallback: collect distinct parents of /jobs/<slug> links
    if not cards:
        seen = set()
        for lnk in soup.find_all("a", href=re.compile(r"/jobs/[a-zA-Z0-9-]+")):
            parent = lnk.find_parent(["article", "li", "section", "div"])
            if parent and id(parent) not in seen:
                seen.add(id(parent))
                cards.append(parent)

    for card in cards:
        link = card.find("a", href=re.compile(r"/jobs/"))
        if not link:
            continue
        href = link.get("href", "")
        job_url = href if href.startswith("http") else urljoin(base_url, href)

        # Title
        title_el = (
            card.find(["h2", "h3"])
            or card.find(class_=re.compile(r"title|role|position", re.I))
        )
        title = title_el.get_text(strip=True) if title_el else link.get_text(strip=True)

        # Company — Pallet boards are portfolio boards, so company = portfolio company
        company_el = (
            card.find(class_=re.compile(r"company|employer|startup|org", re.I))
            or card.find(attrs={"data-company": True})
        )
        company = company_el.get_text(strip=True) if company_el else ""

        # Location
        location_el = card.find(class_=re.compile(r"location|place|city|remote", re.I))
        location = location_el.get_text(strip=True) if location_el else ""

        # Salary badge (Pallet sometimes shows a "$X–$Y" badge)
        salary_el = card.find(class_=re.compile(r"salary|pay|comp|remuneration", re.I))
        if salary_el:
            salary_text = salary_el.get_text(strip=True)
        else:
            m = re.search(
                r"(?:NZ\$|AU\$|\$|NZD|AUD|USD)\s*[\d,]+[kKmM]?"
                r"(?:\s*[-–]\s*(?:NZ\$|AU\$|\$)?\s*[\d,]+[kKmM]?)?",
                card.get_text(), re.I,
            )
            salary_text = m.group(0) if m else ""

        # Tags — Pallet boards often show tech stack / role type tags
        tags = [t.get_text(strip=True) for t in card.find_all(class_=re.compile(r"tag|badge|chip", re.I))]

        # Date
        date_el = card.find("time")
        posted_raw = date_el.get("datetime", "") if date_el else ""

        results.append({
            "url": job_url,
            "title": title,
            "company": company,
            "location": location,
            "salary_text": salary_text,
            "tags": tags,
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

    # Salary — explicit section first
    for el in soup.find_all(class_=re.compile(r"salary|pay|compensation|remuneration", re.I)):
        t = el.get_text(strip=True)
        if any(c.isdigit() for c in t):
            salary_text = t
            break

    if not salary_text:
        m = re.search(
            r"(?:NZ\$|AU\$|\$|NZD|AUD|USD)\s*[\d,]+[kKmM]?\s*[-–—to]+\s*"
            r"(?:NZ\$|AU\$|\$|NZD|AUD|USD)?\s*[\d,]+[kKmM]?",
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


async def _scrape_board(
    client: httpx.AsyncClient,
    board: Dict[str, Any],
    rejected_log: List[Dict],
    min_confidence: float,
    seen_urls: set,
) -> List[Listing]:
    listings: List[Listing] = []
    board_name = board["name"]
    base_url = board["base_url"]
    country_hint = board["country"]
    source_id = f"vc_{board_name}"

    for query in SEARCH_QUERIES:
        path = board["search_path"].format(query=query.replace(" ", "+"))
        url = f"{base_url}{path}"
        logger.info("[%s] Searching: %s", source_id, query)

        html = await _fetch(client, url, board_name)
        if not html:
            await asyncio.sleep(REQUEST_DELAY)
            continue

        # Choose parser based on platform
        if board["platform"] == "pallet":
            cards = _parse_pallet(html, base_url)
        else:
            cards = _parse_pallet(html, base_url)  # custom boards often look similar

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
                    "reason": "title_excluded_or_unmatched", "source": source_id,
                })
                continue

            seniority, confidence = classification
            if confidence < min_confidence:
                rejected_log.append({
                    "url": job_url, "title": title,
                    "reason": f"low_confidence_{confidence:.2f}", "source": source_id,
                })
                continue

            await asyncio.sleep(REQUEST_DELAY)
            detail_html = await _fetch(client, job_url, board_name)
            detail = _parse_detail(detail_html) if detail_html else {}

            description = detail.get("description", "") or card.get("description", "")
            salary_text = detail.get("salary_text", "") or card.get("salary_text", "")

            parsed_sal = parse_salary(salary_text, country=country_hint)
            if parsed_sal.rejected:
                rejected_log.append({
                    "url": job_url, "title": title,
                    "reason": parsed_sal.rejection_reason, "source": source_id,
                })

            raw_location = card.get("location", "") or country_hint
            scope_signals = extract_scope_signals(description)
            company = card.get("company", "Unknown")
            country = infer_country(raw_location, f"vc_{country_hint.lower()}")
            city = extract_city(raw_location)
            company_size = infer_company_size(description) or "startup"  # VC portfolio default
            posted_date = _parse_date(card.get("posted_raw", ""))

            listing = Listing(
                id=make_id(source_id, job_url),
                source=source_id,
                url=job_url,
                title=title,
                company=company,
                company_size=company_size,
                location=raw_location or country_hint,
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
                posted_date=posted_date,
                scraped_date=date.today(),
            )
            listings.append(listing)
            logger.info("[%s] ✓ %s | %s", source_id, title, company)

        await asyncio.sleep(REQUEST_DELAY)

    return listings


async def scrape(
    rejected_log: List[Dict],
    min_confidence: float = 0.65,
) -> List[Listing]:
    listings: List[Listing] = []
    seen_urls: set = set()

    async with httpx.AsyncClient() as client:
        for board in VC_BOARDS:
            board_listings = await _scrape_board(
                client, board, rejected_log, min_confidence, seen_urls
            )
            listings.extend(board_listings)
            logger.info("[vc_%s] %d listings collected.", board["name"], len(board_listings))

    logger.info("[vc_boards] Total: %d listings collected.", len(listings))
    return listings


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    rejected: List[Dict] = []
    results = asyncio.run(scrape(rejected))
    print(json.dumps([r.model_dump(mode="json") for r in results], indent=2))
    print(f"\n{len(results)} listings, {len(rejected)} rejected", file=sys.stderr)
