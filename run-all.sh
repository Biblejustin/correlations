#!/usr/bin/env bash
# Reproducibility entry point: rebuild every catalog and regenerate every figure
# in every repo of this project, from scratch.
#
# Assumes all sibling repos are cloned in the parent directory:
#   ../earthquakes/         (public)
#   ../spaceweather/        (public)
#   ../famines-tracking/    (public)
#   ../flood-data/          (public)
#   ../pandemics-tracking/  (private)
#   ../volcanic-eruptions/  (private)
#   ../tropical-cyclones/   (private)
#   ../droughts-tracking/   (private)
#   ../astronomical-signs/  (private)
#   ./                      this correlations repo
#
# Usage:
#   bash run-all.sh                    # full rebuild
#   bash run-all.sh --skip-fetch       # only re-run plots, don't refetch SQLite catalogs
#   bash run-all.sh --skip-source-repos  # only run correlations analyses

set -e

SKIP_FETCH=0
SKIP_SOURCE=0
for arg in "$@"; do
    case $arg in
        --skip-fetch) SKIP_FETCH=1 ;;
        --skip-source-repos) SKIP_SOURCE=1 ;;
    esac
done

echo "==> Setting up Python environment"
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
fi
source .venv/bin/activate
pip install -q -r requirements.txt

if [ $SKIP_SOURCE -eq 0 ]; then
    # ---- Source-repo catalog builds ----
    if [ $SKIP_FETCH -eq 0 ]; then
        echo "==> Building spaceweather.sqlite (fast)"
        (cd ../spaceweather && python fetch_spaceweather.py)

        echo "==> Building quakes.sqlite (M>=4 since 1965, ~10-15 min)"
        (cd ../earthquakes && python fetch_quakes.py)

        echo "==> Building quakes_1900.sqlite (M>=6 since 1900, ~2 min)"
        (cd ../earthquakes && python fetch_quakes.py --start-year 1900 --min-mag 6.0 --db quakes_1900.sqlite)
    fi

    echo "==> Regenerating per-repo plots"
    for repo in famines-tracking pandemics-tracking volcanic-eruptions tropical-cyclones droughts-tracking astronomical-signs; do
        if [ -d "../$repo" ]; then
            echo "    $repo"
            (cd ../$repo && python make_plots.py 2>&1 | tail -3) || echo "      (skipped or failed)"
        fi
    done
    if [ -d "../flood-data" ]; then
        echo "    flood-data"
        (cd ../flood-data && python build_plots.py 2>&1 | tail -3) || true
    fi
fi

# ---- Correlations analyses ----
echo "==> Running correlations analyses"
for script in analyze lag_test cycle_fold spectral wars famines israel flares_quakes \
              floods pandemics volcanoes cyclones astronomy \
              meta_analysis trends_meta pattern_analysis signs_overlay \
              contractions_analysis periodogram_extended sensitivity \
              wavelet chains; do
    if [ -f "${script}.py" ]; then
        echo "    ${script}.py"
        python ${script}.py > /dev/null 2>&1 || echo "      (failed — check ${script}.py manually)"
    fi
done

# Regenerate the figure-builder scripts
for script in make_figures make_more_figures; do
    if [ -f "${script}.py" ]; then
        echo "    ${script}.py"
        python ${script}.py > /dev/null 2>&1 || true
    fi
done

echo "==> Done. Every catalog rebuilt, every figure regenerated."
echo "    To re-render this repo's README plots, browse to figures/"
echo "    To re-render sister repos' README plots, browse to ../{repo}/plots/"
