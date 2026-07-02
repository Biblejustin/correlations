"""
Post-process raw canonical downloads into working catalog CSVs, with guards.

refresh_canonical_data.sh downloads raw files with a _ prefix; this script
turns them into the catalogs the analyses read:

  data/_owid_terrorist_attacks.csv + data/_owid_terrorism_deaths.csv
      -> data/terrorism.csv          (year, events, deaths; World aggregate)
  data/_ucdp_prio_v25_1.zip
      -> data/ucdp_prio_conflicts.csv

Every replacement goes through fetch_guard.safe_replace, so a bad upstream
response can't overwrite a good catalog.
"""
import argparse
import sys
import zipfile
from pathlib import Path

import pandas as pd

from fetch_guard import guard_or_exit


def process_owid_terrorism(data: Path) -> None:
    att_p = data / "_owid_terrorist_attacks.csv"
    dth_p = data / "_owid_terrorism_deaths.csv"
    if not (att_p.exists() and dth_p.exists()):
        print("  terrorism: raw OWID files not present, skipping")
        return
    att = pd.read_csv(att_p)
    dth = pd.read_csv(dth_p)
    att_w = att[att["Code"] == "OWID_WRL"][["Year", "Attacks"]].rename(
        columns={"Year": "year", "Attacks": "events"})
    dth_w = dth[dth["Code"] == "OWID_WRL"][["Year", "Fatalities"]].rename(
        columns={"Year": "year", "Fatalities": "deaths"})
    m = att_w.merge(dth_w, on="year", how="outer").sort_values("year")
    m["events"] = m["events"].fillna(0).astype(int)
    m["deaths"] = m["deaths"].fillna(0).astype(int)
    tmp = data / "_terrorism.tmp.csv"
    m.to_csv(tmp, index=False)
    guard_or_exit(tmp, data / "terrorism.csv",
                    required_cols=["year", "events", "deaths"])
    att_p.unlink()
    dth_p.unlink()


def process_ucdp(data: Path) -> None:
    zips = sorted(data.glob("_ucdp_prio_*.zip"))
    if not zips:
        print("  ucdp: raw zip not present, skipping")
        return
    zp = zips[-1]
    with zipfile.ZipFile(zp) as z:
        csvs = [n for n in z.namelist() if n.lower().endswith(".csv")]
        if not csvs:
            print(f"  GUARD REFUSED: {zp.name} contains no CSV", file=sys.stderr)
            sys.exit(1)
        tmp = data / "_ucdp.tmp.csv"
        tmp.write_bytes(z.read(csvs[0]))
    guard_or_exit(tmp, data / "ucdp_prio_conflicts.csv",
                    required_cols=["conflict_id", "year", "type_of_conflict",
                                     "intensity_level"])
    zp.unlink()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data-dir", default="data")
    args = ap.parse_args()
    data = Path(args.data_dir)
    process_owid_terrorism(data)
    process_ucdp(data)
    # Tidy remaining scratch files from the download step
    for p in data.glob("_swpc_*.json"):
        p.unlink()


if __name__ == "__main__":
    main()
