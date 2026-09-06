"""Versioned official monthly FX and FAOSTAT cereal-dependence context."""
from __future__ import annotations

import datetime as dt
import fcntl
import gzip
import hashlib
import io
import json
from pathlib import Path
import re
import zipfile

import numpy as np
import pandas as pd

from monitoring.feeds import BASE, Client
from source_tracking import write_json_if_changed

ROOT = BASE/'data/economic_sources'
COUNTRIES = ('ISR','PSE','LBN','UKR','SDN','ETH','SOM','YEM')
AREA_CODES = dict(zip(COUNTRIES, ('376','275','422','804','729','231','706','887')))
FX_CODE = 'DPANUSLCU'
FAO_ITEM = '21035'
FAO_LABEL = 'Cereal import dependency ratio (percent) (3-year average)'
FAO_MEMBER = 'Food_Security_Data_E_All_Data_(Normalized).csv'
FX_DEFINITION = 'https://api.worldbank.org/v2/indicator/DPANUSLCU?format=json'
COUNTRY_URL = 'https://api.worldbank.org/v2/country/'+';'.join(COUNTRIES)+'?format=json&per_page=100'
FAO_URL = 'https://bulks-faostat.fao.org/production/Food_Security_Data_E_All_Data_(Normalized).zip'
FAO_CATALOG = 'https://bulks-faostat.fao.org/production/datasets_E.json'
METHOD_URL = 'https://openknowledge.fao.org/3/cc2211en/cc2211en.pdf'
FX_COLUMNS = ['country','source_country_id','source_country_name','month','period_start','period_end',
              'value','unit','indicator','observation_status','decimal','period_complete','usable','source_last_updated']
CEREAL_COLUMNS = ['country','source_area','area_m49','period_start','period_end','start_year','end_year',
                 'value','unit','item_code','item','element_code','flag','note','period_complete','usable']


def digest(data):
    return hashlib.sha256(data).hexdigest()


def cutoff(value=None):
    value = value if value is not None else dt.datetime.now(dt.timezone.utc)
    stamp = pd.Timestamp(value)
    if pd.isna(stamp): raise ValueError('Invalid economic-source cutoff')
    if isinstance(value, dt.date) and not isinstance(value, dt.datetime) or isinstance(value,str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}',value):
        stamp += pd.Timedelta(days=1)
    return stamp.tz_convert('UTC').tz_localize(None) if stamp.tzinfo else stamp


def urls(year):
    return {'fx_definition':FX_DEFINITION,'countries':COUNTRY_URL,'food_security':FAO_URL,'fao_catalog':FAO_CATALOG,
            'fx':'https://api.worldbank.org/v2/country/'+';'.join(COUNTRIES)+f'/indicator/{FX_CODE}?source=15&date=2015M01:{year}M12&format=json&per_page=20000&gapfill=N'}


def worldbank_rows(payload, label, source=None):
    data = json.loads(payload)
    if not isinstance(data,list) or len(data)!=2 or not isinstance(data[0],dict) or not isinstance(data[1],list):
        raise ValueError(f'{label}: invalid World Bank response')
    meta,rows=data
    if int(meta.get('page',0))!=1 or int(meta.get('pages',0))!=1 or int(meta.get('total',-1))!=len(rows):
        raise ValueError(f'{label}: incomplete World Bank pagination')
    if source is not None and str(meta.get('sourceid'))!=source:
        raise ValueError(f'{label}: source changed')
    return meta,rows


def parse_fx(payload, country_payload, definition_payload, as_of):
    _, definitions = worldbank_rows(definition_payload,'FX definition')
    if (len(definitions)!=1 or definitions[0].get('id')!=FX_CODE
        or str(definitions[0].get('source',{}).get('id'))!='15'
        or definitions[0].get('name')!='Official exchange rate, LCU per USD, period average'):
        raise ValueError('Official FX definition changed; review before extending history')
    _, records = worldbank_rows(country_payload,'Country mapping')
    if {r.get('id') for r in records}!=set(COUNTRIES):
        raise ValueError('Incomplete fixed-country mapping')
    codes={}
    for record in records:
        iso3=record['id'];iso2=record['iso2Code']
        for code in [iso2,iso3]:
            if code in codes: raise ValueError('Duplicate country mapping')
            codes[code]=iso3
    meta, records=worldbank_rows(payload,'Monthly FX',source='15')
    if not meta.get('lastupdated') or pd.isna(pd.Timestamp(meta['lastupdated'])):raise ValueError('Missing FX source vintage')
    bound=cutoff(as_of);rows=[]
    for record in records:
        source_id=record.get('country',{}).get('id')
        country=codes.get(source_id)
        if not country: raise ValueError('Unrecognized FX source-country code')
        if record.get('countryiso3code') not in ('',None,country):
            raise ValueError('Conflicting FX country identifiers')
        if record.get('indicator',{}).get('id')!=FX_CODE:
            raise ValueError('Unexpected FX indicator')
        match=re.fullmatch(r'(\d{4})M(0[1-9]|1[0-2])',str(record.get('date','')))
        if not match: raise ValueError('FX period must be explicitly monthly; annual values cannot be expanded')
        year,month=map(int,match.groups());start=pd.Timestamp(year=year,month=month,day=1);end=start+pd.offsets.MonthEnd(0)
        if year<2015 or year>bound.year: raise ValueError('FX response escaped declared date scope')
        value=np.nan if record.get('value') is None else float(record['value'])
        if pd.notna(value) and (not np.isfinite(value) or value<=0): raise ValueError('FX rate must be positive or missing')
        complete=end+pd.Timedelta(days=1)<=bound
        rows.append(dict(country=country,source_country_id=source_id,source_country_name=record['country']['value'],
            month=f'{year:04}-{month:02}',period_start=str(start.date()),period_end=str(end.date()),value=value,
            unit='official LCU per USD',indicator=FX_CODE,observation_status=record.get('obs_status',''),
            decimal=record.get('decimal'),period_complete=complete,usable=bool(complete and pd.notna(value)),
            source_last_updated=meta.get('lastupdated')))
    frame=pd.DataFrame(rows,columns=FX_COLUMNS)
    if frame.empty or frame.duplicated(['country','month']).any(): raise ValueError('Empty or duplicated FX snapshot')
    return frame.sort_values(['country','month']).reset_index(drop=True),definitions[0],meta


def parse_cereal(payload, as_of):
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        if archive.namelist().count(FAO_MEMBER)!=1: raise ValueError('FAOSTAT bulk member changed')
        data=pd.read_csv(archive.open(FAO_MEMBER),dtype=str,keep_default_na=False)
    required={'Area Code (M49)','Area','Item Code','Item','Element Code','Element','Year','Unit','Value','Flag','Note'}
    if not required<=set(data):raise ValueError('FAOSTAT food-security schema changed')
    selected=data[data['Item Code'].eq(FAO_ITEM)].copy()
    if selected.empty or not selected.Item.eq(FAO_LABEL).all(): raise ValueError('Cereal-dependence definition changed')
    selected['m49']=selected['Area Code (M49)'].str.strip("' ").str.zfill(3)
    countries={m49:country for country,m49 in AREA_CODES.items()}
    selected=selected[selected.m49.isin(countries)]
    bound=cutoff(as_of);rows=[]
    for _,record in selected.iterrows():
        if record['Element Code']!='6121' or record.Element!='Value' or record.Unit!='%':
            raise ValueError('Cereal-dependence unit or element changed')
        period=re.fullmatch(r'(\d{4})-(\d{4})',record.Year)
        if not period or int(period[2])-int(period[1])!=2:raise ValueError('Cereal ratio must retain full three-year window')
        first,last=map(int,period.groups())
        value=np.nan if not record.Value.strip() else float(record.Value)
        if pd.notna(value) and (not np.isfinite(value) or value>100):raise ValueError('Invalid cereal ratio; negative net-exporter values are retained')
        complete=pd.Timestamp(year=last+1,month=1,day=1)<=bound
        rows.append(dict(country=countries[record.m49],source_area=record.Area,area_m49=record.m49,
            period_start=f'{first}-01-01',period_end=f'{last}-12-31',start_year=first,end_year=last,value=value,
            unit='percent; three-year average',item_code=FAO_ITEM,item=record.Item,element_code='6121',
            flag=record.Flag,note=record.Note,period_complete=complete,usable=bool(complete and pd.notna(value))))
    result=pd.DataFrame(rows,columns=CEREAL_COLUMNS)
    if result.empty or result.duplicated(['country','period_start','period_end']).any():raise ValueError('Empty or duplicate cereal-dependence records')
    return result.sort_values(['country','period_end']).reset_index(drop=True)


def build_tables(payloads, as_of=None):
    bound=cutoff(as_of)
    fx,definition,metadata=parse_fx(payloads['fx'],payloads['countries'],payloads['fx_definition'],bound)
    cereal=parse_cereal(payloads['food_security'],bound)
    catalog=json.loads(payloads['fao_catalog'])
    try:
        entries=[x for x in catalog['Datasets']['Dataset'] if x['DatasetCode']=='FS']
        if len(entries)!=1 or entries[0]['FileLocation']!=FAO_URL or entries[0]['CompressionFormat']!='zip':
            raise ValueError('FAOSTAT food-security catalog binding changed')
        if pd.isna(pd.Timestamp(entries[0]['DateUpdate'])):raise ValueError('Missing FAOSTAT version date')
    except (KeyError,TypeError) as error:
        raise ValueError('FAOSTAT bulk catalog schema changed') from error
    coverage=[]
    for country in COUNTRIES:
        for source,frame in [('official_fx',fx),('cereal_dependence',cereal)]:
            observed=frame[frame.country.eq(country)&frame.usable]
            coverage.append(dict(country=country,source=source,usable_rows=len(observed),
                observed_start=observed.period_start.min() if len(observed) else '',
                observed_end=observed.period_end.max() if len(observed) else '',
                status='observed source periods' if len(observed) else 'unavailable from selected source'))
    tables={'official_fx_monthly.csv':fx,'cereal_dependence.csv':cereal,'coverage.csv':pd.DataFrame(coverage)}
    return tables,{'fx_definition':definition,'fx_response_metadata':metadata,'fao_catalog_entry':entries[0]}


def load_snapshot(root=ROOT, *, manifest_path=None):
    root=Path(root);manifest=json.loads(Path(manifest_path or root/'manifest.json').read_text())
    if manifest.get('schema_version')!=1 or manifest.get('method_version')!='official_fx_fao_cereal_v1':raise ValueError('Economic source contract changed')
    if set(manifest.get('inputs',{}))!=set(urls(2026)):raise ValueError('Incomplete economic source archive')
    expected_urls=urls(cutoff(manifest['as_of_utc']).year)
    payloads={}
    for key,record in manifest['inputs'].items():
        if record['source_url']!=expected_urls[key]:raise ValueError('Economic source URL changed')
        path=root/record['path']
        if not path.resolve().is_relative_to(root.resolve()):raise ValueError('Economic raw source path escaped root')
        payloads[key]=gzip.decompress(path.read_bytes())
        if digest(payloads[key])!=record['sha256']:
            raise ValueError('Economic raw source hash mismatch')
    tables={};contents={}
    for name,record in manifest['outputs'].items():
        path=root/record['path']
        if not path.resolve().is_relative_to(root.resolve()) or digest(path.read_bytes())!=record['sha256']:raise ValueError('Economic output hash mismatch')
        tables[name]=pd.read_csv(path)
        contents[name]=path.read_bytes()
        if len(tables[name])!=record['rows']:raise ValueError('Economic output count mismatch')
    if set(tables)!={'official_fx_monthly.csv','cereal_dependence.csv','coverage.csv'}:raise ValueError('Incomplete economic output snapshot')
    if digest(b''.join(name.encode()+contents[name] for name in sorted(contents)))!=manifest['snapshot_id']:
        raise ValueError('Economic snapshot identity mismatch')
    replay,metadata=build_tables(payloads,manifest['as_of_utc'])
    for name,frame in replay.items():
        if frame.to_csv(index=False).encode()!=contents[name]:raise ValueError('Economic archived source replay mismatch')
    for key in ['fx_definition','fx_response_metadata','fao_catalog_entry']:
        if manifest[key]!=metadata[key]:raise ValueError('Economic metadata differs from archived source')
    if manifest['territory_codes']!=AREA_CODES:raise ValueError('Economic territory mapping changed')
    if manifest['cereal_definition']!={'item':FAO_LABEL,'item_code':FAO_ITEM,
        'formula':'100*(imports-exports)/(production+imports-exports), three-year average','method_source':METHOD_URL}:
        raise ValueError('Economic cereal definition changed')
    return tables,manifest


def refresh(root=ROOT, *, offline=False, client=None, as_of=None):
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    with (root/'.activation.lock').open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:raise ValueError('Another economic-source refresh is running') from error
        return _refresh(root,offline=offline,client=client,as_of=as_of)


def _refresh(root=ROOT, *, offline=False, client=None, as_of=None):
    root=Path(root);bound=cutoff(as_of)
    client=client or Client(cache=BASE/'.cache/economic_sources',offline=offline)
    locations=urls(bound.year);payloads={name:client.get(url) for name,url in locations.items()}
    for name,data in payloads.items():
        evidence=[r for r in client.requests if r['url']==locations[name]]
        if not evidence or evidence[-1]['sha256']!=digest(data):raise ValueError('Economic cache/request hash mismatch')
    tables,metadata=build_tables(payloads,bound)
    if (root/'manifest.json').exists():
        previous,old=load_snapshot(root)
        if bound<cutoff(old['as_of_utc']):raise ValueError('Economic activation cutoff regressed')
        for label,current,prior in [('FX',metadata['fx_response_metadata']['lastupdated'],old['fx_response_metadata']['lastupdated']),
                                    ('FAOSTAT',metadata['fao_catalog_entry']['DateUpdate'],old['fao_catalog_entry']['DateUpdate'])]:
            if pd.isna(pd.Timestamp(current)) or pd.Timestamp(current)<pd.Timestamp(prior):
                raise ValueError(f'{label} source vintage regressed; review before activation')
        for name,keys in [('official_fx_monthly.csv',['country','month']),('cereal_dependence.csv',['country','period_start','period_end'])]:
            observed=lambda d:set(map(tuple,d.loc[d.value.notna(),keys].to_numpy()))
            if not observed(previous[name])<=observed(tables[name]):raise ValueError('Economic source lost observed history; review before activation')
    contents={name:table.to_csv(index=False).encode() for name,table in tables.items()}
    identity=digest(b''.join(name.encode()+contents[name] for name in sorted(contents)))
    inputs,outputs={},{}
    def immutable(path,content):
        path.parent.mkdir(parents=True,exist_ok=True)
        if path.exists() and path.read_bytes()!=content:raise ValueError('Immutable economic snapshot conflict')
        if not path.exists():path.write_bytes(content)
    for name,data in payloads.items():
        relative=f'raw/{name}/{digest(data)}.gz';immutable(root/relative,gzip.compress(data,mtime=0))
        inputs[name]={'path':relative,'sha256':digest(data),'source_url':locations[name]}
    for name,data in contents.items():
        relative=f'snapshots/{identity}/{name}';immutable(root/relative,data)
        outputs[name]={'path':relative,'sha256':digest(data),'rows':len(tables[name])}
    manifest={'schema_version':1,'method_version':'official_fx_fao_cereal_v1','as_of_utc':bound.isoformat(),
        'snapshot_id':identity,'inputs':inputs,'outputs':outputs,'requests':client.requests,
        'fx_definition':metadata['fx_definition'],'fx_response_metadata':metadata['fx_response_metadata'],
        'fao_catalog_entry':metadata['fao_catalog_entry'],
        'cereal_definition':{'item':FAO_LABEL,'item_code':FAO_ITEM,'formula':'100*(imports-exports)/(production+imports-exports), three-year average','method_source':METHOD_URL},
        'territory_codes':AREA_CODES,'limitations':['Official FX does not necessarily represent retail or parallel-market exchange rates. Country/food currency compatibility is separately gated.',
          'Published monthly FX only; unavailable months never inherit annual or neighboring values.',
          'Cereal dependence retains three-year windows, negative values and source flags; it is not monthly grain traffic.',
          'Source snapshots may revise historical estimates. These cutoffs do not reconstruct release-time information.']}
    encode=lambda value:(json.dumps(value,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()
    if (root/'manifest.json').exists():
        old_content=encode(old);immutable(root/f'revisions/{digest(old_content)}.json',old_content)
    new_content=encode(manifest);saved=root/f'revisions/{digest(new_content)}.json';immutable(saved,new_content)
    load_snapshot(root,manifest_path=saved)
    write_json_if_changed(root/'manifest.json',manifest)
    return manifest


def main():
    import argparse
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--offline',action='store_true');parser.add_argument('--output',type=Path,default=ROOT)
    args=parser.parse_args();result=refresh(args.output,offline=args.offline)
    print(json.dumps({'snapshot_id':result['snapshot_id'],'outputs':result['outputs'],'fx_last_updated':result['fx_response_metadata'].get('lastupdated')},indent=2))


if __name__=='__main__':main()
