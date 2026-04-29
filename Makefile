.PHONY: all scrape web install install-playwright seed help

# ── defaults ─────────────────────────────────────────────────────────────────
SOURCE ?= seek_nz,seek_au,linkedin
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

# Show rejected listings
rejected:
	@$(PYTHON) -c "import json,sys; data=json.load(open('data/rejected.json')); \
	  [print(f\"{r['source']:12} {r['reason']:35} {r.get('title','')[:60]}\") for r in data]"

help:
	@echo ""
	@echo "  make all              — scrape all sources, then start web server"
	@echo "  make seed             — load seed data (no scraping needed)"
	@echo "  make web              — start React dev server only"
	@echo "  make scrape           — scrape all sources (or SOURCE=seek_nz)"
	@echo "  make scrape SOURCE=seek_nz,seek_au"
	@echo "  make install          — pip install scraper dependencies"
	@echo "  make install-playwright — download Chromium for Playwright"
	@echo "  make rejected         — print rejected listing reasons"
	@echo ""
