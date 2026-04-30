.PHONY: all scrape analyse web install install-playwright seed help \
        scrape-nz scrape-au scrape-linkedin scrape-wellfound scrape-hatch \
        scrape-hiring-cafe scrape-vc scrape-startup scrape-all venv

# ── defaults ──────────────────────────────────────────────────────────────────
# Default excludes LinkedIn and Wellfound (both need Playwright).
# hiring_cafe needs Playwright but is the primary global benchmark source.
SOURCE ?= seek_nz,seek_au,hatch,vc_boards,hiring_cafe
VENV   := .venv
PYTHON := $(VENV)/bin/python3
PIP    := $(VENV)/bin/pip

# ── venv setup ────────────────────────────────────────────────────────────────

$(VENV)/bin/activate:
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip

venv: $(VENV)/bin/activate

# Install Python dependencies into the venv
install: venv
	$(PIP) install -r scraper/requirements.txt
	@echo "✓ Python dependencies installed in $(VENV)"

# Install Playwright browsers (run once after install)
install-playwright: install
	$(PIP) install playwright
	$(VENV)/bin/playwright install chromium
	@echo "✓ Playwright + Chromium installed"

# ── top-level targets ─────────────────────────────────────────────────────────

all: scrape web
	@echo "Done. Open http://localhost:5173 in your browser."

# Run scraper (analysis runs automatically inside scraper.run), then copy outputs
scrape: $(VENV)/bin/activate
	@echo "▶ Scraping sources: $(SOURCE)"
	$(PYTHON) -m scraper.run --source $(SOURCE)
	@cp data/listings.json web/public/data/listings.json
	@echo "✓ Listings copied to web/public/data/listings.json"
	@if [ -f data/analysis.json ]; then \
		cp data/analysis.json web/public/data/analysis.json; \
		echo "✓ Analysis copied to web/public/data/analysis.json"; \
	fi

# Run analysis only (re-reads existing listings.json — no re-scraping)
analyse: $(VENV)/bin/activate
	@echo "▶ Running regional analysis…"
	$(PYTHON) -m scraper.analysis.regional
	@cp data/analysis.json web/public/data/analysis.json
	@echo "✓ Analysis copied to web/public/data/analysis.json"

# Just copy the seed data (no scraping) — useful for first-run demo
seed:
	@cp data/seed_listings.json data/listings.json
	@cp data/listings.json web/public/data/listings.json
	@echo "✓ Seed data loaded into web/public/data/listings.json"

# Start the React dev server
web:
	@cd web && npm run dev

# ── per-source shortcuts ──────────────────────────────────────────────────────

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

scrape-hiring-cafe:
	$(MAKE) scrape SOURCE=hiring_cafe

scrape-working-in-tech:
	$(MAKE) scrape SOURCE=working_in_tech

scrape-vc:
	$(MAKE) scrape SOURCE=vc_boards

# Startup/tech-focused sources only (no Seek, which skews enterprise)
scrape-startup:
	$(MAKE) scrape SOURCE=linkedin,wellfound,hatch,vc_boards,hiring_cafe

# Everything
scrape-all:
	$(MAKE) scrape SOURCE=seek_nz,seek_au,linkedin,wellfound,hatch,vc_boards,hiring_cafe

# ── utilities ─────────────────────────────────────────────────────────────────

# Show rejected listings
rejected:
	@$(PYTHON) -c "import json,sys; data=json.load(open('data/rejected.json')); [print(f\"{r['source']:12} {r['reason']:35} {r.get('title','')[:60]}\") for r in data]"

help:
	@echo ""
	@echo "  make install              — create venv + install Python deps (run once)"
	@echo "  make seed                 — load seed data, no scraping needed"
	@echo "  make web                  — start React dev server at localhost:5173"
	@echo "  make scrape               — scrape default sources (no Playwright needed)"
	@echo "  make scrape-all           — scrape everything incl. LinkedIn + Wellfound"
	@echo "  make scrape SOURCE=seek_nz,hatch,vc_boards"
	@echo "  make all                  — scrape then start web server"
	@echo ""
	@echo "  Per-source shortcuts:"
	@echo "    make scrape-nz"
	@echo "    make scrape-au"
	@echo "    make scrape-hatch"
	@echo "    make scrape-hiring-cafe   Global benchmark source (needs Playwright)"
	@echo "    make scrape-vc            Blackbird + AirTree"
	@echo "    make scrape-startup       All startup/tech sources (no Seek)"
	@echo "    make scrape-linkedin      (needs Playwright)"
	@echo "    make scrape-wellfound     (needs Playwright)"
	@echo ""
	@echo "  make install-playwright   — install Playwright + Chromium (needed for hiring_cafe)"
	@echo "  make analyse              — rerun analysis on existing listings (no re-scraping)"
	@echo "  make rejected             — print rejected listings with reasons"
	@echo ""
