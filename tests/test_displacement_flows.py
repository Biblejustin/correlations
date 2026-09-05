import json

import pandas as pd
import pytest

from monitoring.feeds import normalize_idmc
from monitoring.analysis import build_annual_panel


def fixture():
    return pd.DataFrame([
        ['ISR','Israel',2023,120,90],
        ['ISR','Israel',2024,None,80],
        ['ISR','Israel',2025,0,None],
    ],columns=['iso3','country_name','year','new_displacement','total_displacement'])


def test_flows_not_inferred_from_stock_and_missing_not_zero():
    d=normalize_idmc(fixture(),'ISR','https://data.humdata.org/')
    flows=d[d.metric.eq('internal_displacements_flow')]
    assert flows.value.tolist()==[120,0]
    assert flows.unit.eq('displacement movements').all()
    assert not flows.period_start.str.startswith('2024').any()
    assert not json.loads(flows.iloc[0].dimensions)['population_denominator_compatible']
    panel=build_annual_panel(d,as_of='2026-09-05')
    assert len(panel)==4
    assert not panel.metric.str.endswith('per_100k').any()


@pytest.mark.parametrize('defect',['country','duplicate','negative','event','year'])
def test_invalid_or_wrong_scope_export_refused(defect):
    d=fixture()
    if defect=='country':d.loc[0,'iso3']='PSE'
    if defect=='duplicate':d=pd.concat([d,d.iloc[:1]])
    if defect=='negative':d.loc[0,'new_displacement']=-1
    if defect=='event':d['event_name']='flood'
    if defect=='year':d['year']=d.year.astype(float);d.loc[0,'year']=2023.5
    with pytest.raises(ValueError):normalize_idmc(d,'ISR','https://data.humdata.org/')
