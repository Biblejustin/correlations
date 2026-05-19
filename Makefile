# Reproducibility Makefile for the correlations project.
#
# Usage:
#   make           — full rebuild (catalogs + all plots)
#   make plots     — regenerate plots only (don't refetch catalogs)
#   make catalogs  — rebuild SQLite catalogs only
#   make correlations — run only this repo's analyses
#   make clean     — delete generated figures

VENV    := .venv
PY      := $(abspath $(VENV)/bin/python)
PIP     := $(abspath $(VENV)/bin/pip)

SOURCE_REPOS := famines-tracking pandemics-tracking volcanic-eruptions \
                tropical-cyclones droughts-tracking astronomical-signs

CORR_SCRIPTS := analyze lag_test cycle_fold spectral wars famines israel \
                flares_quakes floods pandemics volcanoes cyclones astronomy \
                meta_analysis trends_meta pattern_analysis signs_overlay \
                contractions_analysis periodogram_extended sensitivity \
                wavelet chains make_figures make_more_figures

.PHONY: all venv catalogs plots correlations clean

all: venv catalogs plots correlations
	@echo "==> Full rebuild done."

$(VENV):
	python3 -m venv $(VENV)
	$(PIP) install -q -r requirements.txt

venv: $(VENV)

catalogs: venv
	@echo "==> Building source catalogs (SQLite DBs)"
	cd ../spaceweather && $(PY) fetch_spaceweather.py
	cd ../earthquakes && $(PY) fetch_quakes.py
	cd ../earthquakes && $(PY) fetch_quakes.py --start-year 1900 --min-mag 6.0 --db quakes_1900.sqlite

plots: venv
	@echo "==> Regenerating per-repo plots"
	@for repo in $(SOURCE_REPOS); do \
	    if [ -d ../$$repo ]; then \
	        echo "    $$repo"; \
	        (cd ../$$repo && $(PY) make_plots.py > /dev/null 2>&1) || echo "      (skipped)"; \
	    fi; \
	done
	@if [ -d ../flood-data ]; then \
	    echo "    flood-data"; \
	    (cd ../flood-data && $(PY) build_plots.py > /dev/null 2>&1) || true; \
	fi

correlations: venv
	@echo "==> Running correlations analyses"
	@for script in $(CORR_SCRIPTS); do \
	    if [ -f $$script.py ]; then \
	        echo "    $$script.py"; \
	        $(PY) $$script.py > /dev/null 2>&1 || echo "      (failed — check $$script.py)"; \
	    fi; \
	done

clean:
	rm -rf figures/*.png

# Convenience: just rerun if a script changed
%.py.run: %.py
	$(PY) $<
