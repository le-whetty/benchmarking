"""
Regional salary analysis — reads data/listings.json, outputs data/analysis.json.

Two outputs:
1. Regional stats (p25/median/p75) per country, in both local currency and NZD.
2. NZ benchmark estimate using the cross-market ratio method:
   - Compute RevOps/SWE salary ratio in each market that has data (US, UK, AU)
   - Average those ratios
   - Apply to the NZ SWE anchor salary from data/benchmarks.json

Run standalone: python -m scraper.analysis.regional
"""
from __future__ import annotations

import json
import logging
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

DATA_DIR = Path("data")
LISTINGS_FILE = DATA_DIR / "listings.json"
BENCHMARKS_FILE = DATA_DIR / "benchmarks.json"
ANALYSIS_FILE = DATA_DIR / "analysis.json"

# FX → NZD (keep in sync with schema.py / salary_parser.py)
FX_TO_NZD: Dict[str, float] = {
    "NZD": 1.0,
    "AUD": 1.09,
    "USD": 1.65,
    "GBP": 2.10,
}

DEFAULT_BENCHMARKS = {
    "note": "Anchors from Tracksuit Function Frameworks (Mar 2026). SWE Altitude 3 (Senior) as mid-market anchor.",
    "nz_anchors": {
        "software_engineer_mid": 145000,
        "product_manager_mid": 120000,
    },
    "market_swe_benchmarks": {
        "US": {"value": 155000, "currency": "USD", "note": "Mid-level SWE base, US market consensus"},
        "UK": {"value": 80000,  "currency": "GBP", "note": "Mid-level SWE base, UK market consensus"},
        "AU": {"value": 170000, "currency": "AUD", "note": "Tracksuit Alt 3 Senior Engineer midpoint"},
    },
}


def _to_nzd(value: float, currency: str) -> float:
    return value * FX_TO_NZD.get(currency, 1.0)


def _percentile(sorted_vals: List[float], p: float) -> float:
    if not sorted_vals:
        return 0.0
    n = len(sorted_vals)
    idx = (n - 1) * p / 100
    lo, frac = int(idx), idx % 1
    if lo + 1 >= n:
        return sorted_vals[lo]
    return sorted_vals[lo] * (1 - frac) + sorted_vals[lo + 1] * frac


def _salary_midpoint(listing: Dict) -> Optional[float]:
    lo = listing.get("salary_min")
    hi = listing.get("salary_max")
    if lo and hi:
        return (lo + hi) / 2
    return lo or hi or None


def _compute_stats(values_nzd: List[float], values_local: List[float]) -> Dict[str, Any]:
    if not values_nzd:
        return {"n": 0}
    sv_nzd = sorted(values_nzd)
    sv_loc = sorted(values_local)
    return {
        "n": len(sv_nzd),
        "p25_nzd":    round(_percentile(sv_nzd, 25)),
        "median_nzd": round(_percentile(sv_nzd, 50)),
        "p75_nzd":    round(_percentile(sv_nzd, 75)),
        "mean_nzd":   round(statistics.mean(sv_nzd)),
        "p25_local":    round(_percentile(sv_loc, 25)),
        "median_local": round(_percentile(sv_loc, 50)),
        "p75_local":    round(_percentile(sv_loc, 75)),
    }


def analyse(
    listings_path: Path = LISTINGS_FILE,
    benchmarks_path: Path = BENCHMARKS_FILE,
    output_path: Path = ANALYSIS_FILE,
) -> Dict[str, Any]:
    # Load listings
    if not listings_path.exists():
        raise FileNotFoundError(f"{listings_path} not found — run `make scrape` first")
    listings: List[Dict] = json.loads(listings_path.read_text(encoding="utf-8"))
    logger.info("Loaded %d listings from %s", len(listings), listings_path)

    # Load or create benchmarks
    if benchmarks_path.exists():
        benchmarks = json.loads(benchmarks_path.read_text(encoding="utf-8"))
    else:
        benchmarks = DEFAULT_BENCHMARKS
        benchmarks_path.write_text(json.dumps(DEFAULT_BENCHMARKS, indent=2), encoding="utf-8")
        logger.info("Created default benchmarks at %s — edit to use Tracksuit's actual pay bands", benchmarks_path)

    # ── 1. Regional stats ─────────────────────────────────────────────────────

    # Group listings with salary data by country
    by_country: Dict[str, Dict[str, Any]] = {}
    currency_map: Dict[str, str] = {}  # country → dominant currency

    for listing in listings:
        country = listing.get("country", "")
        mid = _salary_midpoint(listing)
        if not mid or not country or country in ("ANZ", "REMOTE"):
            continue

        currency = listing.get("salary_currency", "NZD")
        currency_map[country] = currency  # last one wins (fine for homogeneous countries)

        if country not in by_country:
            by_country[country] = {"local": [], "nzd": [], "by_seniority": {}}

        by_country[country]["local"].append(mid)
        by_country[country]["nzd"].append(_to_nzd(mid, currency))

        seniority = listing.get("seniority", "")
        if seniority:
            if seniority not in by_country[country]["by_seniority"]:
                by_country[country]["by_seniority"][seniority] = {"local": [], "nzd": []}
            by_country[country]["by_seniority"][seniority]["local"].append(mid)
            by_country[country]["by_seniority"][seniority]["nzd"].append(_to_nzd(mid, currency))

    regional: Dict[str, Any] = {}
    for country, data in by_country.items():
        stats = _compute_stats(data["nzd"], data["local"])
        stats["currency"] = currency_map.get(country, "NZD")
        stats["by_seniority"] = {}
        for sen, sen_data in data["by_seniority"].items():
            sen_stats = _compute_stats(sen_data["nzd"], sen_data["local"])
            if sen_stats.get("n", 0) > 0:
                stats["by_seniority"][sen] = sen_stats
        regional[country] = stats
        logger.info("  %s: n=%d, median=NZ$%s", country, stats.get("n", 0),
                    f"{stats.get('median_nzd', 0):,.0f}")

    # ── 2. NZ benchmark estimate (ratio method) ───────────────────────────────

    swe_benchmarks = benchmarks.get("market_swe_benchmarks", DEFAULT_BENCHMARKS["market_swe_benchmarks"])
    nz_swe_anchor = (benchmarks.get("nz_anchors", {}).get("software_engineer_mid")
                     or DEFAULT_BENCHMARKS["nz_anchors"]["software_engineer_mid"])
    nz_pm_anchor = (benchmarks.get("nz_anchors", {}).get("product_manager_mid")
                    or DEFAULT_BENCHMARKS["nz_anchors"]["product_manager_mid"])

    ratios: Dict[str, float] = {}
    for market, bench in swe_benchmarks.items():
        if market not in regional:
            continue
        market_median_revops_nzd = regional[market].get("median_nzd", 0)
        if not market_median_revops_nzd:
            continue
        swe_nzd = _to_nzd(bench["value"], bench["currency"])
        if swe_nzd:
            ratio = market_median_revops_nzd / swe_nzd
            ratios[market] = round(ratio, 3)
            logger.info("  %s RevOps/SWE ratio: %.2f  (RevOps NZ$%s / SWE NZ$%s)",
                        market, ratio,
                        f"{market_median_revops_nzd:,.0f}",
                        f"{swe_nzd:,.0f}")

    nz_estimate: Dict[str, Any] = {"insufficient_data": True}
    if ratios:
        avg_ratio = statistics.mean(ratios.values())
        estimated_median = round(nz_swe_anchor * avg_ratio / 5000) * 5000  # round to nearest $5k
        estimated_p25 = round(estimated_median * 0.80 / 5000) * 5000
        estimated_p75 = round(estimated_median * 1.25 / 5000) * 5000

        nz_estimate = {
            "insufficient_data": False,
            "method": "cross_market_swe_ratio",
            "nz_swe_anchor_nzd": nz_swe_anchor,
            "nz_pm_anchor_nzd": nz_pm_anchor,
            "market_ratios": ratios,
            "avg_ratio": round(avg_ratio, 3),
            "estimated_p25_nzd": estimated_p25,
            "estimated_median_nzd": estimated_median,
            "estimated_p75_nzd": estimated_p75,
            "caveats": [
                f"Based on {sum(regional[m]['n'] for m in ratios)} listings across "
                f"{', '.join(ratios.keys())}",
                "FX conversion uses approximate spot rates — update in data/benchmarks.json",
                "NZ SWE anchor is configurable — edit data/benchmarks.json with Tracksuit's actual bands",
                "Ratio method assumes RevOps ≈ SWE scarcity premium holds across markets",
            ],
        }
        logger.info("NZ estimate: NZ$%s–NZ$%s (median NZ$%s, ratio %.2f×)",
                    f"{estimated_p25:,.0f}", f"{estimated_p75:,.0f}",
                    f"{estimated_median:,.0f}", avg_ratio)

    # ── 3. Top companies ──────────────────────────────────────────────────────

    company_data: Dict[str, Dict] = {}
    for listing in listings:
        co = listing.get("company") or "Unknown"
        if co == "Unknown":
            continue
        country = listing.get("country", "")
        mid = _salary_midpoint(listing)
        if co not in company_data:
            company_data[co] = {"country": country, "salaries": [], "roles": []}
        if mid:
            company_data[co]["salaries"].append(
                _to_nzd(mid, listing.get("salary_currency", "NZD"))
            )
        company_data[co]["roles"].append(listing.get("title", ""))

    top_companies = []
    for co, data in company_data.items():
        if not data["salaries"]:
            continue
        top_companies.append({
            "company": co,
            "country": data["country"],
            "n_roles": len(data["roles"]),
            "median_nzd": round(statistics.median(data["salaries"])),
        })
    top_companies.sort(key=lambda x: x["median_nzd"], reverse=True)

    # ── Assemble output ───────────────────────────────────────────────────────

    total_with_salary = sum(
        1 for l in listings
        if l.get("salary_min") or l.get("salary_max")
    )

    result = {
        "generated_at": datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total_listings": len(listings),
        "listings_with_salary": total_with_salary,
        "fx_rates_used": FX_TO_NZD,
        "regional": regional,
        "nz_estimate": nz_estimate,
        "top_companies_by_salary": top_companies[:20],
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    logger.info("Analysis written to %s", output_path)
    return result


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        result = analyse()
        print(f"\n✓ Analysis complete → {ANALYSIS_FILE}")
        print(f"  {result['total_listings']} listings total, "
              f"{result['listings_with_salary']} with salary data")
        if not result["nz_estimate"].get("insufficient_data"):
            est = result["nz_estimate"]
            print(f"\nNZ estimate (ratio method):")
            print(f"  p25:    NZ${est['estimated_p25_nzd']:,}")
            print(f"  median: NZ${est['estimated_median_nzd']:,}")
            print(f"  p75:    NZ${est['estimated_p75_nzd']:,}")
            print(f"  ratio:  {est['avg_ratio']:.2f}× NZ SWE anchor")
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
