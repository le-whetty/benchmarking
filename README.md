# GTM Ops Salary Benchmark

A local tool for benchmarking ANZ Head-of/Director/VP Revenue Operations compensation. Scrapes live job listings with disclosed salaries, normalises them, and visualises the dataset.

## Quick start

```bash
# 1. Install Python dependencies
make install

# 2. Install Playwright browser (needed for LinkedIn)
make install-playwright

# 3. Load seed data and start the app (no scraping needed)
make seed
make web
# → open http://localhost:5173
```

To run a real scrape first:
```bash
make all          # scrape all sources, then start web server
```

## Structure

```
/scraper
  /sources/         one file per source
    seek_nz.py
    seek_au.py
    linkedin.py
  schema.py         Pydantic canonical schema
  salary_parser.py  parse & normalise salary strings
  normaliser.py     title classification, scope signal extraction
  run.py            orchestrator (parallel sources)
  requirements.txt
  companies.json    known ANZ companies with public careers pages

/web                React + Vite + TypeScript app
  /src
    App.tsx
    /components
      Header.tsx
      FilterBar.tsx
      DistributionChart.tsx
      ListingsTable.tsx
    /lib
      types.ts       canonical TypeScript types
      filters.ts     filter + normalise logic
      useListings.ts data fetching hook
  /public/data/
    listings.json   ← the app reads this file

/data
  listings.json          live dataset (written by scraper, copied to web/public/data/)
  seed_listings.json     25 manually verified entries for demo
  rejected.json          listings skipped with reason
  listings_history/      timestamped snapshots
```

## Makefile commands

| Command | What it does |
|---|---|
| `make seed` | Load seed data (no scraping) |
| `make web` | Start React dev server at localhost:5173 |
| `make scrape` | Run all scrapers |
| `make scrape SOURCE=seek_nz` | Run one scraper |
| `make scrape SOURCE=seek_nz,seek_au` | Run multiple scrapers |
| `make all` | Scrape then start web server |
| `make rejected` | Print rejected listings with reasons |
| `make install` | pip install scraper dependencies |
| `make install-playwright` | Download Chromium for Playwright |

## Sources

| Source | ID | Notes |
|---|---|---|
| Seek NZ | `seek_nz` | seek.co.nz, HTML scraping |
| Seek AU | `seek_au` | seek.com.au, HTML scraping |
| LinkedIn | `linkedin` | Public search via Playwright |

## Adding a new source

1. Create `scraper/sources/your_source.py`
2. Implement `async def scrape(rejected_log: List[Dict]) -> List[Listing]`
3. Add the source name to `ALL_SOURCES` in `scraper/run.py`
4. Add to the Makefile's `SOURCE` default if desired

Minimum a source must do:
- Fetch listings matching the title taxonomy
- Run each title through `normaliser.classify_title()`
- Parse salary strings with `salary_parser.parse_salary()`
- Return `List[Listing]` using the canonical schema

## Canonical schema

See `scraper/schema.py`. Key fields:

| Field | Type | Notes |
|---|---|---|
| `salary_min/max` | float | Base salary, local currency |
| `salary_currency` | NZD/AUD/USD | Detected from listing context |
| `salary_includes_super` | bool/null | AU-specific, 11.5% super flagged but NOT added to base |
| `seniority` | enum | manager → senior_manager → head → director → vp |
| `title_match_confidence` | 0–1 | How well the title matches our taxonomy |
| `scope_signals` | list | manages_team, ai_remit, cross_functional, etc. |

## FX rates

Hardcoded in `web/src/lib/types.ts` and `scraper/salary_parser.py`:

```typescript
export const AUD_TO_NZD = 1.09;
export const USD_TO_NZD = 1.65;
```

Update these periodically. The "Normalise to NZD" toggle in the app applies them.

## Rejected listings

`data/rejected.json` logs every skipped listing with a reason:
- `title_excluded_or_unmatched` — title didn't match taxonomy / was an IC role
- `low_confidence_0.XX` — confidence below threshold
- `Outlier: …` — salary outside NZD 50k–1M sanity range

Run `make rejected` to print a summary.
