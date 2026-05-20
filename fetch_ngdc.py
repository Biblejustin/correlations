"""Fetch NGDC (NOAA NCEI) Significant Earthquakes and Volcanic Events catalogs.

NGDC's hazel hazard-service API returns paginated JSON. This script pages through
all events and writes to a CSV matching the existing column layout.
"""
import argparse
import csv
import sys
import time
from pathlib import Path

import requests

EARTHQUAKE_URL = "https://www.ngdc.noaa.gov/hazel/hazard-service/api/v1/earthquakes"
VOLCANO_EVENTS_URL = "https://www.ngdc.noaa.gov/hazel/hazard-service/api/v1/volcanoes"


def fetch_all(url: str, params: dict | None = None, page_size: int = 200) -> list[dict]:
    """Paginate through NGDC API and collect all items."""
    params = dict(params or {})
    params["page"] = 1
    params["itemsPerPage"] = page_size
    all_items: list[dict] = []
    while True:
        r = requests.get(url, params=params, timeout=60,
                          headers={"User-Agent": "correlations-data-refresh/1.0"})
        r.raise_for_status()
        data = r.json()
        items = data.get("items") or []
        all_items.extend(items)
        total = data.get("totalItems") or len(all_items)
        sys.stdout.write(f"  page {params['page']}: +{len(items)} (total so far {len(all_items)} / {total})\n")
        sys.stdout.flush()
        if len(all_items) >= total or not items:
            break
        params["page"] += 1
        time.sleep(0.5)
    return all_items


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data-dir", default="data")
    ap.add_argument("--max-year", type=int, default=2026)
    args = ap.parse_args()
    out = Path(args.data_dir); out.mkdir(parents=True, exist_ok=True)

    print(f"Fetching NGDC significant earthquakes (maxYear={args.max_year})...")
    quakes = fetch_all(EARTHQUAKE_URL, {"maxYear": args.max_year})
    if quakes:
        # Union of all keys so we don't drop columns
        keys: list[str] = []
        seen = set()
        for q in quakes:
            for k in q.keys():
                if k not in seen:
                    keys.append(k); seen.add(k)
        out_path = out / "noaa_significant_earthquakes.csv"
        with open(out_path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=keys)
            w.writeheader()
            for q in quakes:
                w.writerow(q)
        print(f"Wrote {out_path}: {len(quakes)} rows, {len(keys)} columns")

    print(f"\nFetching NGDC volcanic events (maxYear={args.max_year})...")
    volcs = fetch_all(VOLCANO_EVENTS_URL, {"maxYear": args.max_year})
    if volcs:
        keys = []
        seen = set()
        for v in volcs:
            for k in v.keys():
                if k not in seen:
                    keys.append(k); seen.add(k)
        out_path = out / "noaa_volcanic_events.csv"
        with open(out_path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=keys)
            w.writeheader()
            for v in volcs:
                w.writerow(v)
        print(f"Wrote {out_path}: {len(volcs)} rows, {len(keys)} columns")


if __name__ == "__main__":
    main()
