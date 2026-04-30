"""
Hiring.cafe scraper — RevOps, GTM Ops, GTM Engineering roles across US/UK/AU/NZ.

hiring.cafe is a salary-first job aggregator (JS-rendered SPA). We use Playwright,
intercepting the underlying API responses for structured compensation data.
Falls back to DOM parsing if the API shape changes.

The site sorts by compensation_desc — the first page already contains the
highest-paying roles, making it the best single source for global benchmarking.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from datetime import date, datetime, timedelta
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

SOURCE = "hiring_cafe"
BASE_URL = "https://hiring.cafe"
REQUEST_DELAY = 3.0
MAX_SCROLL_ROUNDS = 8      # infinite-scroll iterations
SCROLL_PAUSE = 2.5         # seconds between scrolls

# Exact URL provided by user — RevOps/GTM Ops/GTM Engineering across US/UK/AU/NZ,
# all time, sorted by highest compensation first. Uses + encoding to match browser exactly.
SEARCH_URL = (
    "https://hiring.cafe/?searchState=%7B%22jobTitleQuery%22%3A%22%5C%22revenue+operations%5C%22%2C"
    "+%5C%22gtm+operations%5C%22%2C+%5C%22revops%5C%22%2C+%5C%22gtm+engineering%5C%22%2C"
    "+%5C%22go+to+market+engineering%5C%22%2C+%5C%22go+to+market+operations%5C%22%2C"
    "+%5C%22ai+operations%5C%22%22%2C%22dateFetchedPastNDays%22%3A-1%2C%22sortBy%22%3A"
    "%22compensation_desc%22%2C%22locations%22%3A%5B%7B%22id%22%3A%22LBY1yZQBoEtHp_8UEq3V%22%2C"
    "%22types%22%3A%5B%22continent%22%5D%2C%22address_components%22%3A%5B%7B%22long_name%22%3A"
    "%22Australia%22%2C%22short_name%22%3A%22Australia%22%2C%22types%22%3A%5B%22continent%22%5D%7D%5D"
    "%2C%22formatted_address%22%3A%22Australia+%2F+Oceania%22%2C%22population%22%3A42000000%2C"
    "%22workplace_types%22%3A%5B%5D%2C%22options%22%3A%7B%22flexible_regions%22%3A%5B%22anywhere_in_world%22%5D%7D%7D"
    "%2C%7B%22id%22%3A%22FxY1yZQBoEtHp_8UEq7V%22%2C%22types%22%3A%5B%22country%22%5D%2C"
    "%22address_components%22%3A%5B%7B%22long_name%22%3A%22United+States%22%2C%22short_name%22%3A%22US%22%2C"
    "%22types%22%3A%5B%22country%22%5D%7D%5D%2C%22formatted_address%22%3A%22United+States%22%2C"
    "%22population%22%3A327167434%2C%22workplace_types%22%3A%5B%5D%2C%22options%22%3A%7B%22flexible_regions%22%3A"
    "%5B%22anywhere_in_continent%22%2C%22anywhere_in_world%22%5D%7D%7D%2C%7B%22id%22%3A%22ehY1yZQBoEtHp_8UEq3V%22%2C"
    "%22types%22%3A%5B%22country%22%5D%2C%22address_components%22%3A%5B%7B%22long_name%22%3A%22United+Kingdom%22%2C"
    "%22short_name%22%3A%22GB%22%2C%22types%22%3A%5B%22country%22%5D%7D%5D%2C%22formatted_address%22%3A"
    "%22United+Kingdom%22%2C%22population%22%3A66488991%2C%22workplace_types%22%3A%5B%5D%2C%22options%22%3A"
    "%7B%22flexible_regions%22%3A%5B%22anywhere_in_continent%22%2C%22anywhere_in_world%22%5D%7D%7D%2C"
    "%7B%22id%22%3A%222RY1yZQBoEtHp_8UEq3V%22%2C%22types%22%3A%5B%22country%22%5D%2C%22address_components%22%3A"
    "%5B%7B%22long_name%22%3A%22New%20Zealand%22%2C%22short_name%22%3A%22NZ%22%2C%22types%22%3A%5B%22country%22%5D%7D%5D"
    "%2C%22formatted_address%22%3A%22New%20Zealand%22%2C%22population%22%3A4885500%2C%22workplace_types%22%3A%5B%5D%2C"
    "%22options%22%3A%7B%22flexible_regions%22%3A%5B%22anywhere_in_continent%22%2C%22anywhere_in_world%22%5D%7D%7D%5D%7D"
)


def _extract_from_api_payload(payload: Any) -> List[Dict[str, Any]]:
    """Walk a JSON payload (any depth) and pull out job-like objects."""
    results = []

    def _walk(node: Any, depth: int = 0) -> None:
        if depth > 8:
            return
        if isinstance(node, list):
            for item in node:
                _walk(item, depth + 1)
        elif isinstance(node, dict):
            # Recognise a job object: must have title and one of company/employer
            has_title = any(k in node for k in ("title", "jobTitle", "job_title", "name"))
            has_company = any(k in node for k in (
                "company", "companyName", "employer", "organization",
                "startup", "startupName",
            ))
            if has_title and has_company:
                results.append(node)
                return  # don't recurse into the job object itself
            for v in node.values():
                _walk(v, depth + 1)

    _walk(payload)
    return results


def _parse_ssr_hits(page_props: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Parse hiring.cafe's ssrHits array from __NEXT_DATA__ pageProps.

    Structure (confirmed from live page):
      pageProps.ssrHits[].job_information.title
      pageProps.ssrHits[].v5_processed_job_data.company_name
      pageProps.ssrHits[].v5_processed_job_data.yearly_min/max_compensation
      pageProps.ssrHits[].v5_processed_job_data.listed_compensation_currency
      pageProps.ssrHits[].v5_processed_job_data.formatted_workplace_location
      pageProps.ssrHits[].apply_url
    """
    hits = page_props.get("ssrHits", [])
    if not hits:
        return []

    results = []
    for hit in hits:
        processed = hit.get("v5_processed_job_data", {})
        job_info = hit.get("job_information", {})

        title = (job_info.get("title")
                 or job_info.get("job_title_raw")
                 or processed.get("title", ""))
        if not title:
            continue

        company = (processed.get("company_name")
                   or hit.get("enriched_company_data", {}).get("name", ""))

        salary_min = processed.get("yearly_min_compensation")
        salary_max = processed.get("yearly_max_compensation")
        currency = processed.get("listed_compensation_currency") or "USD"

        if salary_min and salary_max:
            salary_text = f"{currency} {salary_min}-{salary_max}"
        elif salary_min:
            salary_text = f"{currency} {salary_min}"
        else:
            salary_text = ""

        location = processed.get("formatted_workplace_location", "")
        if not location:
            countries = processed.get("workplace_countries", [])
            location = ", ".join(countries) if countries else ""

        url = hit.get("apply_url") or hit.get("job_url") or ""
        posted_raw = processed.get("estimated_publish_date", "")

        description = ""
        if isinstance(job_info.get("description"), str):
            description = job_info["description"][:3000]

        results.append({
            "url": str(url),
            "title": str(title),
            "company": str(company),
            "location": location,
            "salary_text": salary_text,
            "description": description,
            "posted_raw": str(posted_raw),
        })

    return results


def _normalise_job_dict(obj: Dict[str, Any]) -> Dict[str, Any]:
    """Flatten a raw job dict from the API into a consistent shape."""
    def _first(*keys: str, default: Any = "") -> Any:
        for k in keys:
            if obj.get(k):
                return obj[k]
        return default

    title = _first("title", "jobTitle", "job_title", "name")
    company = _first("company", "companyName", "employer", "organization",
                     "startup", "startupName")
    if isinstance(company, dict):
        company = company.get("name") or company.get("displayName") or str(company)

    # Location — may be string, dict, or list
    raw_loc = _first("location", "locationNames", "jobLocation", "city", "address")
    if isinstance(raw_loc, list):
        raw_loc = ", ".join(str(x) for x in raw_loc if x)
    elif isinstance(raw_loc, dict):
        raw_loc = (raw_loc.get("formatted_address") or raw_loc.get("name")
                   or raw_loc.get("city") or str(raw_loc))
    location = str(raw_loc) if raw_loc else ""

    # Salary — structured or text
    salary_text = ""
    comp = obj.get("compensation") or obj.get("salary") or obj.get("pay") or {}
    if isinstance(comp, dict):
        lo = comp.get("min") or comp.get("minimum") or comp.get("base")
        hi = comp.get("max") or comp.get("maximum")
        curr = comp.get("currency") or comp.get("currencyCode") or ""
        if lo and hi:
            salary_text = f"{curr} {lo}–{hi}" if curr else f"{lo}–{hi}"
        elif lo:
            salary_text = f"{curr} {lo}" if curr else str(lo)
        else:
            salary_text = comp.get("text") or comp.get("display") or ""
    elif isinstance(comp, str):
        salary_text = comp
    if not salary_text:
        salary_text = (obj.get("salaryRange") or obj.get("compensationText")
                       or obj.get("payRange") or "")

    # Date
    posted_raw = _first("datePosted", "postedAt", "posted_at", "createdAt",
                        "created_at", "listingDate", "publishedAt")
    if isinstance(posted_raw, (int, float)):
        # Unix timestamp
        try:
            posted_raw = datetime.fromtimestamp(posted_raw / 1000).strftime("%Y-%m-%d")
        except Exception:
            posted_raw = ""

    description = _first("description", "body", "jobDescription", "content")
    if isinstance(description, dict):
        description = description.get("text") or description.get("html") or ""

    url = _first("url", "jobUrl", "applyUrl", "link", "href")
    if url and not url.startswith("http"):
        url = f"{BASE_URL}{url}"

    return {
        "url": str(url),
        "title": str(title),
        "company": str(company),
        "location": location,
        "salary_text": str(salary_text),
        "description": str(description)[:3000],
        "posted_raw": str(posted_raw),
    }


def _parse_dom_cards(html: str) -> List[Dict[str, Any]]:
    """DOM fallback: extract job cards from the rendered HTML."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    results = []

    # hiring.cafe job cards — try several selector strategies
    cards = (
        soup.find_all("div", attrs={"data-job-id": True})
        or soup.find_all("article", class_=re.compile(r"job|listing|result", re.I))
        or soup.find_all("div", class_=re.compile(r"job.?card|listing.?card|result.?card", re.I))
        or soup.find_all("li", class_=re.compile(r"job|listing|result", re.I))
    )

    # Broad fallback: parents of links that look like job detail URLs
    if not cards:
        seen = set()
        for a in soup.find_all("a", href=re.compile(r"/job[s]?/|/role/|/opening/")):
            parent = a.find_parent(["article", "li", "div", "section"])
            if parent and id(parent) not in seen:
                seen.add(id(parent))
                cards.append(parent)

    for card in cards:
        link = (
            card.find("a", href=re.compile(r"/job[s]?/|/role/|/opening/"))
            or card.find("a", href=re.compile(r"hiring\.cafe"))
        )
        href = (link.get("href", "") if link else "")
        url = href if href.startswith("http") else (f"{BASE_URL}{href}" if href else "")

        title_el = (
            card.find(["h1", "h2", "h3", "h4"])
            or card.find(class_=re.compile(r"title|role|position|job.?name", re.I))
        )
        title = title_el.get_text(strip=True) if title_el else (link.get_text(strip=True) if link else "")

        company_el = card.find(class_=re.compile(r"company|employer|org|brand|startup", re.I))
        company = company_el.get_text(strip=True) if company_el else ""

        location_el = card.find(class_=re.compile(r"location|city|place|region|country", re.I))
        location = location_el.get_text(strip=True) if location_el else ""

        # Salary — hiring.cafe shows compensation prominently
        salary_el = card.find(class_=re.compile(r"salary|compensation|comp|pay|wage", re.I))
        if salary_el:
            salary_text = salary_el.get_text(strip=True)
        else:
            card_text = card.get_text()
            m = re.search(
                r"(?:£|US\$|AU\$|NZ\$|\$|USD|GBP|AUD)\s*[\d,]+[kKmM]?"
                r"(?:\s*[-–]\s*(?:£|US\$|AU\$|NZ\$|\$|USD|GBP|AUD)?\s*[\d,]+[kKmM]?)?",
                card_text, re.I,
            )
            salary_text = m.group(0) if m else ""

        date_el = card.find("time")
        posted_raw = date_el.get("datetime", "") if date_el else ""

        if title and url:
            results.append({
                "url": url,
                "title": title,
                "company": company,
                "location": location,
                "salary_text": salary_text,
                "description": card.get_text(separator=" ", strip=True)[:2000],
                "posted_raw": posted_raw,
            })

    return results


def _extract_from_nextjs_data(html: str) -> tuple[List[Dict[str, Any]], int, int]:
    """
    Parse the embedded Next.js __NEXT_DATA__ JSON from the page HTML.
    Returns (jobs, current_page, total_count).
    """
    match = re.search(
        r'<script\s[^>]*id=["\']__NEXT_DATA__["\'][^>]*>\s*(\{.*?\})\s*</script>',
        html, re.S
    )
    if not match:
        logger.warning("[hiring_cafe] __NEXT_DATA__ script tag not found in HTML")
        return [], 0, 0

    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        logger.warning("[hiring_cafe] Failed to parse __NEXT_DATA__ JSON: %s", exc)
        return [], 0, 0

    page_props = data.get("props", {}).get("pageProps", {})
    total_count = page_props.get("ssrTotalCount", 0)
    current_page = page_props.get("ssrPage", 0)

    # hiring.cafe-specific: ssrHits array with nested structure
    if "ssrHits" in page_props:
        results = _parse_ssr_hits(page_props)
        logger.info(
            "[hiring_cafe] __NEXT_DATA__ ssrHits: %d jobs (page %d of ~%d total)",
            len(results), current_page,
            total_count,
        )
        return results, current_page, total_count

    # Generic fallback for unknown structures
    logger.info("[hiring_cafe] ssrHits not found — trying generic walk (keys: %s)",
                list(page_props.keys())[:10])
    results = _extract_from_api_payload(data)
    logger.info("[hiring_cafe] generic extract: %d job-like objects", len(results))
    return results, current_page, total_count


def _parse_date(raw: str) -> Optional[date]:
    if not raw:
        return None
    raw = str(raw).strip()
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw[:19], fmt[:len(raw[:19])]).date()
        except ValueError:
            continue
    m = re.search(r"(\d+)\s+day", raw, re.I)
    if m:
        return (datetime.now() - timedelta(days=int(m.group(1)))).date()
    return None


async def _fetch_page(url: str, page_num: int = 0) -> Optional[tuple[str, List[Dict]]]:
    """
    Load the page with Playwright. Returns (html, api_jobs) where api_jobs is
    a list of raw job dicts captured from intercepted API responses.
    """
    try:
        from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout
    except ImportError:
        logger.error("[hiring_cafe] Playwright not installed — run: pip install playwright && playwright install chromium")
        return None

    cache_key = f"hiring_cafe:{url}"
    cached = _cache_get(cache_key)
    if cached:
        logger.debug("[hiring_cafe] Cache hit")
        # Cached is HTML only; we'll parse DOM
        return cached, []

    api_jobs: List[Dict] = []

    async def _on_response(response):
        content_type = response.headers.get("content-type", "")
        if "json" not in content_type:
            return
        # Skip tiny responses and known non-data endpoints
        if any(skip in response.url for skip in (
            "analytics", "tracking", "metrics", "sentry", "gtag", "clarity",
            "hotjar", "segment", "mixpanel",
        )):
            return
        try:
            body = await response.json()
            extracted = _extract_from_api_payload(body)
            if extracted:
                logger.debug("[hiring_cafe] API hit: %d jobs from %s", len(extracted), response.url[:80])
                api_jobs.extend(extracted)
        except Exception:
            pass

    try:
        # Read CF clearance from environment — never hardcode
        cf_clearance = os.environ.get("CF_CLEARANCE", "").strip()
        if not cf_clearance:
            logger.warning(
                "[hiring_cafe] CF_CLEARANCE env var not set. "
                "Cloudflare will likely block. Set it with your browser cookie:\n"
                "  export CF_CLEARANCE='<value from hiring.cafe cookies>'\n"
                "  make scrape SOURCE=hiring_cafe"
            )

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                ],
            )
            # Match the exact Chrome version from the user's real browser (Chrome 147 on macOS)
            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/147.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1440, "height": 900},
                locale="en-US",
                timezone_id="Pacific/Auckland",
            )
            await context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
                Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
                window.chrome = { runtime: {}, loadTimes: () => {}, csi: () => {}, app: {} };
            """)

            # Inject the real CF clearance cookie from the user's browser session
            if cf_clearance:
                await context.add_cookies([{
                    "name": "cf_clearance",
                    "value": cf_clearance,
                    "domain": "hiring.cafe",
                    "path": "/",
                    "secure": True,
                    "sameSite": "None",
                }])
                logger.info("[hiring_cafe] CF clearance cookie injected")

            page = await context.new_page()
            page.on("response", _on_response)

            try:
                try:
                    from playwright_stealth import stealth_async
                    await stealth_async(page)
                except (ImportError, AttributeError):
                    from playwright_stealth import Stealth
                    await Stealth().apply_stealth_async(page)
                logger.debug("[hiring_cafe] Stealth patches applied")
            except Exception as exc:
                logger.debug("[hiring_cafe] playwright-stealth unavailable: %s", exc)

            try:
                logger.info("[hiring_cafe] Loading search page…")
                await page.goto(url, timeout=60_000, wait_until="load")

                # Give JS time to hydrate and fetch initial data
                await asyncio.sleep(5)

                # Diagnose what we got before waiting for selectors
                page_title = await page.title()
                body_text_len = await page.evaluate("() => document.body?.innerText?.length || 0")
                logger.info("[hiring_cafe] Page loaded — title: %r, body text length: %d", page_title, body_text_len)

                # Save debug HTML (overwritten each run, inspect at data/cache/hiring_cafe_debug.html)
                debug_html = await page.content()
                from pathlib import Path
                Path("data/cache").mkdir(parents=True, exist_ok=True)
                debug_path = f"data/cache/hiring_cafe_debug_p{page_num}.html"
                Path(debug_path).write_text(debug_html, encoding="utf-8")
                logger.info("[hiring_cafe] Debug HTML saved to %s (%d bytes)", debug_path, len(debug_html))

                # Wait for job content
                try:
                    await page.wait_for_selector(
                        "article, [class*='job'], [class*='listing'], [class*='result'], "
                        "[class*='card'], main a[href*='/job']",
                        timeout=15_000,
                    )
                    logger.info("[hiring_cafe] Job content found in DOM")
                except PlaywrightTimeout:
                    logger.warning("[hiring_cafe] No job selectors matched — site may be blocking headless browsers. "
                                   "Inspect data/cache/hiring_cafe_debug.html to see what was rendered.")

                await asyncio.sleep(2)

                # Scroll to trigger lazy-loaded content
                prev_count = len(api_jobs)
                for round_num in range(MAX_SCROLL_ROUNDS):
                    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    await asyncio.sleep(SCROLL_PAUSE)
                    new_count = len(api_jobs)
                    logger.debug("[hiring_cafe] Scroll %d: %d total jobs captured", round_num + 1, new_count)
                    if new_count == prev_count and round_num > 1:
                        break
                    prev_count = new_count

                html = await page.content()
                _cache_set(cache_key, html)
                return html, api_jobs

            except PlaywrightTimeout:
                logger.warning("[hiring_cafe] Page load timeout — trying with whatever content loaded")
                try:
                    html = await page.content()
                    if len(html) > 5000:  # got some content
                        return html, api_jobs
                except Exception:
                    pass
                return None
            finally:
                await browser.close()

    except Exception as exc:
        logger.warning("[hiring_cafe] Playwright error: %s", exc)
        return None


async def scrape(
    rejected_log: List[Dict],
    min_confidence: float = 0.75,
) -> List[Listing]:
    listings: List[Listing] = []
    seen_urls: set = set()
    all_raw_jobs: List[Dict] = []

    max_pages = 10  # safety cap; updated after first page based on ssrTotalCount
    page_num = 0

    while page_num < max_pages:
        page_url = SEARCH_URL if page_num == 0 else f"{SEARCH_URL}&page={page_num}"
        result = await _fetch_page(page_url, page_num)
        if not result:
            logger.error("[hiring_cafe] Page %d failed — stopping", page_num)
            break

        html, api_jobs = result

        # Priority: API interception → __NEXT_DATA__ ssrHits → DOM
        page_raw: List[Dict] = []
        if api_jobs:
            logger.info("[hiring_cafe] Page %d: %d jobs from API interception", page_num, len(api_jobs))
            page_raw = [_normalise_job_dict(j) for j in api_jobs]
        else:
            nextjs_jobs, _, total_count = _extract_from_nextjs_data(html)
            if nextjs_jobs:
                page_raw = nextjs_jobs
                if page_num == 0 and total_count:
                    page_size = len(nextjs_jobs)
                    if page_size:
                        max_pages = min((total_count + page_size - 1) // page_size, 10)
                        logger.info(
                            "[hiring_cafe] %d total jobs, page size %d → %d pages to fetch",
                            total_count, page_size, max_pages,
                        )
            else:
                logger.info("[hiring_cafe] Page %d: trying DOM fallback", page_num)
                page_raw = _parse_dom_cards(html)

        if not page_raw:
            logger.warning("[hiring_cafe] Page %d: no jobs found — stopping pagination", page_num)
            break

        logger.info("[hiring_cafe] Page %d: %d raw jobs", page_num, len(page_raw))
        all_raw_jobs.extend(page_raw)
        page_num += 1

        if page_num < max_pages:
            await asyncio.sleep(REQUEST_DELAY)

    raw_jobs = all_raw_jobs
    logger.info("[hiring_cafe] Total raw jobs collected across all pages: %d", len(raw_jobs))

    for raw in raw_jobs:
        title = raw.get("title", "").strip()
        if not title:
            continue

        # Deduplicate by URL; fall back to title+company if URL missing
        job_url = raw.get("url", "").strip()
        dedup_key = job_url or f"{title}::{raw.get('company', '')}".lower()
        if dedup_key in seen_urls:
            continue
        seen_urls.add(dedup_key)

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

        raw_location = raw.get("location", "")
        country = infer_country(raw_location, SOURCE)

        description = raw.get("description", "")
        salary_text = raw.get("salary_text", "")

        # Derive currency country hint from inferred country
        country_for_salary = country if country in ("NZ", "AU", "US", "UK") else "US"
        parsed_sal = parse_salary(salary_text, country=country_for_salary)
        if parsed_sal.rejected:
            rejected_log.append({
                "url": job_url, "title": title,
                "reason": parsed_sal.rejection_reason, "source": SOURCE,
            })

        scope_signals = extract_scope_signals(description)
        company = raw.get("company", "Unknown") or "Unknown"
        city = extract_city(raw_location)
        company_size = infer_company_size(description)
        posted_date = _parse_date(raw.get("posted_raw", ""))

        # Ensure URL is set even if API didn't return one
        if not job_url:
            job_url = f"{BASE_URL}/jobs/{make_id(SOURCE, f'{title}::{company}')}"

        listing = Listing(
            id=make_id(SOURCE, job_url),
            source=SOURCE,
            url=job_url,
            title=title,
            company=company,
            company_size=company_size,
            location=raw_location or country,
            country=country,
            city=city,
            salary_min=parsed_sal.salary_min,
            salary_max=parsed_sal.salary_max,
            salary_currency=parsed_sal.currency,
            salary_includes_super=parsed_sal.includes_super if country == "AU" else None,
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
        logger.info("[hiring_cafe] ✓ %s | %s | %s | salary: %s",
                    title, company, country,
                    f"{parsed_sal.salary_min}–{parsed_sal.salary_max} {parsed_sal.currency}"
                    if parsed_sal.salary_min else "none")

        await asyncio.sleep(0.05)  # light throttle between records

    logger.info("[hiring_cafe] Done. %d listings collected.", len(listings))
    return listings


if __name__ == "__main__":
    import sys
    import json as _json
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    rejected: List[Dict] = []
    results = asyncio.run(scrape(rejected))
    print(_json.dumps([r.model_dump(mode="json") for r in results], indent=2))
    print(f"\n{len(results)} listings, {len(rejected)} rejected", file=sys.stderr)
