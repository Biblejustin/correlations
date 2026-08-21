#!/bin/bash
# Single entry point for the data refresh across all 10 sibling repos.
#
#   bash weekly_update.sh              # fetch → analyze → figures → commit → push
#   bash weekly_update.sh --dry-run    # everything except commit/push
#   bash weekly_update.sh --skip-fetch # only re-run analyses + figures
#
# Designed to be the ONE path for updates: run it by hand, or point the
# scheduled job at it, and both do identical work. Repos with no real data
# change are left untouched (figure-only byte churn is reverted, not
# committed). Expects the sibling-directory layout and keeps a shared venv
# at ../venv (created on first run from correlations/requirements.txt,
# which is version-pinned so figures render identically across machines).
set -u

export MPLBACKEND="${MPLBACKEND:-Agg}"   # headless-safe (VPS has no display)

DRY_RUN=0
SKIP_FETCH=0
for arg in "$@"; do
    case $arg in
        --dry-run) DRY_RUN=1 ;;
        --skip-fetch) SKIP_FETCH=1 ;;
    esac
done

HERE="$(cd "$(dirname "$0")" && pwd)"   # .../correlations
ROOT="$(dirname "$HERE")"
REPOS=(correlations earthquakes spaceweather famines-tracking flood-data
       pandemics-tracking volcanic-eruptions tropical-cyclones
       droughts-tracking astronomical-signs israel-pressure-disasters
       israel-rain-agriculture)

echo "==> Workspace: $ROOT"

# ---- venv (shared, pinned) ----
PY="$ROOT/venv/bin/python"
if [ ! -x "$PY" ]; then
    echo "==> Creating shared venv"
    python3 -m venv "$ROOT/venv"
    "$ROOT/venv/bin/pip" install -q -U pip
    "$ROOT/venv/bin/pip" install -q -r "$HERE/requirements.txt" \
        jupyter nbconvert ipykernel
fi

# ---- pull all repos so we build on the latest data commits ----
# Regenerable artifacts (figures/plots/notebooks) left dirty by an earlier
# run (e.g. a --dry-run) would make pull fail, so drop that churn first.
# data/ and code are never auto-reverted here.
echo "==> Pulling all repos"
for r in "${REPOS[@]}"; do
    if [ -d "$ROOT/$r" ]; then
        for spec in figures plots ':(glob)*.ipynb'; do
            git -C "$ROOT/$r" checkout -q -- "$spec" 2>/dev/null
        done
        git -C "$ROOT/$r" pull --ff-only -q || echo "    ! $r pull failed (diverged?)"
    else
        git -C "$ROOT" clone -q "git@github.com:Biblejustin/$r.git"
    fi
done

# ---- fetch ----
if [ $SKIP_FETCH -eq 0 ]; then
    echo "==> Fetching space weather (SILSO + GFZ)"
    (cd "$ROOT/spaceweather" && "$PY" fetch_spaceweather.py | tail -2)

    echo "==> Fetching USGS M>=4 modern (resumable; fast after first seed)"
    (cd "$ROOT/earthquakes" && "$PY" fetch_quakes.py --sleep 0.3 | tail -2)

    echo "==> Fetching USGS M>=6.5 since 1900"
    (cd "$ROOT/earthquakes" && "$PY" fetch_quakes.py --start-year 1900 \
        --min-mag 6.5 --db quakes_1900.sqlite --sleep 0.5 | tail -2)

    echo "==> Fetching NGDC significant quakes (live, into sqlite)"
    (cd "$ROOT/earthquakes" && "$PY" fetch_significant.py | tail -3)

    echo "==> Fetching NGDC catalogs (CSV, guarded)"
    (cd "$HERE" && "$PY" fetch_ngdc.py | tail -3)

    echo "==> Fetching OWID / UCDP / SWPC (guarded)"
    (cd "$HERE" && PYTHON="$PY" bash refresh_canonical_data.sh | tail -4)

    echo "==> Israel-pressure disaster correlation (guarded fetch + test + figure)"
    (cd "$ROOT/israel-pressure-disasters" && bash update.sh | tail -4)

    echo "==> Israel rain + agriculture (guarded fetch + trends + figures)"
    (cd "$ROOT/israel-rain-agriculture" && bash update.sh | tail -4)
fi

# ---- delta report + change flags (before analyses, so we can skip work) ----
echo "==> Delta report"
FLAGS="$ROOT/.refresh_flags"
(cd "$HERE" && "$PY" refresh_report.py --flags-file "$FLAGS" | tee "$ROOT/.refresh_report.txt")
# shellcheck disable=SC1090
source "$FLAGS"
echo "    flags: ANY_CHANGE=$ANY_CHANGE EQ_CHANGED=$EQ_CHANGED SW_CHANGED=$SW_CHANGED"

# ---- analyses + figures ----
echo "==> Sister-repo plots"
for r in famines-tracking pandemics-tracking volcanic-eruptions \
         tropical-cyclones droughts-tracking astronomical-signs; do
    (cd "$ROOT/$r" && "$PY" make_plots.py > /dev/null 2>&1) \
        && echo "    $r OK" || echo "    $r FAIL"
done
(cd "$ROOT/flood-data" && "$PY" build_plots.py > /dev/null 2>&1) \
    && echo "    flood-data OK" || echo "    flood-data FAIL"

echo "==> Notebooks"
for pair in "earthquakes earthquakes.ipynb" "spaceweather spaceweather.ipynb"; do
    set -- $pair
    (cd "$ROOT/$1" && "$PY" -m jupyter nbconvert --to notebook --execute "$2" \
        --output "$2" > /dev/null 2>&1) \
        && echo "    $1 OK" || echo "    $1 FAIL"
done

echo "==> Correlations analyses"
PASS=0; FAILED=0; SKIPPED=0
for script in analyze lag_test cycle_fold spectral wars famines israel \
              flares_quakes floods pandemics volcanoes cyclones astronomy \
              meta_analysis trends_meta pattern_analysis signs_overlay \
              contractions_analysis periodogram_extended sensitivity \
              wavelet chains wars_split granger regional regional_quakes \
              ucdp_compare canonical_compare dashboard; do
    [ -f "$HERE/$script.py" ] || continue
    OUTPUT=$(cd "$HERE" && "$PY" "$script.py" 2>&1)
    if [ $? -ne 0 ]; then
        FAILED=$((FAILED+1)); echo "    FAIL: $script — $(echo "$OUTPUT" | tail -1)"
    elif echo "$OUTPUT" | grep -q "^SKIPPED"; then
        SKIPPED=$((SKIPPED+1)); echo "    skip: $script"
    else
        PASS=$((PASS+1))
    fi
done
echo "    $PASS passed, $SKIPPED skipped, $FAILED failed"

# ---- predictions scorecard (only log an entry when data moved) ----
if [ "$ANY_CHANGE" = "1" ]; then
    echo "==> Predictions scorecard"
    (cd "$HERE" && "$PY" predictions_scorecard.py | tail -14)
else
    echo "==> Predictions scorecard (dry run — no data change)"
    (cd "$HERE" && "$PY" predictions_scorecard.py --dry-run > /dev/null 2>&1)
fi

# ---- commit + push, but only where data actually changed ----
# Both helpers touch ONLY generated artifacts + data files. Code or doc
# edits sitting uncommitted in a repo are never staged and never reverted
# by this script.
ARTIFACTS=(figures plots data ':(glob)*.ipynb' PREDICTIONS_LOG.md results.txt results)

commit_repo () {  # $1 repo dir, $2 subject, $3 body-file (optional)
    local r="$1"
    if [ -z "$(git -C "$ROOT/$r" status --porcelain)" ]; then
        echo "    $r: clean"
        return
    fi
    if [ $DRY_RUN -eq 1 ]; then
        echo "    $r: changes present (dry run, not committing)"
        return
    fi
    for spec in "${ARTIFACTS[@]}"; do
        git -C "$ROOT/$r" add "$spec" 2>/dev/null
    done
    if git -C "$ROOT/$r" diff --cached --quiet; then
        echo "    $r: nothing staged (only non-artifact edits present, left alone)"
        return
    fi
    if [ -n "${3:-}" ] && [ -f "${3:-}" ]; then
        git -C "$ROOT/$r" -c commit.gpgsign=false commit -q -m "$2" -m "$(cat "$3")"
    else
        git -C "$ROOT/$r" -c commit.gpgsign=false commit -q -m "$2"
    fi
    git -C "$ROOT/$r" push -q && echo "    $r: committed + pushed"
    LEFT=$(git -C "$ROOT/$r" status --porcelain | head -3)
    [ -n "$LEFT" ] && echo "    $r: NOTE — uncommitted non-artifact edits remain"
}

revert_repo () {
    for spec in "${ARTIFACTS[@]}"; do
        git -C "$ROOT/$1" checkout -q -- "$spec" 2>/dev/null
    done
    echo "    $1: no data change — reverted figure churn"
}

TODAY=$(date +%Y-%m-%d)
echo "==> Commit phase"

if [ "$EQ_CHANGED" = "1" ]; then
    commit_repo earthquakes "Update data through $TODAY"
else
    revert_repo earthquakes
fi

if [ "$SW_CHANGED" = "1" ]; then
    commit_repo spaceweather "Update data through $TODAY"
else
    revert_repo spaceweather
fi

# Hand-curated sisters: commit only when a non-plot file changed
# (israel-rain-agriculture belongs here because its data/ CSVs only change
# when an upstream release actually moves; figure-only churn is reverted)
for r in famines-tracking flood-data pandemics-tracking volcanic-eruptions \
         tropical-cyclones droughts-tracking astronomical-signs \
         israel-pressure-disasters israel-rain-agriculture; do
    NONPLOT=$(git -C "$ROOT/$r" status --porcelain | grep -vE "(plots/|figures/|\.ipynb)" || true)
    if [ -n "$NONPLOT" ]; then
        commit_repo "$r" "Update data through $TODAY"
    else
        revert_repo "$r"
    fi
done

if [ "$ANY_CHANGE" = "1" ]; then
    commit_repo correlations "Update data through $TODAY" "$ROOT/.refresh_report.txt"
else
    revert_repo correlations
fi

echo "==> Done."
