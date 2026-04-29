.PHONY: all scrape web install install-playwright seed help \
        scrape-nz scrape-au scrape-linkedin scrape-wellfound scrape-hatch \
        scrape-working-in-tech scrape-vc scrape-startup scrape-all

# ── defaults ─────────────────────────────────────────────────────────────────
SOURCE ?= seek_nz,seek_au,linkedin,wellfound,hatch,working_in_tech,vc_boards
PYTHON  ?= python3

# ── top-level targets ─────────────────────────────────────────────────────────

all: scrape web
	@echo "Done. Open http://localhost:5173 in your browser."

# Run scraper then copy output to web public dir
scrape:
	@echo "▶ Scraping sources: $(SOURCE)"
	$(PYTHON) -m scraper.run --source $(SOURCE)
	@cp data/listings.json web/public/data/listings.json
	@echo "✓ Listings copied to web/public/data/listings.json"

# Just copy the seed data (no scraping) — useful for first-run demo
seed:
	@cp data/seed_listings.json data/listings.json
	@cp data/listings.json web/public/data/listings.json
	@echo "✓ Seed data loaded into web/public/data/listings.json"

# Start the React dev server
web:
	@cd web && npm run dev

# Install Python dependencies
install:
	pip install -r scraper/requirements.txt

# Install Playwright browsers (run once after pip install)
install-playwright:
	playwright install chromium

# ── convenience targets ───────────────────────────────────────────────────────

scrape-nz:
	$(MAKE) scrape SOURCE=seek_nz

scrape-au:
	$(MAKE) scrape SOURCE=seek_au

scrape-linkedin:
	$(MAKE) scrape SOURCE=linkedin

scrape-wellfound:
	$(MAKE) scrape SOURCE=wellfound

scrape-hatch:
	$(MAKE) scrape SOURCE=hatch

scrape-working-in-tech:
	$(MAKE) scrape SOURCE=working_in_tech

scrape-vc:
	$(MAKE) scrape SOURCE=vc_boards

# Startup/tech-focused sources only (no Seek, which skews enterprise)
scrape-startup:
	$(MAKE) scrape SOURCE=linkedin,wellfound,hatch,working_in_tech,vc_boards

# Show rejected listings
rejected:
	@$(PYTHON) -c "import json,sys; data=json.load(open('data/rejected.json')); \
	  [print(f\"{r['source']:12} {r['reason']:35} {r.get('title','')[:60]}\") for r in data]"

help:
	@echo ""
	@echo "  make all                  — scrape all sources, then start web server"
	@echo "  make seed                 — load seed data (no scraping needed)"
	@echo "  make web                  — start React dev server only"
	@echo "  make scrape               — scrape all sources"
	@echo "  make scrape SOURCE=seek_nz,hatch,vc_boards"
	@echo ""
	@echo "  Per-source shortcuts:"
	@echo "    make scrape-nz            Seek NZ"
	@echo "    make scrape-au            Seek AU"
	@echo "    make scrape-linkedin      LinkedIn (needs Playwright)"
	@echo "    make scrape-wellfound     Wellfound/AngelList (needs Playwright)"
	@echo "    make scrape-hatch         Hatch NZ startup board"
	@echo "    make scrape-working-in-tech  Working In Tech NZ"
	@echo "    make scrape-vc            Blackbird + AirTree + Icehouse boards"
	@echo "    make scrape-startup       All startup/tech sources (no Seek)"
	@echo ""
	@echo "  make install              pip install scraper dependencies"
	@echo "  make install-playwright   download Chromium for Playwright"
	@echo "  make rejected             print rejected listing reasons"
	@echo ""
