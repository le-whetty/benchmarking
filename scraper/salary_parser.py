"""
Parse salary strings into (min, max, currency, includes_super, ote_min, ote_max).
Handles most ANZ job board formats defensively.
"""
from __future__ import annotations

import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

# ── currency detection ────────────────────────────────────────────────────────

_CURRENCY_HINTS = {
    "NZD": re.compile(r"NZ\$|NZD", re.I),
    "AUD": re.compile(r"AU\$|AUD|A\$", re.I),
    "USD": re.compile(r"US\$|USD|\bUSD\b", re.I),
    "GBP": re.compile(r"£|GBP|\bGBP\b", re.I),
}

_GENERIC_DOLLAR = re.compile(r"\$")


def detect_currency(text: str, country: str = "NZ") -> str:
    for currency, pattern in _CURRENCY_HINTS.items():
        if pattern.search(text):
            return currency
    # Fall back to country default
    if country == "AU":
        return "AUD"
    if country == "US":
        return "USD"
    if country == "UK":
        return "GBP"
    return "NZD"


# ── number normalisation ──────────────────────────────────────────────────────

def _parse_number(s: str) -> Optional[float]:
    """Turn '180k', '180,000', '180000' into a float."""
    s = s.strip().replace(",", "").replace(" ", "")
    try:
        if s.lower().endswith("k"):
            return float(s[:-1]) * 1_000
        if s.lower().endswith("m"):
            return float(s[:-1]) * 1_000_000
        return float(s)
    except ValueError:
        return None


# ── main extraction patterns ──────────────────────────────────────────────────

# Matches patterns like:
#   $180k–$220k  |  £80k–£120k  |  $180,000 - $220,000  |  180k-220k
_RANGE_PATTERN = re.compile(
    r"(?:NZ\$|AU\$|A\$|US\$|£|\$)?\s*"
    r"([\d,]+(?:\.\d+)?[kKmM]?)"
    r"\s*[-–—to]+\s*"
    r"(?:NZ\$|AU\$|A\$|US\$|£|\$)?\s*"
    r"([\d,]+(?:\.\d+)?[kKmM]?)",
    re.I,
)

# Single value: "$180k" or "£120k"
_SINGLE_PATTERN = re.compile(
    r"(?:NZ\$|AU\$|A\$|US\$|£|\$)\s*([\d,]+(?:\.\d+)?[kKmM]?)",
    re.I,
)

_SUPER_PATTERN = re.compile(r"\+\s*super(?:annuation)?", re.I)
_OTE_PATTERN = re.compile(r"OTE|on[\s\-]target[\s\-]earn", re.I)

# Phrases meaning "no salary disclosed"
_NO_SALARY_PHRASES = re.compile(
    r"\b(competitive|market rate|negotiable|doe|tbd|upon request|attractive)\b",
    re.I,
)

SALARY_MIN_NZD = 50_000
SALARY_MAX_NZD = 1_000_000
AUD_TO_NZD = 1.09


GBP_TO_NZD = 2.10

def _to_nzd(value: float, currency: str) -> float:
    if currency == "AUD":
        return value * AUD_TO_NZD
    if currency == "USD":
        return value * 1.65
    if currency == "GBP":
        return value * GBP_TO_NZD
    return value


class ParsedSalary:
    __slots__ = (
        "salary_min", "salary_max", "currency",
        "includes_super", "ote_min", "ote_max",
        "rejected", "rejection_reason",
    )

    def __init__(self) -> None:
        self.salary_min: Optional[float] = None
        self.salary_max: Optional[float] = None
        self.currency: str = "NZD"
        self.includes_super: Optional[bool] = None
        self.ote_min: Optional[float] = None
        self.ote_max: Optional[float] = None
        self.rejected: bool = False
        self.rejection_reason: Optional[str] = None


def parse_salary(text: str, country: str = "NZ") -> ParsedSalary:
    result = ParsedSalary()

    if not text or _NO_SALARY_PHRASES.search(text):
        return result  # all fields None — excluded from charts

    currency = detect_currency(text, country)
    result.currency = currency

    includes_super = bool(_SUPER_PATTERN.search(text))
    result.includes_super = includes_super if country == "AU" else None

    # Split on OTE markers to keep base and OTE separate
    ote_part: Optional[str] = None
    base_text = text
    if _OTE_PATTERN.search(text):
        # everything after "OTE" is the OTE figure; everything before is base
        ote_split = re.split(r"OTE|on[\s\-]target[\s\-]earn", text, flags=re.I)
        base_text = ote_split[0]
        ote_part = ote_split[1] if len(ote_split) > 1 else None

    # Parse base range
    range_match = _RANGE_PATTERN.search(base_text)
    if range_match:
        lo = _parse_number(range_match.group(1))
        hi = _parse_number(range_match.group(2))
        if lo and hi:
            result.salary_min = lo
            result.salary_max = hi
    else:
        single_match = _SINGLE_PATTERN.search(base_text)
        if single_match:
            val = _parse_number(single_match.group(1))
            if val:
                result.salary_min = val
                result.salary_max = val

    # Parse OTE if present
    if ote_part:
        ote_range = _RANGE_PATTERN.search(ote_part)
        if ote_range:
            result.ote_min = _parse_number(ote_range.group(1))
            result.ote_max = _parse_number(ote_range.group(2))
        else:
            ote_single = _SINGLE_PATTERN.search(ote_part)
            if ote_single:
                v = _parse_number(ote_single.group(1))
                result.ote_min = v
                result.ote_max = v

    # Sanity check: reject outliers (convert to NZD for comparison)
    if result.salary_min is not None:
        min_nzd = _to_nzd(result.salary_min, currency)
        max_nzd = _to_nzd(result.salary_max or result.salary_min, currency)
        if min_nzd < SALARY_MIN_NZD or max_nzd > SALARY_MAX_NZD:
            logger.warning(
                "Salary outlier (%.0f–%.0f %s) in: %s",
                result.salary_min, result.salary_max or 0, currency, text[:80],
            )
            result.rejected = True
            result.rejection_reason = (
                f"Outlier: {result.salary_min}–{result.salary_max} {currency}"
            )
            result.salary_min = None
            result.salary_max = None

    return result
