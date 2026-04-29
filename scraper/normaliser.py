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
    # VP level
    (re.compile(r"\bvp\b.*(revenue|revops|sales|gtm|go.?to.?market)", re.I), "vp", 0.95),
    (re.compile(r"\bvice\s+president\b.*(revenue|sales|gtm)", re.I), "vp", 0.95),

    # Director level
    (re.compile(r"\bdirector\b.*(revenue|revops|sales\s+op|gtm|go.?to.?market|commercial)", re.I), "director", 0.95),
    (re.compile(r"\bdirector\b.*operations", re.I), "director", 0.75),

    # Head of
    (re.compile(r"\bhead\s+of\b.*(revenue|revops|gtm|go.?to.?market|sales\s+op|commercial|business\s+op)", re.I), "head", 0.95),
    (re.compile(r"\bhead\s+of\b.*operations", re.I), "head", 0.70),

    # Senior Manager
    (re.compile(r"\bsenior\s+manager\b.*(revenue|revops|gtm|sales\s+op)", re.I), "senior_manager", 0.85),

    # Manager (lower confidence — needs scope signals to include)
    (re.compile(r"\bmanager\b.*(revenue|revops|gtm|sales\s+op)", re.I), "manager", 0.65),

    # Strategy / GTM leads
    (re.compile(r"\bgtm\s+(strategy|operations|ops)\b", re.I), "head", 0.80),
    (re.compile(r"\brevenue\s+(strategy|operations|ops)\b", re.I), "head", 0.80),
    (re.compile(r"\bgo.?to.?market\s+(strategy|lead|operations)", re.I), "head", 0.80),
]

# Patterns that immediately disqualify a title
EXCLUDE_PATTERNS = [
    re.compile(r"\b(analyst|coordinator|specialist|associate|junior|intern)\b", re.I),
    re.compile(r"\bmarketing\s+op", re.I),          # marketing ops only
    re.compile(r"\bcustomer\s+success\s+op", re.I),  # CS ops only
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

_CITY_PATTERN = re.compile(
    r"\b(" + "|".join(_NZ_CITIES + _AU_CITIES) + r")\b",
    re.I,
)


def extract_city(location: str) -> Optional[str]:
    m = _CITY_PATTERN.search(location)
    return m.group(1).title() if m else None


# ── country inference ─────────────────────────────────────────────────────────

def infer_country(location: str, source: str) -> str:
    loc_upper = location.upper()
    if any(c in loc_upper for c in ["NEW ZEALAND", "NZ", "NZL"]):
        return "NZ"
    if any(c in loc_upper for c in ["AUSTRALIA", "AU", "AUS", "NSW", "VIC", "QLD", "WA", "SA", "TAS", "ACT", "NT"]):
        return "AU"
    if "REMOTE" in loc_upper:
        return "REMOTE"
    # Fall back to source hint
    if source.endswith("_nz"):
        return "NZ"
    if source.endswith("_au"):
        return "AU"
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
