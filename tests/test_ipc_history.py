"""Assessment history/revision contracts; no inferred source IDs or geographic match."""
import json
import io
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from monitoring import feeds as F, analysis as A


def assessment(label='May 2021',start='2021-05-01',end='2021-06-30',validity='current',total=1000,high=300,country='ETH'):
    rows=[]
    for phase,count in [('all',total),('3+',high),('3',high),('4',0),('5',0)]:
        rows.append({'Country':country,'Date of analysis':label,'From':start,'To':end,'Validity period':validity,
                     'Total country population':5000,'Phase':phase,'Number':count,'Percentage':count/total})
    return pd.DataFrame(rows)


def normalized(raw):
    return F.normalize_ipc(raw,['ETH'],2000,'https://example.org/full-history.csv','2026-09-01')


def test_adapter_selects_complete_history_and_preserves_all_periods():
    raw=pd.concat([assessment(),assessment('May 2023','2023-05-01','2023-06-30'),
                   assessment('May 2023','2023-07-01','2023-09-30','first projection')])
    with patch.object(F,'hdx_resource',return_value=(raw,'https://example.org/history.csv','2026-09-01')) as fetch:
        data=F.ipc(None,['ETH'],2000)
    assert fetch.call_args.args[-1]=='ipc_global_national_long.csv'
    assert len(data)==12
    desc=data.dimensions.map(json.loads)
    assert desc.map(lambda r:r['assessment']).nunique()==2
    assert desc.map(lambda r:r['derived_period_key']).nunique()==3
    assert desc.map(lambda r:r['source_analysis_id'] is None).all()
    assert desc.map(lambda r:r['geography_comparable_to_country'] is False).all()
    assert set(data.denominator)=={1000}
    assert data.provisional.sum()==4
    assert A.build_annual_panel(data,as_of='2026-09-05').empty


def test_same_period_revision_replaces_counts_and_denominator_only_for_that_identity():
    old=normalized(pd.concat([assessment(),assessment('May 2022','2022-05-01','2022-06-30'),
                             assessment('May 2021','2021-05-01','2021-06-30','first projection')]))
    old['fetched_at']='2025-01-01'
    new=normalized(assessment(total=2000,high=800))
    new['fetched_at']='2026-09-05'
    merged=F.merge_ipc_history(old,new,new.attrs['ipc_history'])
    high=merged[merged.metric.eq('ipc_phase_3plus_fraction')]
    revised=high[high.dimensions.map(lambda s:json.loads(s)['source_snapshot_status']).eq('present in full-history export')]
    assert len(high)==3
    assert len(revised)==1 and revised.iloc[0].value==.4 and revised.iloc[0].denominator==2000
    assert (high[high.index!=revised.index[0]].fetched_at=='2025-01-01').all()
    assert high[high.index!=revised.index[0]].denominator.eq(1000).all()


def test_explicitly_missing_revised_phase_does_not_resurrect_prior_value():
    old=normalized(assessment())
    raw=assessment()
    raw.loc[raw.Phase.eq('4'),['Number','Percentage']]=float('nan')
    new=normalized(raw)
    merged=F.merge_ipc_history(old,new,new.attrs['ipc_history'])
    assert not merged.metric.eq('ipc_phase_4_fraction').any()


def test_ambiguous_scope_is_quarantined_with_evidence_not_paired_or_deduplicated():
    raw=pd.concat([assessment(total=1000,high=300),assessment(total=100,high=90),
                   assessment('May 2022','2022-05-01','2022-06-30')])
    new=normalized(raw)
    assert len(new)==4 and new.period_start.eq('2022-05-01').all()
    issues=new.attrs['ipc_history']['quarantined_periods']
    assert len(issues)==1 and issues[0]['source_rows']==10
    evidence=pd.read_csv(io.StringIO(new.attrs['ipc_quarantine_csv']))
    assert sorted(evidence.loc[evidence.Phase.eq('all'),'Number'])==[100,1000]
    prior=normalized(assessment(total=100,high=90));prior['source_url']='https://example.org/latest-only.csv';prior['fetched_at']='2025-01-01'
    merged=F.merge_ipc_history(prior,new,new.attrs['ipc_history'])
    retained=merged[merged.period_start.eq('2021-05-01')]
    assert len(retained)==4
    assert retained.source_url.eq('https://example.org/latest-only.csv').all()
    assert retained.denominator.eq(100).all()
    assert retained.dimensions.map(lambda s:'quarantined' in json.loads(s)['source_snapshot_status']).all()


def test_missing_denominator_never_borrows_from_another_period():
    current=assessment();current=current[current.Phase.ne('all')]
    new=normalized(pd.concat([current,assessment('May 2021','2021-07-01','2021-09-30','first projection')]))
    assert len(new)==4 and new.period_start.eq('2021-07-01').all()
    assert len(new.attrs['ipc_history']['quarantined_periods'])==1


def test_incompatible_fraction_fails_before_publication():
    raw=assessment();raw.loc[raw.Phase.eq('3+'),'Percentage']=.9
    with pytest.raises(ValueError,match='incompatible'):normalized(raw)


def test_actual_sudan_complete_partition_conflict_is_excluded_even_from_prior_snapshot():
    # Official full-history AND latest-only exports contain this Jan 2026 projection.
    # Source phase-all47,535,794 versus phase1–5 total8,289,610; do not invent a denominator.
    counts={'all':47535794,'1':737813,'2':1977719,'3':3126748,'4':2247617,'5':199713,'3+':5574078}
    raw=pd.DataFrame([{'Country':'SDN','Date of analysis':'Jan 2026','Validity period':'first projection',
        'From':'2026-06-01','To':'2026-09-30','Phase':phase,'Number':count,
        'Percentage':round(count/counts['all'],2)} for phase,count in counts.items()])
    fresh=F.normalize_ipc(raw,['SDN'],2000,'https://example.org/full-history.csv')
    assert fresh.empty
    issue=fresh.attrs['ipc_history']['quarantined_periods'][0]
    assert issue['failure_kind']=='invalid_partition'
    assert issue['supplied_phase_sum']==8289610 and issue['reported_total']==47535794
    previous=F.frame([F.obs('SDN','2026-06-01','2026-09-30','ipc_phase_'+phase.replace('+','plus')+'_fraction',
        round(counts[phase]/counts['all'],2),'fraction_of_population_analyzed','ipc','https://example.org/latest.csv',
        numerator=counts[phase],denominator=counts['all'],frequency='assessment',
        dimensions={'assessment':'Jan 2026','type':'first projection'}) for phase in ['3+','3','4','5']])
    good=F.normalize_ipc(assessment(country='SDN'),['SDN'],2000,'https://example.org/full-history.csv')
    evidence=fresh.attrs['ipc_history']
    evidence['accepted_period_keys']=good.attrs['ipc_history']['accepted_period_keys']
    merged=F.merge_ipc_history(previous,good,evidence)
    assert not merged.period_start.eq('2026-06-01').any()


@pytest.mark.parametrize('missing',[False,True])
def test_phase_three_plus_partition_cannot_hide_conflicts(missing):
    raw=assessment()
    raw.loc[raw.Phase.eq('3'),'Number']=600
    raw.loc[raw.Phase.eq('3'),'Percentage']=.6
    if missing:raw.loc[raw.Phase.eq('4'),['Number','Percentage']]=float('nan')
    data=normalized(raw)
    assert data.empty
    assert data.attrs['ipc_history']['quarantined_periods'][0]['failure_kind']=='invalid_partition'


def test_conservative_partition_tolerance_preserves_published_rounding_differences():
    raw=assessment(total=100000,high=30000)
    raw=pd.concat([raw,pd.DataFrame([{**raw.iloc[0].to_dict(),'Phase':'1','Number':35000,'Percentage':.35},
                                   {**raw.iloc[0].to_dict(),'Phase':'2','Number':34500,'Percentage':.35}])])
    data=normalized(raw)
    assert len(data)==4 and not data.attrs['ipc_history']['quarantined_periods']
    assert set(data.denominator)=={100000}


def test_refresh_archives_prior_revision_and_keeps_diagnostics_outside_observations(tmp_path):
    output=tmp_path/'monitoring'
    class Client:
        def __init__(self,**kwargs):self.requests=[{'url':'https://example.org/history.csv','fetched_at':'2026-09-05','sha256':'fixture'}]
    with patch.object(F,'Client',Client),patch.dict(F.ADAPTERS,{'ipc':lambda *args:normalized(assessment())}):
        F.refresh('ipc',output=output)
    original=(output/'ipc.csv').read_bytes()
    with patch.object(F,'Client',Client),patch.dict(F.ADAPTERS,{'ipc':lambda *args:normalized(assessment(total=2000,high=800))}):
        result=F.refresh('ipc',output=output)
    archives=list((tmp_path/'diagnostics/ipc_history/prior_snapshots').glob('*.csv'))
    assert len(archives)==1 and archives[0].read_bytes()==original
    assert len(A.load_observations(output))==4
    assert result['history']['accepted_periods']==1
    assert Path(tmp_path/result['history']['quarantine_evidence']).is_file()
    # Replaying an unchanged release adds no archival revision.
    with patch.object(F,'Client',Client),patch.dict(F.ADAPTERS,{'ipc':lambda *args:normalized(assessment(total=2000,high=800))}):
        F.refresh('ipc',output=output)
    assert len(list(archives[0].parent.glob('*.csv')))==1


def test_truncated_history_cannot_hide_shrink_by_merging_old_rows(tmp_path):
    output=tmp_path/'monitoring'
    class Client:
        def __init__(self,**kwargs):self.requests=[{'fetched_at':'2026-09-05'}]
    full=normalized(pd.concat([assessment(),assessment('May 2022','2022-05-01','2022-06-30')]))
    with patch.object(F,'Client',Client),patch.dict(F.ADAPTERS,{'ipc':lambda *args:full.copy()}):F.refresh('ipc',output=output)
    before=(output/'ipc.csv').read_bytes()
    with patch.object(F,'Client',Client),patch.dict(F.ADAPTERS,{'ipc':lambda *args:normalized(assessment())}):
        with pytest.raises(ValueError,match='suspicious full-history source shrink'):F.refresh('ipc',output=output)
    assert (output/'ipc.csv').read_bytes()==before
