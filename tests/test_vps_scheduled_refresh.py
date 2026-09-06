"""Safety boundaries; fixtures never access network or real repositories."""
import io
import json
from pathlib import Path
import subprocess
import sys
import types
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'ops' / 'vps'))
import scheduled_refresh as runner
from semantic_snapshot import csv_summary, compare


def test_alternate_push_owner_is_rejected(tmp_path):
    def command(args, **kwargs):
        tail = args[3:]
        if tail == ['rev-parse', '--show-toplevel']: return str(tmp_path/'correlations')
        if tail == ['symbolic-ref', '--short', 'HEAD']: return 'main'
        if tail[:2] == ['status', '--porcelain']: return ''
        if tail == ['remote', 'get-url', '--all', 'origin']: return 'https://github.com/Biblejustin/correlations.git'
        if tail == ['remote', 'get-url', '--push', '--all', 'origin']:
            return 'https://github.com/Biblejustin/correlations.git\nhttps://github.com/other/correlations.git'
        raise AssertionError(tail)
    with pytest.raises(RuntimeError, match='Every fetch/push URL'):
        runner.Runner({'workspace': str(tmp_path)}, command).local('correlations')


@pytest.mark.parametrize('login', ['another-account', 'biblejustin', ''])
def test_wrong_account_stops_before_git(login, tmp_path):
    instance = runner.Runner({'workspace': str(tmp_path)}, lambda args: json.dumps({'login': login, 'id': 1}))
    with pytest.raises(RuntimeError, match='Biblejustin'):
        instance.account()


@pytest.mark.parametrize('failure', ['divergence', 'frozen_change'])
def test_all_candidates_preflight_before_any_merge(monkeypatch, tmp_path, failure):
    monkeypatch.setattr(runner, 'REPOS', ['one', 'two'])
    class Fake(runner.Runner):
        def __init__(self): super().__init__({'workspace': str(tmp_path)}, None); self.calls=[]
        def local(self, repo): return 'old'
        def runtime(self): pass
        def guards(self, revisions=None):
            if revisions and failure == 'frozen_change': raise RuntimeError('frozen change')
        def account(self): return {'login':'Biblejustin', 'id':1}
        def remote(self, repo, head, **kwargs): pass
        def git(self, repo, *args):
            self.calls.append((repo, args))
            if args == ('rev-parse', 'refs/remotes/origin/main'): return 'new'
            if args[:2] == ('merge-base', '--is-ancestor') and repo == 'two' and failure == 'divergence':
                raise subprocess.CalledProcessError(1, args)
            return ''
    instance=Fake()
    with pytest.raises((RuntimeError, subprocess.CalledProcessError)):
        instance.update({'login':'Biblejustin', 'id':1})
    assert not any(args[0] == 'merge' for _, args in instance.calls)


def test_changed_frozen_bytes_fail_guard_even_without_update(monkeypatch, tmp_path):
    workspace=tmp_path/'work';deployed=tmp_path/'bin';deployed.mkdir();(deployed/'scheduled_refresh.py').write_text('runner')
    guarded=workspace/'correlations/ops/vps/scheduled_refresh.py';guarded.parent.mkdir(parents=True);guarded.write_text('approved')
    monkeypatch.setattr(runner, '__file__', str(deployed/'scheduled_refresh.py'))
    monkeypatch.setattr(runner, 'REQUIRED_GUARDS', {'correlations/ops/vps/scheduled_refresh.py'})
    monkeypatch.setattr(runner, 'REQUIRED_RUNNER_FILES', {'scheduled_refresh.py'})
    config={'workspace':str(workspace),'guard_sha256':{'correlations/ops/vps/scheduled_refresh.py':runner.sha(guarded)},'runner_sha256':{'scheduled_refresh.py':runner.sha(deployed/'scheduled_refresh.py')}}
    guarded.write_text('changed')
    with pytest.raises(RuntimeError, match='Approved guard changed'):
        runner.Runner(config, None).guards()


def test_nonblocking_lock_never_overwrites_active_state(tmp_path):
    path=tmp_path/'refresh.lock'
    with runner.lock(path):
        with pytest.raises(BlockingIOError):
            with runner.lock(path): pass


def fixture_run(monkeypatch, tmp_path, failure):
    monkeypatch.setattr(runner, 'REPOS', ['correlations'])
    initial={'schema_version':1,'tables':{}}
    baseline=tmp_path/'previous.json';baseline.write_text(json.dumps(initial))
    previous={'last_run':{'status':'success'},'last_success':{'semantic_path':str(baseline),'heads':{'correlations':'previous'}}}
    (tmp_path/'status.json').write_text(json.dumps(previous))
    class FakeCommands:
        def __init__(self, *args): pass
        def __call__(self, args, **kwargs):
            if args[0] == 'make' and failure == 'publish': raise subprocess.CalledProcessError(1,args)
            if '--started-at' in args:
                if failure == 'postcheck': raise ValueError('broken artifact')
                return '{"status":"passed"}'
            return ''
    class FakeRunner:
        def __init__(self, config, commands): self.workspace=tmp_path;self.command=commands
        def account(self): return {'login':'Biblejustin','id':1}
        def local(self, repo): return 'head'
        def remote(self, repo, head, **kwargs):
            if failure == 'remote': raise RuntimeError('actual remote mismatch')
        def runtime(self): pass
        def guards(self): pass
        def update(self, account): return {'correlations':'head'}
        def git(self, *args): return ''
    monkeypatch.setattr(runner, 'Commands', FakeCommands);monkeypatch.setattr(runner, 'Runner', FakeRunner)
    monkeypatch.setattr(runner, 'snapshot', lambda *args:initial)
    monthly={'status':'incomplete','attention_required':True,'review_needed':False} if failure == 'monthly' else {'status':'current','attention_required':False,'review_needed':False}
    monkeypatch.setitem(sys.modules,'monthly_release_review',types.SimpleNamespace(review_releases=lambda *a,**k:monthly))
    config={'state_dir':str(tmp_path),'workspace':str(tmp_path/'workspace'),'python':'/python','node':'/node','gh_config_dir':str(tmp_path/'github')}
    code=runner.run(config)
    return code,json.loads((tmp_path/'status.json').read_text()),previous


@pytest.mark.parametrize('failure,state', [('publish','attempted_completion_unknown'),('remote','publish_command_completed'),('postcheck','remote_publication_verified')])
def test_failed_runs_preserve_success_and_honest_publication_state(monkeypatch,tmp_path,failure,state):
    code,result,previous=fixture_run(monkeypatch,tmp_path,failure)
    assert code == 1 and result['last_run']['status'] == 'failed'
    assert result['last_run']['publication_state'] == state
    assert result['last_run']['notification_needed'] is True
    assert result['last_success'] == previous['last_success']


def test_release_review_failure_does_not_deny_completed_publication(monkeypatch,tmp_path):
    code,result,_=fixture_run(monkeypatch,tmp_path,'monthly')
    assert code == 0 and result['last_run']['status'] == 'success'
    assert result['last_run']['publication_state'] == 'remote_publication_verified'
    assert result['last_run']['monthly_release_review']['status'] == 'incomplete'
    assert result['last_run']['notification_needed'] is True


def test_metadata_renumbering_and_routine_lake_addition_stay_quiet(tmp_path):
    path=tmp_path/'lake.csv';name='israel-rain-agriculture/data/kinneret_levels.csv'
    path.write_text('observation_date,level_m,source_record_id,fetched_at\n2026-09-01,-213.1,1,old\n')
    before={'schema_version':1,'tables':{name:csv_summary(path,name)}}
    path.write_text('observation_date,level_m,source_record_id,fetched_at\n2026-09-02,-213.2,1,new\n2026-09-01,-213.10000000000001,2,new\n')
    after={'schema_version':1,'tables':{name:csv_summary(path,name)}}
    result=compare(before,after)
    assert not result['notification_needed'] and len(result['routine_changes']) == 1
    path.write_text('observation_date,level_m,source_record_id,fetched_at\n2026-09-01,-213.3,7,new\n')
    revised={'schema_version':1,'tables':{name:csv_summary(path,name)}}
    assert compare(before,revised)['notification_needed']


def test_portwatch_provider_ids_and_unusable_padding_ignored_but_revision_flagged(tmp_path):
    path=tmp_path/'daily.csv';name='correlations/data/trade_shipping/active/daily.csv'
    path.write_text('date,chokepoint,capacity,ObjectId,usable,fetched_at\n2026-08-01,Suez Canal,12,1,True,old\n')
    before=csv_summary(path,name)
    path.write_text('date,chokepoint,capacity,ObjectId,usable,fetched_at\n2026-08-01,Suez Canal,12,77,True,new\n2026-09-06,Suez Canal,,,False,new\n')
    assert csv_summary(path,name) == before
    path.write_text('date,chokepoint,capacity,ObjectId,usable,fetched_at\n2026-08-01,Suez Canal,13,77,True,new\n')
    assert csv_summary(path,name)['sha256'] != before['sha256']


def test_new_major_flare_or_eligible_result_changes_are_visible(tmp_path):
    path=tmp_path/'flare.csv';name='correlations/data/flares_swpc.csv'
    path.write_text('event_id,class\na,C5.0\n');old=csv_summary(path,name)
    path.write_text('event_id,class\na,C5.0\nb,B8.0\n');assert csv_summary(path,name)==old
    path.write_text('event_id,class\na,C5.0\nb,M1.0\n');assert csv_summary(path,name)!=old
    before={'schema_version':1,'tables':{'fit':{'rows':1,'sha256':'unavailable'}}}
    after={'schema_version':1,'tables':{'fit':{'rows':1,'sha256':'eligible'}}}
    assert compare(before,after)['notification_needed']


def test_timer_keeps_explicit_chicago_zone_and_catchup():
    text=(Path(runner.__file__).with_name('correlations-refresh.timer')).read_text()
    assert 'OnCalendar=*-*-* 06:30:00 America/Chicago' in text and 'Persistent=true' in text


def test_attention_deduplicates_unchanged_failure_and_monthly_review_but_reports_recovery():
    for reason in [{'kind':'run_failure','error':'same source outage'}, {'kind':'monthly_release_attention','status':'incomplete'}]:
        state,record={},{}
        runner.attention(state,{},record,[reason])
        assert record['action_required'] and record['notification_needed']
        second,next_record={},{}
        runner.attention(second,state,next_record,[reason])
        assert next_record['action_required'] and not next_record['notification_needed']
        recovered,recovered_record={},{}
        runner.attention(recovered,second,recovered_record,[],recovered=True)
        assert not recovered_record['action_required'] and recovered_record['notification_needed']


def test_preflight_preserves_authoritative_status(monkeypatch,tmp_path):
    fixture_run(monkeypatch,tmp_path,'monthly')
    status=tmp_path/'status.json';previous=status.read_bytes()
    config={'state_dir':str(tmp_path),'workspace':str(tmp_path/'workspace'),'python':'/python','node':'/node','gh_config_dir':str(tmp_path/'github')}
    assert runner.run(config,check_only=True)==0
    assert status.read_bytes()==previous


def test_interrupted_run_updates_both_receipts_without_advancing_success(tmp_path):
    identifier='20260906T120000.123456Z'
    state={'last_run':{'id':identifier,'status':'running','phase':'publish','publication_state':'attempted_completion_unknown'},'last_success':{'heads':{'correlations':'old'}}}
    (tmp_path/'status.json').write_text(json.dumps(state))
    runner.interrupted_state(tmp_path)
    updated=json.loads((tmp_path/'status.json').read_text())
    assert updated['last_run']==json.loads((tmp_path/'runs'/identifier/'run.json').read_text())
    assert updated['last_success']==state['last_success']
    assert updated['last_run']['action_required'] and updated['last_run']['notification_needed']


def test_tracking_ref_is_updated_and_race_detected(tmp_path):
    calls=[]
    def command(args,**kwargs):
        calls.append(args)
        if 'ls-remote' in args:return 'expected\trefs/heads/main'
        if 'rev-parse' in args:return 'concurrent-new-remote'
        return ''
    with pytest.raises(RuntimeError,match='Remote changed'):
        runner.Runner({'workspace':str(tmp_path)},command).remote('correlations','expected',refresh_tracking=True)
    assert any('refs/heads/main:refs/remotes/origin/main' in args for args in calls)


@pytest.mark.parametrize('levels', [(-213.365,-215.0),(-212.99,-213.01)])
def test_lake_large_move_or_reference_crossing_requires_descriptive_review(tmp_path,levels):
    path=tmp_path/'lake.csv';name='israel-rain-agriculture/data/kinneret_levels.csv'
    path.write_text(f'observation_date,level_m\n2026-09-01,{levels[0]}\n')
    before={'schema_version':1,'tables':{name:csv_summary(path,name)}}
    path.write_text(f'observation_date,level_m\n2026-09-01,{levels[0]}\n2026-09-02,{levels[1]}\n')
    after={'schema_version':1,'tables':{name:csv_summary(path,name)}}
    result=compare(before,after)
    assert result['notification_needed'] and result['reasons'][0]['physical_review']


def test_receipt_age_and_latest_week_label_are_not_measurement_changes(tmp_path):
    for name,column in [('affordability_latest_series.csv','age_months'),('seasonal_flu_weekly.csv','latest_expected_week')]:
        path=tmp_path/name
        path.write_text(f'period_start,value,{column}\n2026-08-01,3,1\n');before=csv_summary(path,name)
        path.write_text(f'period_start,value,{column}\n2026-08-01,3,2\n')
        assert csv_summary(path,name)==before


def test_failure_fingerprint_ignores_receipt_dates_and_elapsed_seconds():
    assert runner.normalize_error('failed 2026-09-06T11:42:36.668757+00:00 (3.2s)') == runner.normalize_error('failed 2026-09-07T11:42:36.122+00:00 (9.5s)')


def test_only_portwatch_edit_marker_is_receipt_metadata(tmp_path):
    path=tmp_path/'daily.csv';shipping='correlations/data/trade_shipping/active/daily.csv'
    path.write_text('date,capacity,source_version\n2026-08-01,12,item; source edit 100\n')
    before_shipping=csv_summary(path,shipping)
    before_other=csv_summary(path,'correlations/data/other_product.csv')
    path.write_text('date,capacity,source_version\n2026-08-01,12,item; source edit 200\n')
    assert csv_summary(path,shipping)==before_shipping
    assert csv_summary(path,'correlations/data/other_product.csv')!=before_other
