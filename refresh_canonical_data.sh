#!/bin/bash
# Refresh canonical source CSVs via Webshare proxy.
# Sources that update: OWID (yearly), UCDP/PRIO (yearly), NGDC (irregular), NOAA SWPC (continuous).
# Skipped: COW v4 (frozen at 2003), hand-curated CSVs.
set -e

if [[ -z "$WEBSHARE_PROXY_USERNAME" || -z "$WEBSHARE_PROXY_PASSWORD" ]]; then
  echo "ERROR: Set WEBSHARE_PROXY_USERNAME / WEBSHARE_PROXY_PASSWORD (source ~/.zshrc)" >&2
  exit 1
fi

PROXY="http://${WEBSHARE_PROXY_USERNAME}:${WEBSHARE_PROXY_PASSWORD}@p.webshare.io:80"
UA="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"
mkdir -p data

fetch() {
  local url="$1" out="$2" label="$3"
  echo "Fetching $label..."
  if curl -sS --proxy "$PROXY" -A "$UA" --max-time 60 -o "$out.tmp" "$url"; then
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

# OWID — terrorism (GTD aggregate)
fetch "https://ourworldindata.org/grapher/terrorist-attacks.csv" "data/_owid_terrorist_attacks.csv" "OWID terrorist attacks"
fetch "https://ourworldindata.org/grapher/terrorism-deaths.csv" "data/_owid_terrorism_deaths.csv" "OWID terrorism deaths"

# UCDP/PRIO — Armed Conflict Dataset (latest version)
fetch "https://ucdp.uu.se/downloads/ucdpprioacd/UcdpPrioConflict_v24_1.csv" \
      "data/_ucdp_prio_v24_1.csv" "UCDP/PRIO v24.1"

# NGDC significant earthquakes — paginated full export
fetch "https://www.ngdc.noaa.gov/hazel/hazard-service/api/v1/earthquakes?_format=csv&minMagnitude=4&maxYear=2026&maxResults=10000" \
      "data/_ngdc_earthquakes_raw.csv" "NGDC earthquakes (page 1)"

# NGDC volcanic events
fetch "https://www.ngdc.noaa.gov/hazel/hazard-service/api/v1/volcanoes/events?_format=csv&maxYear=2026&maxResults=10000" \
      "data/_ngdc_volcanic_events_raw.csv" "NGDC volcanic events"

# NOAA SWPC X-ray flares — daily summary archive
fetch "https://services.swpc.noaa.gov/json/goes/primary/xray-flares-7-day.json" \
      "data/_swpc_xray_7day.json" "NOAA SWPC X-ray flares (recent)"

echo "Done — see *.tmp/_*.csv files. Run merge_canonical_refresh.py to update working CSVs."
