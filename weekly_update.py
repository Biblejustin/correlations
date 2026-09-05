"""Refresh → synchronize → validate → analyze. Publish only explicit, clean successful runs."""
from __future__ import annotations
import argparse
import datetime as dt
import json
from pathlib import Path
import subprocess
import sys

from run_suite import BASE,run_step,run_suite
ROOT=BASE.parent
REPOS=('correlations earthquakes spaceweather famines-tracking flood-data pandemics-tracking '
       'volcanic-eruptions tropical-cyclones droughts-tracking astronomical-signs '
       'israel-pressure-disasters israel-rain-agriculture').split()


def git(repo,*args):
    return subprocess.check_output(['git','-C',str(ROOT/repo),*args],text=True).strip()


def verify_publish_targets():
    account=json.loads(subprocess.check_output(['gh','api','user'],text=True))
    if account['login']!='Biblejustin':raise RuntimeError('GitHub active account must be Biblejustin')
    for repo in REPOS:
        remote=git(repo,'remote','get-url','origin')
        if remote.removesuffix('.git') not in {f'https://github.com/Biblejustin/{repo}',f'git@github.com:Biblejustin/{repo}'}:
            raise RuntimeError(f'Unexpected remote for {repo}: {remote}')
        verify_push_urls(repo)
        if git(repo,'status','--porcelain'):
            raise RuntimeError(f'{repo} has existing changes; publication needs clean starting trees')
    return account


def verify_push_urls(repo):
    urls=git(repo,'remote','get-url','--push','--all','origin').splitlines()
    expected={f'https://github.com/Biblejustin/{repo}',f'git@github.com:Biblejustin/{repo}'}
    if not urls or any(url.removesuffix('.git') not in expected for url in urls):
        raise RuntimeError(f'Every push target must be Biblejustin/{repo}')


def generated_path(path):
    p=Path(path)
    return (p.parts[0] in {'data','figures','plots','results'} or
            path in {'results.txt','PREDICTIONS_LOG.md'} or
            (len(p.parts)==1 and path.endswith('.coverage.json')))


def publish(account):
    current=json.loads(subprocess.check_output(['gh','api','user'],text=True))
    if current['login']!='Biblejustin' or current['id']!=account['id']:
        raise RuntimeError('GitHub active account changed; publication stopped')
    for repo in REPOS:
        # Revalidate target immediately before any commit/push.
        remote=git(repo,'remote','get-url','origin').removesuffix('.git')
        if remote not in {f'https://github.com/Biblejustin/{repo}',f'git@github.com:Biblejustin/{repo}'}:
            raise RuntimeError('Target owner must be Biblejustin')
        verify_push_urls(repo)
        branch=git(repo,'symbolic-ref','--short','HEAD')
        changed=subprocess.check_output(['git','-C',str(ROOT/repo),'ls-files','--modified','--others','--exclude-standard','-z']).decode().split('\0')
        paths=sorted({p for p in changed if p and generated_path(p)})
        if not paths:continue
        subprocess.run(['git','-C',str(ROOT/repo),'add','--',*paths],check=True)
        if subprocess.run(['git','-C',str(ROOT/repo),'diff','--cached','--quiet']).returncode==0:continue
        subprocess.run(['git','-C',str(ROOT/repo),'-c','user.name=Biblejustin',
                        '-c',f'user.email={account["id"]}+Biblejustin@users.noreply.github.com',
                        '-c','commit.gpgsign=false','commit','-m',f'Refresh validated data through {dt.date.today()}'],check=True)
        subprocess.run(['git','-C',str(ROOT/repo),'-c','credential.helper=',
                        '-c','credential.helper=!gh auth git-credential','push',
                        f'https://github.com/Biblejustin/{repo}.git',f'HEAD:refs/heads/{branch}'],check=True)


def fetch_steps(py=None):
    py = py or sys.executable
    return [
        ('fetch_spaceweather','spaceweather',[py,'fetch_spaceweather.py']),
        ('fetch_quakes','earthquakes',[py,'fetch_quakes.py','--sleep','.3']),
        ('fetch_historical_quakes','earthquakes',[py,'fetch_quakes.py','--start-year','1900','--min-mag','6.5','--db','quakes_1900.sqlite','--sleep','.5']),
        ('fetch_significant','earthquakes',[py,'fetch_significant.py']),
        ('fetch_ngdc','correlations',[py,'fetch_ngdc.py']),
        ('fetch_canonical','correlations',['env',f'PYTHON={py}','bash','refresh_canonical_data.sh']),
        ('fetch_monitoring','correlations',[py,'refresh_monitoring.py']),
        ('fetch_israel_pressure','israel-pressure-disasters',['env',f'PYTHON={py}','bash','update.sh']),
        ('fetch_israel_rain','israel-rain-agriculture',['env',f'PYTHON={py}','bash','update.sh']),
    ]


def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--skip-fetch',action='store_true')
    ap.add_argument('--dry-run',action='store_true',help='Update local data/figures; no commits or pushes')
    ap.add_argument('--publish',action='store_true',help='Commit/push generated artifacts after every stage passes')
    ap.add_argument('--workers',type=int,default=2)
    ap.add_argument('--fetch-only',action='store_true',help='Fetch sources only; no analysis or publication')
    ap.add_argument('--sources',nargs='+',choices=[x[0].removeprefix('fetch_') for x in fetch_steps()],help='Select fetch stages for diagnostics; requires --fetch-only')
    args=ap.parse_args(argv)
    if args.dry_run and args.publish:ap.error('--dry-run and --publish are mutually exclusive')
    if args.workers<1:ap.error('--workers must be positive')
    if args.fetch_only and (args.skip_fetch or args.publish):ap.error('--fetch-only cannot skip fetches or publish')
    if args.sources and not args.fetch_only:ap.error('--sources requires --fetch-only')
    missing=[r for r in REPOS if not (ROOT/r).is_dir()]
    if missing:ap.error('Missing sibling repos: '+', '.join(missing))
    account=verify_publish_targets() if args.publish else None
    results=[]
    def step(name,cmd,repo='correlations'):
        result=run_step(name,cmd,cwd=ROOT/repo);results.append(result)
        if result['status']!='passed':
            finish(False)
            raise SystemExit(f'{name} failed; local evidence retained; publication stopped. See {result["log"]}')
    def finish(success):
        out=BASE/'results'/('fetch_run.json' if args.fetch_only else 'refresh_run.json');out.parent.mkdir(exist_ok=True)
        out.write_text(json.dumps({'generated_at':dt.datetime.now(dt.timezone.utc).isoformat(),
                                  'success':success,'fetch_skipped':args.skip_fetch,'fetch_only':args.fetch_only,
                                  'selected_sources':args.sources,'stages':results},indent=2)+'\n')
    py=sys.executable
    # Fail fast on code/test defects before spending network requests or mutating source snapshots.
    step('regression_tests',[py,'-m','pytest','-q','tests'])
    if not args.skip_fetch:
        for name,repo,command in fetch_steps(py):
            if args.sources and name.removeprefix('fetch_') not in args.sources:continue
            step(name,command,repo)
    if args.fetch_only:
        finish(True)
        print('Selected fetch stages passed; analytical validation/publication not attempted.')
        return
    step('sync_feeders',[py,'sync_feeders.py'])
    for repo in REPOS:
        if repo=='correlations':continue
        script='build_plots.py' if repo=='flood-data' else 'make_plots.py'
        if (ROOT/repo/script).exists():step(repo+'_plots',[py,script],repo)
    analyses=run_suite(workers=args.workers);results.extend(analyses)
    if any(r['status']!='passed' for r in analyses):
        finish(False);raise SystemExit('Analysis failure/unavailable input; publication stopped. See logs and results/analysis_run.json.')
    step('predictions_scorecard',[py,'predictions_scorecard.py']+(['--dry-run'] if args.dry_run else []))
    # Advance successful-source snapshot only after every analysis passed.
    step('refresh_report',[py,'refresh_report.py']+(['--dry-run'] if args.dry_run else []))
    finish(True)
    if args.publish:
        try:publish(account)
        except Exception:
            finish(False)
            raise
    print('Refresh complete. '+('Generated artifacts published.' if args.publish else 'Local outputs ready for review.'))

if __name__=='__main__':main()
