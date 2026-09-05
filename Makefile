# Operational entrypoints. Source queries and stage order live in weekly_update.py.
# Run `make bootstrap` once, then `make test` or `make local`.
.DEFAULT_GOAL := all
PYTHON ?= python3.13
VENV ?= .venv
PY ?= $(abspath $(VENV)/bin/python)
WORKERS ?= 2
SOURCES ?=

.PHONY: all bootstrap venv verify-env test refresh local plots catalogs correlations publish

bootstrap venv:
	"$(PYTHON)" -m venv "$(VENV)"
	"$(PY)" -m pip install -r requirements-dev.txt
	"$(PY)" verify_environment.py --requirements requirements-dev.txt

verify-env:
	"$(PY)" verify_environment.py --requirements requirements-dev.txt

test: verify-env
	MPLBACKEND=Agg "$(PY)" -m pytest -q tests

all: refresh

refresh: verify-env
	"$(PY)" weekly_update.py --dry-run --workers "$(WORKERS)"

local plots: verify-env
	"$(PY)" weekly_update.py --skip-fetch --dry-run --workers "$(WORKERS)"

catalogs: verify-env
	"$(PY)" weekly_update.py --fetch-only --dry-run $(if $(strip $(SOURCES)),--sources $(SOURCES),)

correlations: verify-env
	"$(PY)" run_suite.py --workers "$(WORKERS)"

publish: verify-env
	"$(PY)" weekly_update.py --publish --workers "$(WORKERS)"
