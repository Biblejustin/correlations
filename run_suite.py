"""Run analyses with retained logs; unavailable/failed stages cannot publish stale figures."""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor
import datetime as dt
import json
import os
from pathlib import Path
import subprocess
import sys
import time

BASE=Path(__file__).resolve().parent
SCRIPTS=('analyze lag_test cycle_fold spectral wars famines israel flares_quakes floods '
         'pandemics volcanoes cyclones astronomy meta_analysis trends_meta pattern_analysis '
         'signs_overlay contractions_analysis periodogram_extended sensitivity wavelet chains '
         'wars_split granger regional regional_quakes ucdp_compare canonical_compare monitor_regional make_figures make_more_figures').split()


def run_step(name,command,cwd=BASE,log_dir=None,timeout=1800):
    log_dir=Path(log_dir or BASE/'logs');log_dir.mkdir(parents=True,exist_ok=True)
    path=log_dir/(name+'.log');start=time.monotonic()
    env=dict(os.environ,MPLBACKEND='Agg',PYTHONUNBUFFERED='1')
    code=1
    with path.open('w') as output:
        try:
            result=subprocess.run(command,cwd=cwd,env=env,stdout=output,stderr=subprocess.STDOUT,
                                  timeout=timeout,check=False)
            code=result.returncode
        except (OSError,subprocess.TimeoutExpired) as error:
            output.write('\n'+str(error)+'\n')
    content=path.read_text(errors='replace')
    status='failed' if code else ('unavailable' if any(line.startswith('SKIPPED:') for line in content.splitlines()) else 'passed')
    row=dict(stage=name,status=status,returncode=code,seconds=round(time.monotonic()-start,2),log=str(path))
    print(f'{name}: {status} ({row["seconds"]}s)',flush=True)
    return row


def run_suite(scripts=None,workers=2,log_dir=None):
    names=list(scripts or SCRIPTS)
    unknown=set(names)-set(SCRIPTS)
    if unknown:raise ValueError(f'Unknown analyses: {sorted(unknown)}')
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results=list(pool.map(lambda name:run_step(name,[sys.executable,str(BASE/(name+'.py'))],log_dir=log_dir),names))
    # Dashboard depends on all current constituent figures. Never rebuild it after a failure.
    if scripts is None and all(r['status']=='passed' for r in results):
        results.append(run_step('dashboard',[sys.executable,str(BASE/'dashboard.py')],log_dir=log_dir))
    output=BASE/'results/analysis_run.json';output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps({'generated_at':dt.datetime.now(dt.timezone.utc).isoformat(),
                                 'python':sys.version,'stages':results},indent=2)+'\n')
    return results


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--scripts',nargs='+',choices=SCRIPTS)
    ap.add_argument('--workers',type=int,default=2)
    args=ap.parse_args()
    if args.workers<1:ap.error('--workers must be positive')
    rows=run_suite(args.scripts,args.workers)
    raise SystemExit(0 if all(r['status']=='passed' for r in rows) else 1)

if __name__=='__main__':main()
