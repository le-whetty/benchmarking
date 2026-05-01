"""
Title classification, seniority mapping, scope signal extraction,
and company size inference.
"""
from __future__ import annotations

import re
from typing import List, Optional, Tuple

# ── title taxonomy ────────────────────────────────────────────────────────────

# Each entry: (regex pattern, seniority, base_confidence)
TITLE_RULES: List[Tuple[re.Pattern, str, float]] = [
    # VP level — "sales" alone is too broad (VP of Sales ≠ VP RevOps); require ops context
    (re.compile(r"\bvp\b.*(revenue\s+op|revops|sales\s+op|gtm\s+op|go.?to.?market)", re.I), "vp", 0.95),
    (re.compile(r"\bvice\s+president\b.*(revenue\s+op|sales\s+op|gtm|go.?to.?market)", re.I), "vp", 0.95),

    # Director level — require "operations/ops" alongside revenue/sales/commercial
    (re.compile(r"\bdirector\b.*(revenue\s+op|revops|sales\s+op|gtm\s+op|go.?to.?market\s+op)", re.I), "director", 0.95),
    (re.compile(r"\bdirector\b.*(gtm|go.?to.?market)", re.I), "director", 0.90),
    (re.compile(r"\bdirector\b.*(revenue|sales)\s+op", re.I), "director", 0.90),
    (re.compile(r"\bdirector\b.*(revenue|sales|commercial)\b", re.I), "director", 0.72),

    # Head of — require ops/operations suffix for commercial/sales; revenue/GTM alone ok
    (re.compile(r"\bhead\s+of\b.*(revenue\s+op|revops|gtm\s+op|go.?to.?market\s+op|sales\s+op)", re.I), "head", 0.95),
    (re.compile(r"\bhead\s+of\b.*(revenue|gtm|go.?to.?market)", re.I), "head", 0.88),
    (re.compile(r"\bhead\s+of\b.*(commercial\s+op|business\s+op|sales\s+op)", re.I), "head", 0.82),
    (re.compile(r"\bhead\s+of\b.*(commercial|sales)\b", re.I), "head", 0.62),

    # Senior Manager — only specific RevOps/GTM terms
    (re.compile(r"\bsenior\s+manager\b.*(revenue\s+op|revops|gtm\s+op|sales\s+op)", re.I), "senior_manager", 0.88),
    (re.compile(r"\bsenior\s+manager\b.*(revenue|gtm)", re.I), "senior_manager", 0.75),

    # Manager — only very specific terms pass the default 0.75 threshold
    (re.compile(r"\bmanager\b.*(revenue\s+op|revops|gtm\s+op|sales\s+op)", re.I), "manager", 0.78),

    # GTM Strategy leads
    (re.compile(r"\bgtm\s+(strategy|operations|ops)\b", re.I), "head", 0.82),
    (re.compile(r"\brevenue\s+(strategy|operations|ops)\b", re.I), "head", 0.82),
    (re.compile(r"\bgo.?to.?market\s+(strategy|lead|operations)", re.I), "head", 0.82),

    # GTM Engineering — technical RevOps (automation, tooling, integrations)
    (re.compile(r"\b(head|director|vp|lead)\b.*(gtm|go.?to.?market).+engineer", re.I), "head", 0.90),
    (re.compile(r"\b(head|director|vp|lead)\b.*revops?\s+engineer", re.I), "head", 0.90),
    (re.compile(r"\bgtm\s+engineer(ing)?\b", re.I), "manager", 0.82),
    (re.compile(r"\bgo.?to.?market\s+engineer(ing)?\b", re.I), "manager", 0.82),
    (re.compile(r"\brevops?\s+engineer(ing)?\b", re.I), "manager", 0.80),
    (re.compile(r"\bsales\s+systems?\s+(engineer|architect|admin)\b", re.I), "manager", 0.78),
    (re.compile(r"\bai\s+(sales|gtm|revenue)\s+(engineer|ops|automation)\b", re.I), "manager", 0.78),

    # AI GTM roles — applies AI/automation to the GTM motion (sits under GTM Ops function)
    (re.compile(r"\b(head|director|vp|lead)\b.*(ai\s+gtm|gtm\s+ai|ai\s+go.?to.?market)", re.I), "head", 0.90),
    (re.compile(r"\bai\s+gtm\s+(lead|manager|ops|operations|engineer(ing)?)\b", re.I), "head", 0.88),
    (re.compile(r"\bai\s+gtm\b", re.I), "manager", 0.82),
    (re.compile(r"\bgtm\s+ai\b", re.I), "manager", 0.82),
]

# Patterns that immediately disqualify a title
EXCLUDE_PATTERNS = [
    # IC / junior roles
    re.compile(r"\b(analyst|coordinator|specialist|associate|junior|intern)\b", re.I),
    # Single-function ops (not cross-GTM)
    re.compile(r"\bmarketing\s+op", re.I),
    re.compile(r"\bcustomer\s+success\s+op", re.I),
    # Structural red flags — not GTM leadership roles
    re.compile(r"\b(deputy\s+head|group\s+head|assistant\s+head)\b", re.I),
    re.compile(r"\bnational\s+manager\b", re.I),
    # Non-GTM industries appearing in the title itself
    re.compile(r"\b(campus|clinical|school|hospital|aged\s+care|disability)\b", re.I),
    re.compile(r"\b(facilities|warehouse|fleet|supply\s+chain|transport(?:ation)?|logistics)\b", re.I),
    # Finance / legal confusion
    re.compile(r"\b(commercial\s+partner|commercial\s+trading|commercial\s+counsel|finance\s+lead|chief\s+financial)\b", re.I),
    # "VP of Sales" without operations context — too far from RevOps scope
    re.compile(r"\bvp\s+of\s+sales\b(?!\s*(op|&|and))", re.I),
]


def classify_title(title: str) -> Optional[Tuple[str, float]]:
    """Return (seniority, confidence) or None if excluded/unmatched."""
    for pattern in EXCLUDE_PATTERNS:
        if pattern.search(title):
            return None

    for pattern, seniority, confidence in TITLE_RULES:
        if pattern.search(title):
            return seniority, confidence

    return None


# ── scope signal extraction ───────────────────────────────────────────────────

_SCOPE_RULES = [
    ("manages_team", re.compile(
        r"(manage|lead|build|grow|head up).{0,40}team|team\s+of\s+\d+|\d+\s+(direct\s+)?report",
        re.I,
    )),
    ("reports_to_c_suite", re.compile(
        r"report(ing|s)?\s+to\s+(the\s+)?(CRO|CEO|COO|CFO|VP\s+of\s+Revenue|Chief\s+Revenue)",
        re.I,
    )),
    ("owns_crm_stack", re.compile(
        r"(HubSpot|Salesforce|Vitally|Outreach|Apollo|Clay|Gong|Salesloft|6sense|ZoomInfo)",
        re.I,
    )),
    ("owns_forecasting", re.compile(
        r"(forecast|revenue\s+plan|territory\s+design|quota|comp\s+plan|compensation\s+plan)",
        re.I,
    )),
    ("cross_functional", re.compile(
        r"(sales\s+and\s+marketing|marketing\s+and\s+sales|sales,?\s+marketing.{0,30}(and|&)\s+cs"
        r"|go.?to.?market\s+(team|function)|revenue\s+team)",
        re.I,
    )),
    ("ai_remit", re.compile(
        r"(AI|artificial\s+intelligence|automation|agentic|LLM|machine\s+learning)\s+"
        r"(for|in|across|to\s+drive|enabled)",
        re.I,
    )),
    ("multi_gtm_functions", re.compile(
        r"(sales\s+ops|sales\s+operations).{0,60}(marketing|customer\s+success|cs\b)",
        re.I,
    )),
]


def extract_scope_signals(text: str) -> List[str]:
    found = []
    for signal_name, pattern in _SCOPE_RULES:
        if pattern.search(text):
            found.append(signal_name)
    return found


# ── team size extraction ──────────────────────────────────────────────────────

_TEAM_SIZE_PATTERN = re.compile(
    r"team\s+of\s+(\d+)|(\d+)\s+(direct\s+)?reports?",
    re.I,
)


def extract_team_size(text: str) -> Optional[int]:
    m = _TEAM_SIZE_PATTERN.search(text)
    if m:
        return int(m.group(1) or m.group(2))
    return None


# ── city extraction ───────────────────────────────────────────────────────────

_NZ_CITIES = ["Auckland", "Wellington", "Christchurch", "Hamilton", "Tauranga",
               "Dunedin", "Napier", "Palmerston North", "Nelson", "Rotorua"]
_AU_CITIES = ["Sydney", "Melbourne", "Brisbane", "Perth", "Adelaide",
               "Canberra", "Gold Coast", "Newcastle", "Wollongong", "Hobart"]
_US_CITIES = ["San Francisco", "New York", "Chicago", "Austin", "Boston",
               "Seattle", "Los Angeles", "Denver", "Atlanta", "Miami",
               "San Jose", "Nashville", "Dallas", "Houston", "Minneapolis"]
_UK_CITIES = ["London", "Manchester", "Edinburgh", "Birmingham", "Bristol",
               "Leeds", "Glasgow", "Liverpool", "Sheffield", "Cambridge"]

_CITY_PATTERN = re.compile(
    r"\b(" + "|".join(_NZ_CITIES + _AU_CITIES + _US_CITIES + _UK_CITIES) + r")\b",
    re.I,
)


def extract_city(location: str) -> Optional[str]:
    m = _CITY_PATTERN.search(location)
    return m.group(1).title() if m else None


# ── country inference ─────────────────────────────────────────────────────────

# Word-boundary regex patterns. Order matters for multi-country listings:
# more-specific country names checked first; we prefer NZ > AU > US > UK
# for the markets we benchmark.

_NZ_PATTERN = re.compile(
    r"\b(NEW ZEALAND|NZL|"
    r"AUCKLAND|WELLINGTON|CHRISTCHURCH|HAMILTON|TAURANGA|DUNEDIN|NAPIER|NELSON)\b"
    r"|,\s*NZ\b",
)

_AU_PATTERN = re.compile(
    r"\b(AUSTRALIA|"
    r"SYDNEY|MELBOURNE|BRISBANE|PERTH|ADELAIDE|CANBERRA|HOBART|GOLD COAST|NEWCASTLE|"
    r"NEW SOUTH WALES|VICTORIA|QUEENSLAND|WESTERN AUSTRALIA|SOUTH AUSTRALIA|TASMANIA|"
    r"AUSTRALIAN CAPITAL TERRITORY|NORTHERN TERRITORY|"
    r"NSW|QLD|VIC|TAS|ACT)\b"
    r"|,\s*AU\b",
)

_US_PATTERN = re.compile(
    r"\b(UNITED STATES|U\.S\.A\.?|USA|"
    # State names
    r"CALIFORNIA|TEXAS|FLORIDA|MASSACHUSETTS|COLORADO|ILLINOIS|GEORGIA|VIRGINIA|"
    r"MICHIGAN|OHIO|ARIZONA|PENNSYLVANIA|TENNESSEE|MINNESOTA|"
    r"NORTH CAROLINA|SOUTH CAROLINA|NEW JERSEY|NEW YORK|"
    # Major cities
    r"SAN FRANCISCO|NEW YORK CITY|AUSTIN|BOSTON|SEATTLE|CHICAGO|DENVER|MIAMI|"
    r"LOS ANGELES|NASHVILLE|DALLAS|HOUSTON|ATLANTA|MINNEAPOLIS|PORTLAND|"
    r"PHOENIX|PHILADELPHIA|SAN DIEGO|SAN JOSE|RALEIGH|LAS VEGAS|REDWOOD CITY|"
    r"AUBURN HILLS|ARLINGTON|MALVERN|LIVINGSTON|VANCOUVER WA|"
    r"WASHINGTON, ?D\.?C\.?|WASHINGTON DC)\b"
    r"|,\s*(CA|NY|TX|FL|GA|VA|MA|IL|OH|MI|CO|WA|OR|AZ|NV|UT|MD|NC|SC|TN|KY|MN|PA|NJ|DC)\b",
)

_UK_PATTERN = re.compile(
    r"\b(UNITED KINGDOM|GREAT BRITAIN|ENGLAND|SCOTLAND|WALES|"
    r"LONDON|MANCHESTER|EDINBURGH|BIRMINGHAM|GLASGOW|BRISTOL|LEEDS|"
    r"LIVERPOOL|SHEFFIELD|CAMBRIDGE|OXFORD)\b"
    r"|,\s*UK\b|,\s*GB\b",
)


def infer_country(location: str, source: str) -> str:
    loc_upper = location.upper()

    # Specific country/city/state matches with word boundaries.
    # Priority: NZ > AU > US > UK (markets we benchmark, NZ-most-relevant first).
    if _NZ_PATTERN.search(loc_upper):
        return "NZ"
    if _AU_PATTERN.search(loc_upper):
        return "AU"
    if _US_PATTERN.search(loc_upper):
        return "US"
    if _UK_PATTERN.search(loc_upper):
        return "UK"
    if "REMOTE" in loc_upper:
        return "REMOTE"
    # Fall back to source hint
    if source.endswith("_nz"):
        return "NZ"
    if source.endswith("_au"):
        return "AU"
    if source.endswith("_us"):
        return "US"
    if source.endswith("_uk"):
        return "UK"
    return "ANZ"


# ── company size heuristics ───────────────────────────────────────────────────

_STARTUP_SIGNALS = re.compile(r"\b(startup|seed|series\s+[ab]|pre.?ipo|early.?stage)\b", re.I)
_SCALEUP_SIGNALS = re.compile(r"\b(scaleup|scale.up|series\s+[cd]|growth.?stage|hypergrowth)\b", re.I)
_ENTERPRISE_SIGNALS = re.compile(r"\b(enterprise|asx|nzx|nasdaq|nyse|fortune\s+\d+|global\s+team)\b", re.I)


def infer_company_size(text: str) -> Optional[str]:
    if _ENTERPRISE_SIGNALS.search(text):
        return "enterprise"
    if _SCALEUP_SIGNALS.search(text):
        return "scaleup"
    if _STARTUP_SIGNALS.search(text):
        return "startup"
    return None
