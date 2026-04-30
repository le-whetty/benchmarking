"""
Orchestrator: runs all (or selected) source scrapers in parallel,
deduplicates by id, writes listings.json + rejected.json + a timestamped snapshot.

Usage:
    python -m scraper.run                        # all sources
    python -m scraper.run --source seek_nz       # single source
    python -m scraper.run --source seek_nz,seek_au
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List

from scraper.schema import Listing

logger = logging.getLogger(__name__)

DATA_DIR = Path("data")
HISTORY_DIR = DATA_DIR / "listings_history"
LISTINGS_FILE = DATA_DIR / "listings.json"
REJECTED_FILE = DATA_DIR / "rejected.json"

ALL_SOURCES = [
    "seek_nz",
    "seek_au",
    "linkedin",
    "wellfound",
    "hatch",
    "working_in_tech",
    "vc_boards",
    "hiring_cafe",
]


def _load_source_module(name: str):
    if name == "seek_nz":
        from scraper.sources import seek_nz
        return seek_nz
    if name == "seek_au":
        from scraper.sources import seek_au
        return seek_au
    if name == "linkedin":
        from scraper.sources import linkedin
        return linkedin
    if name == "wellfound":
        from scraper.sources import wellfound
        return wellfound
    if name == "hatch":
        from scraper.sources import hatch
        return hatch
    if name == "working_in_tech":
        from scraper.sources import working_in_tech
        return working_in_tech
    if name == "vc_boards":
        from scraper.sources import vc_boards
        return vc_boards
    if name == "hiring_cafe":
        from scraper.sources import hiring_cafe
        return hiring_cafe
    raise ValueError(f"Unknown source: {name!r}. Available: {ALL_SOURCES}")


async def _run_source(name: str, rejected_log: List[Dict]) -> List[Listing]:
    mod = _load_source_module(name)
    try:
        return await mod.scrape(rejected_log)
    except Exception as exc:
        logger.error("[%s] Fatal error: %s", name, exc, exc_info=True)
        return []


async def main(sources: List[str]) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    HISTORY_DIR.mkdir(exist_ok=True)

    rejected_log: List[Dict] = []

    logger.info("Running sources: %s", sources)
    tasks = [_run_source(s, rejected_log) for s in sources]
    results = await asyncio.gather(*tasks)

    # Flatten and deduplicate
    seen_ids: set = set()
    all_listings: List[Listing] = []
    for batch in results:
        for listing in batch:
            if listing.id not in seen_ids:
                seen_ids.add(listing.id)
                all_listings.append(listing)

    all_listings.sort(key=lambda x: (x.country, x.seniority, x.company))

    # Serialise
    payload = [l.model_dump(mode="json") for l in all_listings]
    LISTINGS_FILE.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")

    # Snapshot
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    snapshot = HISTORY_DIR / f"listings_{ts}.json"
    snapshot.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")

    # Rejected log
    REJECTED_FILE.write_text(json.dumps(rejected_log, indent=2), encoding="utf-8")

    logger.info(
        "Done. %d listings saved to %s | %d rejected → %s | snapshot: %s",
        len(all_listings), LISTINGS_FILE,
        len(rejected_log), REJECTED_FILE,
        snapshot,
    )
    print(
        f"\n✓ {len(all_listings)} listings | {len(rejected_log)} rejected\n"
        f"  Output: {LISTINGS_FILE}\n"
        f"  Snapshot: {snapshot}"
    )

    # Auto-run regional analysis after every scrape
    try:
        from scraper.analysis.regional import analyse, ANALYSIS_FILE
        logger.info("Running regional analysis…")
        result = analyse()
        est = result.get("nz_estimate", {})
        if not est.get("insufficient_data"):
            print(
                f"\n  NZ estimate (ratio method): "
                f"NZ${est['estimated_p25_nzd']:,} – NZ${est['estimated_p75_nzd']:,} "
                f"(median NZ${est['estimated_median_nzd']:,})"
            )
        print(f"  Analysis: {ANALYSIS_FILE}")
    except Exception as exc:
        logger.warning("Analysis step failed (non-fatal): %s", exc)


def cli() -> None:
    parser = argparse.ArgumentParser(description="GTM Ops salary benchmark scraper")
    parser.add_argument(
        "--source", "-s",
        default=",".join(ALL_SOURCES),
        help=f"Comma-separated source names. Available: {', '.join(ALL_SOURCES)}",
    )
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )

    sources = [s.strip() for s in args.source.split(",") if s.strip()]
    unknown = [s for s in sources if s not in ALL_SOURCES]
    if unknown:
        logger.error("Unknown source(s): %s", unknown)
        sys.exit(1)

    asyncio.run(main(sources))


if __name__ == "__main__":
    cli()
