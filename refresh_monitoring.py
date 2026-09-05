"""Fetch selected public regional feeds; failed feeds keep their last good snapshot."""
import argparse
import json
from pathlib import Path

from monitoring.feeds import ADAPTERS, refresh, BASE


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--sources',nargs='+',choices=list(ADAPTERS),default=list(ADAPTERS))
    ap.add_argument('--offline',action='store_true')
    ap.add_argument('--output',type=Path,default=BASE/'data/monitoring')
    args=ap.parse_args();failures=[]
    for name in args.sources:
        try:
            r=refresh(name,args.output,args.offline)
            print(f'{name}: {r["rows"]} observations; through {r["observed_through"]}',flush=True)
        except Exception as exc:
            failures.append({'source':name,'error':str(exc)})
            print(f'{name}: FAILED — {exc}; previous snapshot retained',flush=True)
    if failures:
        (BASE/'logs').mkdir(exist_ok=True)
        (BASE/'logs/monitoring_errors.json').write_text(json.dumps(failures,indent=2)+'\n')
        raise SystemExit(1)


if __name__=='__main__':main()
