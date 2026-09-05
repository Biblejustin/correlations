import json
from pathlib import Path
import sqlite3

import pandas as pd
import pytest

from flare_ingest import ingest_recent_flares
from source_tracking import changed_groups,collect_fingerprints,sqlite_digest
from run_suite import run_step
from weekly_update import generated_path


def payload(path,klass='X1.2'):
    path.write_text(json.dumps([{'begin_time':'2026-08-31T00:00:00Z',
                                'max_time':'2026-08-31T00:10:00Z','max_class':klass,'satellite':18}]))


def test_flare_revisions_idempotent_and_downgrade(tmp_path):
    raw=tmp_path/'raw.json';data=tmp_path/'data';data.mkdir()
    for _ in range(2):
        payload(raw);ingest_recent_flares(raw,data,'2026-09-01T00:00:00Z')
    assert len(pd.read_csv(data/'flares_swpc.csv'))==1
    assert len(pd.read_csv(data/'flares_xclass.csv'))==1
    payload(raw,'M9.1');ingest_recent_flares(raw,data,'2026-09-02T00:00:00Z')
    assert pd.read_csv(data/'flares_swpc.csv')['class'].tolist()==['M9.1']
    assert pd.read_csv(data/'flares_xclass.csv').empty


def test_quiet_weeks_observed_missed_weeks_unknown(tmp_path):
    raw=tmp_path/'raw.json';data=tmp_path/'data'
    for date in ['2026-08-01T00:00:00Z','2026-09-01T00:00:00Z']:
        raw.write_text('[]');ingest_recent_flares(raw,data,date)
    intervals=json.loads((data/'swpc_observation_intervals.json').read_text())['intervals']
    assert len(intervals)==2
    assert pd.Timestamp(intervals[1]['start'])>pd.Timestamp(intervals[0]['end'])
    assert pd.read_csv(data/'flares_swpc.csv').empty


def test_invalid_payload_does_not_claim_coverage(tmp_path):
    raw=tmp_path/'raw.json';raw.write_text('{"error":"upstream"}')
    with pytest.raises(ValueError):ingest_recent_flares(raw,tmp_path/'data')
    assert raw.exists()
    assert not (tmp_path/'data/swpc_observation_intervals.json').exists()


def test_same_count_csv_revision_changes_fingerprint(tmp_path):
    data=tmp_path/'data';data.mkdir();path=data/'events.csv'
    path.write_text('year,deaths\n2020,100\n');before=collect_fingerprints(tmp_path)
    path.write_text('year,deaths\n2020,200\n');after=collect_fingerprints(tmp_path)
    assert changed_groups(before,after)==(True,False,False)


def test_sqlite_hash_detects_correction_ignores_vacuum(tmp_path):
    path=tmp_path/'events.sqlite'
    with sqlite3.connect(path) as con:
        con.execute('CREATE TABLE events(id INTEGER PRIMARY KEY, deaths INT)')
        con.execute('INSERT INTO events VALUES(1,100)')
    before=sqlite_digest(path,['events'])
    with sqlite3.connect(path) as con:con.execute('VACUUM')
    assert sqlite_digest(path,['events'])==before
    with sqlite3.connect(path) as con:con.execute('UPDATE events SET deaths=200')
    assert sqlite_digest(path,['events'])!=before


def test_missing_database_hash_read_only(tmp_path):
    path=tmp_path/'missing.sqlite'
    assert sqlite_digest(path,['events']) is None
    assert not path.exists()


def test_stage_failure_and_skip_visible(tmp_path):
    import sys
    failed=run_step('failure',[sys.executable,'-c','raise RuntimeError("visible")'],cwd=tmp_path,log_dir=tmp_path)
    assert failed['status']=='failed'
    assert 'visible' in Path(failed['log']).read_text()
    skipped=run_step('skipped',[sys.executable,'-c','print("SKIPPED: missing source")'],cwd=tmp_path,log_dir=tmp_path)
    assert skipped['status']=='unavailable'


def test_publish_scope_excludes_code_and_notebooks():
    assert generated_path('data/monitoring/who.csv.gz')
    assert generated_path('figures/result.png')
    assert not generated_path('analyze.py')
    assert not generated_path('earthquakes.ipynb')
    assert not generated_path('README.md')


def test_unknown_annual_pair_retains_result_schema():
    from correlate_events import yearly_corr
    result=yearly_corr(pd.Series([float('nan')],index=[2020]),pd.Series([1],index=[2020]))
    assert result['n']==0
    assert set(result)=={'n','raw_r','raw_p','raw_rho','raw_p_spear','det_r','det_p'}
    assert pd.isna(result['raw_rho'])


def test_push_url_owner_verified_independently(monkeypatch):
    import weekly_update
    monkeypatch.setattr(weekly_update,'git',lambda *a:'https://github.com/untrusted/correlations.git')
    with pytest.raises(RuntimeError):weekly_update.verify_push_urls('correlations')
    monkeypatch.setattr(weekly_update,'git',lambda *a:'https://github.com/Biblejustin/correlations.git')
    weekly_update.verify_push_urls('correlations')


def test_sqlite_coverage_revision_changes_earthquake_flag(tmp_path):
    root=tmp_path/'correlations';root.mkdir();eq=tmp_path/'earthquakes';eq.mkdir()
    before=collect_fingerprints(root)
    (eq/'quakes.sqlite.coverage.json').write_text('{"end_year":2025}')
    after=collect_fingerprints(root)
    assert changed_groups(before,after)==(True,True,False)


def test_flare_withdrawal_reconciles_only_observed_window(tmp_path):
    raw=tmp_path/'raw.json';data=tmp_path/'data'
    payload(raw);ingest_recent_flares(raw,data,'2026-09-01T00:00:00Z')
    raw.write_text('[]');ingest_recent_flares(raw,data,'2026-09-02T00:00:00Z')
    assert pd.read_csv(data/'flares_swpc.csv').empty
    assert pd.read_csv(data/'flares_xclass.csv').empty
    assert len(pd.read_csv(data/'flares_swpc_withdrawn.csv'))==1
    payload(raw);ingest_recent_flares(raw,data,'2026-09-02T00:00:00Z')
    raw.write_text('[]');ingest_recent_flares(raw,data,'2026-10-02T00:00:00Z')
    assert len(pd.read_csv(data/'flares_swpc.csv'))==1
