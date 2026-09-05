import json

import pytest

import weekly_update as W


def isolated_runner(tmp_path,monkeypatch,fail=None):
    for repo in W.REPOS:(tmp_path/repo).mkdir()
    monkeypatch.setattr(W,'ROOT',tmp_path)
    monkeypatch.setattr(W,'BASE',tmp_path/'correlations')
    calls=[]
    def run(name,cmd,**kwargs):
        calls.append((name,cmd))
        return {'stage':name,'status':'failed' if name==fail else 'passed','log':'fixture.log'}
    monkeypatch.setattr(W,'run_step',run)
    monkeypatch.setattr(W,'run_suite',lambda **kw:pytest.fail('fetch-only ran analyses'))
    return calls


def test_fetch_selection_tested_first_and_receipt_separate(tmp_path,monkeypatch):
    calls=isolated_runner(tmp_path,monkeypatch)
    W.main(['--fetch-only','--dry-run','--sources','quakes','israel_rain'])
    assert [name for name,_ in calls]==['regression_tests','fetch_quakes','fetch_israel_rain']
    result=json.loads((W.BASE/'results/fetch_run.json').read_text())
    assert result['success'] and result['fetch_only']
    assert not (W.BASE/'results/refresh_run.json').exists()
    assert '--min-mag' not in calls[1][1]  # Default M4 modern catalog, never Make's old M6 override.


def test_failing_tests_stop_before_network(tmp_path,monkeypatch):
    calls=isolated_runner(tmp_path,monkeypatch,fail='regression_tests')
    with pytest.raises(SystemExit):W.main(['--fetch-only','--sources','quakes'])
    assert [name for name,_ in calls]==['regression_tests']
    assert not json.loads((W.BASE/'results/fetch_run.json').read_text())['success']


@pytest.mark.parametrize('args',[
    ['--fetch-only','--publish'],['--fetch-only','--skip-fetch'],
    ['--sources','quakes'],['--workers','0'],['--publish','--dry-run'],
])
def test_incompatible_modes_rejected_before_actions(monkeypatch,args):
    monkeypatch.setattr(W,'verify_publish_targets',lambda:pytest.fail('publish invoked'))
    with pytest.raises(SystemExit) as error:W.main(args)
    assert error.value.code==2
