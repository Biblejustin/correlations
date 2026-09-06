"""Daily deterministic refresh: guarded FF-only update, publish, verify, record."""
from __future__ import annotations
import argparse
import contextlib
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import signal
import subprocess
import tempfile
from zoneinfo import ZoneInfo
from semantic_snapshot import snapshot, compare

REPOS = ('correlations earthquakes spaceweather famines-tracking flood-data pandemics-tracking '
         'volcanic-eruptions tropical-cyclones droughts-tracking astronomical-signs '
         'israel-pressure-disasters israel-rain-agriculture').split()
AUTH = ['-c', 'credential.helper=', '-c', 'credential.helper=!gh auth git-credential']
REQUIRED_GUARDS = {
    'correlations/requirements.txt', 'correlations/requirements-dev.txt', 'correlations/verify_environment.py',
    'correlations/monitoring/feeds.py', 'israel-rain-agriculture/monitor_climate.py',
    'correlations/monitoring/config.json', 'correlations/monitoring/extension_plan.json',
    'correlations/monitoring/trade_plan.json', 'astronomical-signs/.nvmrc',
    'astronomical-signs/eclipse_plan.json', 'astronomical-signs/source_pins.json',
    'israel-rain-agriculture/analysis_plan.json', 'israel-rain-agriculture/climate_extension_plan.json',
    'israel-rain-agriculture/results/irrigation_sensitivity_plan.json',
    'israel-rain-agriculture/results/prospective_wheat_model.json',
    'israel-rain-agriculture/data/rain_cckp_monthly.csv',
    'israel-rain-agriculture/data/rain_cckp_annual.csv',
}
REQUIRED_RUNNER_FILES = {'scheduled_refresh.py', 'semantic_snapshot.py', 'artifact_validation.py', 'monthly_release_review.py'}


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def normalize_error(value):
    value = re.sub(r'\d{4}-\d{2}-\d{2}(?:T[0-9:.+Z-]+)?', '<date>', str(value))
    value = re.sub(r'\d{8}T\d{6}\.\d+Z', '<run>', value)
    return re.sub(r'\b\d+(?:\.\d+)?s\b', '<duration>', value)


def attention(state, previous, record, reasons, *, recovered=False):
    fingerprint = hashlib.sha256(json.dumps(reasons, sort_keys=True).encode()).hexdigest() if reasons else None
    prior = previous.get('attention', {})
    record['action_required'] = bool(reasons)
    record['notification_needed'] = bool(recovered or (reasons and (not prior.get('active') or fingerprint != prior.get('fingerprint'))))
    state['attention'] = {'active': bool(reasons), 'fingerprint': fingerprint, 'reasons': reasons}


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(value, indent=2, sort_keys=True, allow_nan=False)+'\n').encode()
    fd, temporary = tempfile.mkstemp(prefix='.'+path.name, dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write(payload); handle.flush(); os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@contextlib.contextmanager
def lock(path):
    with Path(path).open('a') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


class Commands:
    def __init__(self, log, env, timeout):
        self.log, self.env, self.timeout = log, env, timeout

    def __call__(self, args, *, cwd=None):
        self.log.write('$ '+shlex.join(map(str, args))+'\n'); self.log.flush()
        process = subprocess.Popen(list(map(str, args)), cwd=cwd, env=self.env, text=True,
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            output, _ = process.communicate(timeout=self.timeout)
        except BaseException:
            # A timed-out make must not leave fetchers/pushers running after releasing our lock.
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                output, _ = process.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                output, _ = process.communicate()
            self.log.write(output or ''); self.log.flush()
            raise
        self.log.write(output); self.log.flush()
        if process.returncode:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            raise subprocess.CalledProcessError(process.returncode, args, output=output)
        return output.strip()


class Runner:
    def __init__(self, config, commands):
        self.config, self.command = config, commands
        self.workspace = Path(config['workspace']).resolve()

    def git(self, repo, *args):
        return self.command(['git', '-C', self.workspace/repo, *args])

    def account(self):
        account = json.loads(self.command(['gh', 'api', 'user']))
        if account.get('login') != 'Biblejustin' or not isinstance(account.get('id'), int):
            raise RuntimeError('GitHub active identity must be Biblejustin')
        return {'login': account['login'], 'id': account['id']}

    def local(self, repo):
        expected = {f'https://github.com/Biblejustin/{repo}', f'git@github.com:Biblejustin/{repo}'}
        if Path(self.git(repo, 'rev-parse', '--show-toplevel')).resolve() != self.workspace/repo:
            raise RuntimeError('Unexpected checkout root: '+repo)
        if self.git(repo, 'symbolic-ref', '--short', 'HEAD') != 'main':
            raise RuntimeError('Not on main: '+repo)
        if self.git(repo, 'status', '--porcelain', '--untracked-files=all'):
            raise RuntimeError('Dirty checkout; preserve local evidence: '+repo)
        fetch_urls = self.git(repo, 'remote', 'get-url', '--all', 'origin').splitlines()
        push_urls = self.git(repo, 'remote', 'get-url', '--push', '--all', 'origin').splitlines()
        if not fetch_urls or not push_urls or any(url.removesuffix('.git') not in expected for url in fetch_urls+push_urls):
            raise RuntimeError('Every fetch/push URL must target Biblejustin/'+repo)
        # An explicit HTTPS command must not be rewritten to another host or account.
        try:
            rewrites = self.git(repo, 'config', '--get-regexp', r'^url\..*\.(insteadof|pushinsteadof)$')
        except subprocess.CalledProcessError as error:
            if error.returncode != 1:
                raise
            rewrites = ''
        if rewrites:
            raise RuntimeError('Git URL rewriting requires explicit deployment review: '+repo)
        return self.git(repo, 'rev-parse', 'HEAD')

    def guards(self, revisions=None):
        guards = self.config['guard_sha256']
        if not REQUIRED_GUARDS <= set(guards) or not REQUIRED_RUNNER_FILES <= set(self.config['runner_sha256']):
            raise RuntimeError('Missing approved frozen/runtime/deployment guards')
        for name, expected in guards.items():
            repo, relative = name.split('/', 1)
            if repo not in REPOS or Path(relative).is_absolute() or '..' in Path(relative).parts:
                raise RuntimeError('Invalid guarded path')
            if revisions:
                # Hash bytes exactly. git show through text mode would alter line endings.
                actual = self.git(repo, 'rev-parse', f'{revisions[repo]}:{relative}')
                approved = self.git(repo, 'hash-object', self.workspace/repo/relative)
                if actual != approved:
                    raise RuntimeError('Approved product, runtime, frozen input or deployment changed; review/redeploy: '+name)
            if sha(self.workspace/name) != expected:
                raise RuntimeError('Approved guard changed: '+name)
        deployed = Path(__file__).resolve().parent
        if deployed.is_relative_to(self.workspace):
            raise RuntimeError('Runner must be deployed outside the self-updating workspace')
        for name, expected in self.config['runner_sha256'].items():
            if Path(name).name != name or sha(deployed/name) != expected:
                raise RuntimeError('Deployed runner changed; approved redeployment required: '+name)
        for name in REQUIRED_RUNNER_FILES:
            if 'correlations/ops/vps/'+name not in guards:
                raise RuntimeError('Self-updating source wrapper must have an approved deployment guard: '+name)

    def runtime(self):
        if self.command([self.config['node'], '--version']) != 'v'+self.config['node_version']:
            raise RuntimeError('Node version differs from approved model runtime')
        self.command([self.config['python'], 'verify_environment.py', '--requirements', 'requirements-dev.txt'], cwd=self.workspace/'correlations')

    def remote(self, repo, head, *, refresh_tracking=False):
        reference = 'refs/heads/main'
        value = self.git(repo, *AUTH, 'ls-remote', '--exit-code', f'https://github.com/Biblejustin/{repo}.git', reference).split()
        if value != [head, reference]:
            raise RuntimeError('Actual remote main does not match local HEAD: '+repo)
        if refresh_tracking:
            self.git(repo, *AUTH, 'fetch', '--no-tags', f'https://github.com/Biblejustin/{repo}.git',
                     'refs/heads/main:refs/remotes/origin/main')
            if self.git(repo, 'rev-parse', 'refs/remotes/origin/main') != head:
                raise RuntimeError('Remote changed during tracking-ref verification: '+repo)

    def update(self, expected_account):
        original = {repo: self.local(repo) for repo in REPOS}
        self.guards(); self.runtime()
        candidates = {}
        for repo in REPOS:
            self.git(repo, *AUTH, 'fetch', '--no-tags', f'https://github.com/Biblejustin/{repo}.git',
                     'refs/heads/main:refs/remotes/origin/main')
            candidates[repo] = self.git(repo, 'rev-parse', 'refs/remotes/origin/main')
            self.git(repo, 'merge-base', '--is-ancestor', original[repo], candidates[repo])
        # Preflight every repository before the first merge. No reset, stash or dependency install.
        self.guards(candidates)
        if self.account() != expected_account:
            raise RuntimeError('GitHub identity changed before fast-forward')
        for repo in REPOS:
            if self.local(repo) != original[repo]:
                raise RuntimeError('Concurrent checkout edit before fast-forward: '+repo)
            self.git(repo, 'merge', '--ff-only', candidates[repo])
        self.guards(); self.runtime()
        for repo in REPOS:
            self.remote(repo, self.local(repo))
        return candidates


def environment(config):
    env = dict(os.environ)
    # Do not inherit a caller's target/config overrides; auth tokens remain external.
    for name in list(env):
        if name.startswith('GIT_') and name not in {'GIT_SSH_COMMAND'}:
            env.pop(name)
    env.update(GH_CONFIG_DIR=config['gh_config_dir'], GIT_TERMINAL_PROMPT='0', GH_PROMPT_DISABLED='1',
               MPLBACKEND='Agg', MPLCONFIGDIR=str(Path(config['state_dir'])/'matplotlib'),
               PYTHONUNBUFFERED='1', TZ='America/Chicago', LC_ALL='C.UTF-8',
               PATH=str(Path(config['node']).parent)+':'+str(Path(config['python']).parent)+':/usr/local/bin:/usr/bin:/bin')
    return env


def interrupted_state(state_dir):
    path = Path(state_dir)/'status.json'
    if not path.exists():
        return
    state = json.loads(path.read_text())
    if state.get('last_run', {}).get('status') == 'running':
        previous = json.loads(json.dumps(state))
        state['last_run'].update(status='failed', completed_at=now(), notification_needed=True,
            error='Service terminated before a completion receipt; publication may be partial or unverified')
        attention(state, previous, state['last_run'], [{'kind':'interrupted', 'phase':state['last_run'].get('phase')}])
        write_json(path, state)
        identifier = state['last_run'].get('id', '')
        if re.fullmatch(r'\d{8}T\d{6}\.\d+Z', identifier):
            write_json(Path(state_dir)/'runs'/identifier/'run.json', state['last_run'])


def run(config, *, check_only=False):
    state_dir = Path(config['state_dir']).resolve()
    state_dir.mkdir(parents=True, exist_ok=True)
    try:
        with lock(state_dir/'refresh.lock'):
            return run_locked(config, state_dir, check_only=check_only)
    except BlockingIOError:
        print(json.dumps({'status': 'already_running', 'notification_needed': False}))
        return 75


def run_locked(config, state_dir, *, check_only=False):
    state_path = state_dir/'status.json'
    if not check_only:
        interrupted_state(state_dir)
    previous = json.loads(state_path.read_text()) if state_path.exists() else {}
    identifier = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    run_dir = state_dir/'runs'/identifier
    run_dir.mkdir(parents=True)
    record = {'id': identifier, 'started_at': now(), 'status': 'running', 'phase': 'preflight',
              'publication_state': 'not_attempted', 'remote_verified': False, 'notification_needed': False}
    state = {'schema_version': 1, 'last_run': record, 'last_success': previous.get('last_success')}
    def save():
        if not check_only:
            write_json(state_path, state)
        write_json(run_dir/'run.json', record)
    save()
    with (run_dir/'commands.log').open('w') as log:
        try:
            commands = Commands(log, environment(config), config.get('command_timeout_seconds', 7200))
            runner = Runner(config, commands)
            account = runner.account()
            record['initial_heads'] = {repo: runner.local(repo) for repo in REPOS}
            runner.guards(); runner.runtime()
            if check_only:
                for repo, head in record['initial_heads'].items():
                    runner.remote(repo, head)
                record.update(status='preflight_passed', completed_at=now()); save()
                print(json.dumps({'status': 'preflight_passed', 'publication_state': 'not_attempted'}))
                return 0
            before = snapshot(runner.workspace, REPOS, runner.git)
            write_json(run_dir/'before.json', before)
            baseline = before
            if previous.get('last_success'):
                baseline = json.loads(Path(previous['last_success']['semantic_path']).read_text())
            record['phase'] = 'fast_forward'; save()
            record['updated_heads'] = runner.update(account)
            record.update(phase='publish', publication_state='attempted_completion_unknown'); save()
            runner.command(['make', f'PY={config["python"]}', f'WORKERS={config.get("workers", 2)}', 'publish'], cwd=runner.workspace/'correlations')
            record.update(phase='verify_publication', publication_state='publish_command_completed'); save()
            if runner.account() != account:
                raise RuntimeError('GitHub identity changed during publication')
            runner.guards()
            heads = {repo: runner.local(repo) for repo in REPOS}
            for repo, head in heads.items():
                runner.remote(repo, head, refresh_tracking=True)
            record.update(remote_verified=True, publication_state='remote_publication_verified', final_heads=heads, phase='verify_artifacts'); save()
            validator = Path(__file__).with_name('artifact_validation.py')
            record['validation'] = json.loads(runner.command([config['python'], validator, '--workspace', runner.workspace, '--started-at', record['started_at']]))
            after = snapshot(runner.workspace, REPOS, runner.git)
            comparison = compare(baseline, after, policy=config.get('semantic_policy'))
            write_json(run_dir/'after.json', after); write_json(run_dir/'comparison.json', comparison)
            record['comparison'] = comparison
            reasons = [{'kind':'semantic_change', **row, 'after_sha256':after['tables'].get(row['table'], {}).get('sha256')} for row in comparison['reasons']]
            # A recovered service failure remains visible even when measurements did not change.
            if previous.get('last_run', {}).get('status') == 'failed':
                record.update(notification_needed=True, recovered_previous_failure=True)
            try:
                from monthly_release_review import review_releases
                monthly = review_releases(state_dir/'release_reviews', as_of=dt.datetime.now(ZoneInfo('America/Chicago')).date())
            except Exception as error:
                monthly = {'status': 'failed', 'attention_required': True, 'review_needed': False, 'error': str(error)}
            record['monthly_release_review'] = monthly
            if monthly.get('attention_required') or monthly.get('review_needed'):
                keys = ['source_id', 'status', 'adopted_version', 'latest_version', 'error']
                reasons.append({'kind':'monthly_release_attention', 'status':monthly.get('status'),
                    'error':normalize_error(monthly.get('error', '')),
                    'checks':[{key:normalize_error(row[key]) if key == 'error' else row[key] for key in keys if key in row} for row in monthly.get('checks', [])]})
            runner.guards()
            if runner.account() != account:
                raise RuntimeError('GitHub identity changed during final verification')
            for repo, head in heads.items():
                if runner.local(repo) != head:
                    raise RuntimeError('Checkout changed during final verification: '+repo)
                runner.remote(repo, head, refresh_tracking=True)
            attention(state, previous, record, reasons, recovered=record.get('recovered_previous_failure', False))
            record.update(status='success', phase='complete', completed_at=now())
            state['last_success'] = {'completed_at': record['completed_at'], 'heads': heads,
                'semantic_path': str(run_dir/'after.json'), 'run_path': str(run_dir/'run.json')}
            save()
        except BaseException as error:
            record.update(status='failed', completed_at=now(), notification_needed=True,
                          error=f'{type(error).__name__}: {error}')
            detail = '\n'.join(line for line in (getattr(error, 'output', '') or '').splitlines() if re.search(r'failed|Error|stopped', line, re.I))
            attention(state, previous, record, [{'kind':'run_failure', 'phase':record['phase'],
                'error':normalize_error(record['error']), 'detail_sha256':hashlib.sha256(normalize_error(detail).encode()).hexdigest()}])
            save()
            print(json.dumps({'status': record['status'], 'phase': record['phase'], 'publication_state': record['publication_state'], 'action_required': True, 'notification_needed': record['notification_needed'], 'state_path': str(state_path)}))
            return 1
    print(json.dumps({'status': record['status'], 'publication_state': record['publication_state'], 'action_required': record['action_required'], 'notification_needed': record['notification_needed'], 'state_path': str(state_path)}))
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True, type=Path)
    parser.add_argument('--check', action='store_true', help='Auth/clean-main/remote/runtime/guard preflight; no fetch or publish')
    parser.add_argument('--mark-interrupted', action='store_true', help='systemd ExecStopPost: record missing completion receipt')
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    if args.mark_interrupted:
        state_dir = Path(config['state_dir']); state_dir.mkdir(parents=True, exist_ok=True)
        try:
            with lock(state_dir/'refresh.lock'):
                interrupted_state(state_dir)
        except BlockingIOError:
            pass
        return 0
    def stop(signum, frame):
        raise InterruptedError('Received termination signal '+str(signum))
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    return run(config, check_only=args.check)


if __name__ == '__main__':
    raise SystemExit(main())
