from __future__ import annotations

import hashlib
from datetime import date
from typing import List, Literal, Optional

from pydantic import BaseModel, field_validator


SENIORITY = Literal["manager", "senior_manager", "head", "director", "vp"]
COUNTRY = Literal["NZ", "AU", "ANZ", "US", "UK", "REMOTE"]
CURRENCY = Literal["NZD", "AUD", "USD", "GBP"]

SALARY_MIN_NZD = 50_000
SALARY_MAX_NZD = 1_000_000

# Rough AUD→NZD conversion (hardcoded; update periodically)
AUD_TO_NZD = 1.09
USD_TO_NZD = 1.65


class Listing(BaseModel):
    id: str
    source: str                           # "seek_nz", "seek_au", "linkedin", etc.
    url: str
    title: str
    company: str
    company_size: Optional[Literal["startup", "scaleup", "enterprise"]] = None
    location: str                         # raw string from listing
    country: COUNTRY
    city: Optional[str] = None
    salary_min: Optional[float] = None   # base, local currency
    salary_max: Optional[float] = None
    salary_currency: CURRENCY = "NZD"
    salary_includes_super: Optional[bool] = None   # AU-specific
    ote_min: Optional[float] = None
    ote_max: Optional[float] = None
    seniority: SENIORITY
    title_match_confidence: float         # 0.0–1.0
    scope_signals: List[str] = []
    description_excerpt: str = ""        # first 500 chars of JD
    posted_date: Optional[date] = None
    scraped_date: date

    @field_validator("title_match_confidence")
    @classmethod
    def clamp_confidence(cls, v: float) -> float:
        return max(0.0, min(1.0, v))


def make_id(source: str, url: str) -> str:
    return hashlib.sha1(f"{source}:{url}".encode()).hexdigest()[:16]
