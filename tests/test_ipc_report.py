"""Visible source lineage for current-type IPC assessment history."""
from monitoring import analysis as A, feeds as F


def test_ipc_report_exposes_retained_quarantine_and_unknown_lineage(tmp_path):
    rows=[]
    statuses={
        'ETH':'retained prior snapshot; current history identity quarantined',
        'SOM':'retained prior snapshot; period absent from current history export',
        'LBN':'present in full-history export',
        'YEM':None,
    }
    for country,status in statuses.items():
        desc={'type':'current','assessment':'May 2021','geography_comparable_to_country':False}
        if status is not None:desc['source_snapshot_status']=status
        rows.append(F.obs(country,'2021-05-01','2021-06-30','ipc_phase_3plus_fraction',.3,
            'fraction_of_population_analyzed','ipc','https://example.org/history.csv',frequency='assessment',
            numerator=300,denominator=1000,dimensions=desc))
    # Future projections must not replace current-type assessments in this table.
    rows.append(F.obs('ETH','2026-07-01','2026-09-30','ipc_phase_3plus_fraction',.99,
        'fraction_of_population_analyzed','ipc','https://example.org/history.csv',frequency='assessment',
        numerator=990,denominator=1000,dimensions={'type':'first projection','source_snapshot_status':'present in full-history export'}))
    observations=F.frame(rows)
    panel=A.build_annual_panel(observations,as_of='2026-09-05')
    tests=A.lag_tests(panel,n_permutations=9)
    sync=A.synchrony(panel,n_permutations=9)
    A.write_report(observations,panel,tests,sync,tmp_path,as_of='2026-09-05',n_permutations=9)
    report=(tmp_path/'monitoring_report.md').read_text()
    table=report.split('## Food security: latest current assessment',1)[1].split('Food affordability:',1)[0]
    assert 'Source snapshot status' in table
    for country,status in statuses.items():
        line=next(line for line in table.splitlines() if line.startswith(f'| {country} |'))
        assert '30.0% | 1,000' in line
        assert 'expired assessment; not present-day estimate' in line
        assert (status or 'legacy snapshot; full-history lineage unverified') in line
    assert '| ISR | unavailable | — | — | no fetched current assessment | unavailable |' in table
    assert '99.0%' not in table
    assert 'full national assessment-history export' in report
    assert 'not certified as current full-history observations' in report
    assert 'Earlier snapshots accumulate prospectively' not in report
