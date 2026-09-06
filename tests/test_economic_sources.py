"""Explicit source frequency, geography, provenance and activation boundaries."""
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile
import pandas as pd
from monitoring import economic_sources as E


def wb(rows, **meta):
    return json.dumps([{'page':1,'pages':1,'total':len(rows),**meta},rows]).encode()


def fixtures():
    countries=[{'id':c,'iso2Code':f'X{i}'} for i,c in enumerate(E.COUNTRIES)]
    definition=[{'id':E.FX_CODE,'name':'Official exchange rate, LCU per USD, period average','source':{'id':'15'}}]
    rates=[{'country':{'id':'ISR','value':'Israel'},'countryiso3code':'','indicator':{'id':E.FX_CODE},'date':m,'value':v}
           for m,v in [('2024M01',3.5),('2025M01',3.8),('2025M02',None)]]
    frame=pd.DataFrame([{'Area Code (M49)':"'376",'Area':'Israel','Item Code':E.FAO_ITEM,'Item':E.FAO_LABEL,
        'Element Code':'6121','Element':'Value','Year':'2021-2023','Unit':'%','Value':'-25.5','Flag':'E','Note':'fixture'}])
    return {'fx':wb(rates,sourceid='15',lastupdated='2025-03-01'),'countries':wb(countries),'fx_definition':wb(definition),
            'food_security':zipped(frame),'fao_catalog':json.dumps({'Datasets':{'Dataset':[{'DatasetCode':'FS','FileLocation':E.FAO_URL,'CompressionFormat':'zip','DateUpdate':'2025-03-01'}]}}).encode()}


def zipped(frame):
    stream=io.BytesIO()
    with zipfile.ZipFile(stream,'w') as archive:archive.writestr(E.FAO_MEMBER,frame.to_csv(index=False))
    return stream.getvalue()


class Client:
    def __init__(self,data=None,fail=None):self.data=data or fixtures();self.fail=fail;self.requests=[]
    def get(self,url):
        key=next(k for k,v in E.urls(2025).items() if v==url)
        if key==self.fail:raise ConnectionError('source failed')
        data=self.data[key];self.requests.append({'url':url,'sha256':E.digest(data),'fetched_at':'2025-03-01'});return data


class EconomicTests(unittest.TestCase):
    def test_monthly_mapping_missing_values_and_negative_three_year_ratio(self):
        tables,meta=E.build_tables(fixtures(),'2025-03-01')
        fx=tables['official_fx_monthly.csv'];grain=tables['cereal_dependence.csv'].iloc[0]
        self.assertEqual(fx.country.tolist(),['ISR']*3);self.assertEqual(fx.usable.tolist(),[True,True,False])
        self.assertTrue(pd.isna(fx.value.iloc[-1]));self.assertEqual(grain.value,-25.5)
        self.assertEqual((grain.period_start,grain.period_end),('2021-01-01','2023-12-31'))
        self.assertEqual(len(tables['coverage.csv']),16)
        future=E.build_tables(fixtures(),'2025-01-15')[0]['official_fx_monthly.csv']
        self.assertFalse(future.query("month == '2025-01'").usable.iloc[0])

    def test_frequency_pagination_mapping_and_indicator_fail_closed(self):
        original=fixtures()
        for change in ['annual','quarter','pages','source','conflict','zero','duplicate']:
            data=copy.deepcopy(original);payload=json.loads(data['fx'])
            if change=='annual':payload[1][0]['date']='2024'
            if change=='quarter':payload[1][0]['date']='2024Q1'
            if change=='pages':payload[0]['pages']=2
            if change=='source':payload[0]['sourceid']='2'
            if change=='conflict':payload[1][0]['countryiso3code']='LBN'
            if change=='zero':payload[1][0]['value']=0
            if change=='duplicate':payload[1].append(payload[1][0]);payload[0]['total']+=1
            data['fx']=json.dumps(payload).encode()
            with self.subTest(change=change),self.assertRaises(ValueError):E.build_tables(data,'2025-03-01')

    def test_cereal_keeps_source_windows_and_definition(self):
        data=fixtures()
        with zipfile.ZipFile(io.BytesIO(data['food_security'])) as archive:original=pd.read_csv(archive.open(E.FAO_MEMBER),dtype=str)
        for key,value in [('Year','2023'),('Item','different definition'),('Unit','tonnes'),('Value','101')]:
            frame=original.copy();frame[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):E.parse_cereal(zipped(frame),'2025-03-01')

    def test_immutable_roundtrip_source_loss_and_corruption_preserve_pointer(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);manifest=E.refresh(root,client=Client(),as_of='2025-03-01');pointer=(root/'manifest.json').read_bytes()
            self.assertEqual(E.load_snapshot(root)[1]['snapshot_id'],manifest['snapshot_id'])
            with self.assertRaises(ConnectionError):E.refresh(root,client=Client(fail='fx'),as_of='2025-03-02')
            data=fixtures();payload=json.loads(data['fx']);payload[1][0]['value']=None;data['fx']=json.dumps(payload).encode()
            with self.assertRaisesRegex(ValueError,'lost observed'):E.refresh(root,client=Client(data),as_of='2025-03-02')
            self.assertEqual((root/'manifest.json').read_bytes(),pointer)
            path=root/manifest['outputs']['coverage.csv']['path'];path.write_text('corrupt')
            with self.assertRaisesRegex(ValueError,'hash mismatch'):E.load_snapshot(root)

    def test_older_source_vintage_cannot_replace_current_values(self):
        for label in ['fx','fao_catalog']:
            with self.subTest(label=label),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);E.refresh(root,client=Client(),as_of='2025-03-01');before=(root/'manifest.json').read_bytes();data=fixtures()
                value=json.loads(data[label])
                if label=='fx':value[0]['lastupdated']='2025-02-01';value[1][0]['value']=7.
                else:value['Datasets']['Dataset'][0]['DateUpdate']='2025-02-01'
                data[label]=json.dumps(value).encode()
                with self.assertRaisesRegex(ValueError,'vintage regressed'):E.refresh(root,client=Client(data),as_of='2025-03-02')
                self.assertEqual((root/'manifest.json').read_bytes(),before)

    def test_manifest_identity_source_metadata_and_revisions_are_bound(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);old=E.refresh(root,client=Client(),as_of='2025-03-01');original=(root/'manifest.json').read_bytes()
            for key in ['snapshot_id','fx_response_metadata','territory_codes','cereal_definition']:
                changed=json.loads(original)
                if key=='snapshot_id':changed[key]='incorrect'
                elif key=='fx_response_metadata':changed[key]['sourceid']='2'
                elif key=='territory_codes':changed[key]['ISR']='422'
                else:changed[key]['item']='different'
                (root/'manifest.json').write_text(json.dumps(changed))
                with self.subTest(key=key),self.assertRaises(ValueError):E.load_snapshot(root)
            (root/'manifest.json').write_bytes(original)
            E.refresh(root,client=Client(),as_of='2025-03-02')
            revisions=list((root/'revisions').glob('*.json'));self.assertEqual(len(revisions),2)
            for revision in revisions:E.load_snapshot(root,manifest_path=revision)
