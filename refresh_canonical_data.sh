#!/bin/bash
# Refresh canonical source CSVs.
#
# Most sources we use (OWID grapher, UCDP, NGDC, NOAA SWPC) work direct from a
# US IP without bot-blocking. The Webshare proxy is currently EXHAUSTED — the
# paid quota was burned through during the 2026-05-19 canonical-data run. The
# script no longer uses it by default. To re-enable proxy mode (e.g. after a
# top-up, or if running from an IP that gets bot-blocked), set USE_PROXY=1.
#
# Sources that update: OWID (annual), UCDP/PRIO (annual), NGDC (irregular),
# NOAA SWPC (continuous). Skipped: COW v4 (frozen at 2003), hand-curated CSVs.
set -e

mkdir -p data
UA="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"

# Optional proxy support. Off by default; turn on with USE_PROXY=1.
PROXY_ARGS=()
if [[ "${USE_PROXY:-0}" == "1" ]]; then
  if [[ -z "$WEBSHARE_PROXY_USERNAME" || -z "$WEBSHARE_PROXY_PASSWORD" ]]; then
    echo "USE_PROXY=1 but creds missing. Set WEBSHARE_PROXY_USERNAME / WEBSHARE_PROXY_PASSWORD (source ~/.zshrc)." >&2
    exit 1
  fi
  PROXY="http://${WEBSHARE_PROXY_USERNAME}:${WEBSHARE_PROXY_PASSWORD}@p.webshare.io:80"
  PROXY_ARGS=(--proxy "$PROXY")
  echo "Using Webshare proxy"
else
  echo "Direct mode (no proxy). Set USE_PROXY=1 to route through Webshare."
fi

fetch() {
  local url="$1" out="$2" label="$3"
  echo "Fetching $label..."
  if curl -sS "${PROXY_ARGS[@]}" -A "$UA" --max-time 60 -o "$out.tmp" "$url"; then
    local sz=$(wc -c < "$out.tmp")
    if [[ $sz -gt 100 ]]; then
      mv "$out.tmp" "$out"
      echo "  OK $out ($sz bytes)"
    else
      echo "  WARN $out empty/tiny ($sz bytes) — keeping previous"
      rm -f "$out.tmp"
    fi
  else
    echo "  FAIL $url"
    rm -f "$out.tmp"
  fi
}

# OWID — terrorism (GTD aggregate). Yields _owid_*.csv files that need post-processing
# into data/terrorism.csv (see ad-hoc snippet in commit history or rerun fetch_ngdc-style merge).
fetch "https://ourworldindata.org/grapher/terrorist-attacks.csv" "data/_owid_terrorist_attacks.csv" "OWID terrorist attacks"
fetch "https://ourworldindata.org/grapher/terrorism-deaths.csv" "data/_owid_terrorism_deaths.csv" "OWID terrorism deaths"

# UCDP/PRIO — Armed Conflict Dataset. Bumped to v25.1 (2024 data) 2026-05-20.
fetch "https://ucdp.uu.se/downloads/ucdpprio/ucdp-prio-acd-251-csv.zip" \
      "data/_ucdp_prio_v25_1.zip" "UCDP/PRIO v25.1 (zip)"

# NGDC significant earthquakes + volcanoes — these require pagination (200 items/page max).
# Use fetch_ngdc.py instead of curl here.
echo "For NGDC catalogs run: python fetch_ngdc.py"

# NOAA SWPC X-ray flares — recent activity (last 7 days). For historical X1+ archive,
# use flares_xclass.csv (hand-curated; SWPC historical data is sparse pre-2000).
fetch "https://services.swpc.noaa.gov/json/goes/primary/xray-flares-7-day.json" \
      "data/_swpc_xray_7day.json" "NOAA SWPC X-ray flares (recent)"

echo ""
echo "Done — fetched _* prefix files. Post-processing notes:"
echo "  - OWID: merge attacks+deaths on year + Code=OWID_WRL → data/terrorism.csv"
echo "  - UCDP: unzip data/_ucdp_prio_v25_1.zip → data/ucdp_prio_conflicts.csv"
echo "  - NGDC: run 'python fetch_ngdc.py' separately (paginated)"
