"""Public-source adapters. Full pagination, explicit units, no imputed zeros."""
from __future__ import annotations

import datetime as dt
import hashlib
import gzip
import io
import json
import re
import zipfile
from pathlib import Path
from urllib.parse import urlparse

import numpy as np
import pandas as pd
import requests

from source_tracking import write_json_if_changed

BASE = Path(__file__).resolve().parents[1]
CONFIG = json.loads((Path(__file__).with_name('config.json')).read_text())
COLUMNS = ['country','period_start','period_end','metric','value','unit','numerator','denominator',
           'frequency','source_id','source_version','source_url','published_at','fetched_at',
           'provisional','dimensions','quality_note']
COUNTRY_NAMES = {'Israel':'ISR','Palestine':'PSE','Lebanon':'LBN','Ukraine':'UKR',
                 'Sudan':'SDN','Ethiopia':'ETH','Somalia':'SOM','Yemen':'YEM','Yemen (North Yemen)':'YEM'}
WFP_PACKAGES = {'PSE':'state-of-palestine','LBN':'lebanon','UKR':'ukraine',
                'SDN':'sudan','ETH':'ethiopia','SOM':'somalia','YEM':'yemen'}


class Client:
    def __init__(self, cache: Path | None = None, offline=False):
        self.cache = Path(cache or BASE / '.cache/monitoring')
        self.cache.mkdir(parents=True, exist_ok=True)
        self.offline = offline
        self.session = requests.Session()
        self.session.headers['User-Agent'] = 'Biblejustin-correlations/2.0 (public research data)'
        self.requests = []

    def get(self, url: str, params: dict | None = None) -> bytes:
        prepared = requests.Request('GET', url, params=params).prepare().url
        key = hashlib.sha256(prepared.encode()).hexdigest()
        target = self.cache / key
        meta_path = target.with_suffix('.json')
        if self.offline:
            if not target.exists() or not meta_path.exists():
                raise FileNotFoundError(f'No cached response: {prepared}')
            meta = json.loads(meta_path.read_text())
        else:
            response = self.session.get(prepared, timeout=(15, 90))
            response.raise_for_status()
            payload = response.content
            if not payload:
                raise ValueError(f'Empty response: {prepared}')
            temp = target.with_suffix('.tmp'); temp.write_bytes(payload); temp.replace(target)
            meta = {'url': prepared, 'fetched_at': dt.datetime.now(dt.timezone.utc).isoformat(),
                    'sha256': hashlib.sha256(payload).hexdigest(),
                    'published_at': response.headers.get('Last-Modified')}
            write_json_if_changed(meta_path,meta)
        self.requests.append(meta)
        return target.read_bytes()

    def json(self,url,params=None):
        return json.loads(self.get(url,params))


def number(value):
    try:
        v=float(value)
        return v if np.isfinite(v) else None
    except (ValueError,TypeError):
        return None


def obs(country,start,end,metric,value,unit,source,url,version='',frequency='annual',
        numerator=None,denominator=None,dimensions=None,quality_note='',published_at=None,
        provisional=False):
    value=number(value)
    if value is None:
        return None
    return dict(country=country,period_start=str(start),period_end=str(end),metric=metric,
                value=value,unit=unit,numerator=number(numerator),denominator=number(denominator),
                frequency=frequency,source_id=source,source_version=str(version),source_url=url,
                published_at=published_at,fetched_at=None,provisional=provisional,
                dimensions=json.dumps(dimensions or {},sort_keys=True),quality_note=quality_note)


def frame(rows):
    return pd.DataFrame([r for r in rows if r is not None],columns=COLUMNS)


def csv_zip(payload, usecols=None):
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        names=[n for n in archive.namelist() if n.lower().endswith('.csv') and not n.startswith('__MACOSX/')]
        if len(names)!=1:
            raise ValueError(f'Expected one data CSV; found {names}')
        return pd.read_csv(archive.open(names[0]),usecols=usecols,low_memory=False)


def ucdp(client,countries,start_year):
    url='https://ucdp.uu.se/downloads/organizedviolencecy/organizedviolencecy-261-csv.zip'
    d=csv_zip(client.get(url));rows=[]
    metrics={'sb_total_deaths_best':'conflict_battle_deaths',
             'ns_total_deaths_best':'conflict_nonstate_deaths',
             'os_total_deaths_best':'conflict_civilian_targeting_deaths',
             'cumulative_total_deaths_in_orgvio_best':'conflict_total_deaths'}
    for _,r in d.iterrows():
        country=COUNTRY_NAMES.get(r['country'])
        if country not in countries or r['year']<start_year:continue
        year=int(r['year'])
        for field,metric in metrics.items():
            rows.append(obs(country,f'{year}-01-01',f'{year}-12-31',metric,r[field],'deaths',
                            'ucdp',url,'26.1',dimensions={'source_country_name':r['country'],'source_country_id':int(r['country_id']),
                              'population_denominator_compatible':country!='ISR' and (country!='SDN' or year>=2012),
                              'geographic_scope':('UCDP Israel country unit includes Palestinian territories; not Israeli-nationality deaths' if country=='ISR' else 'Sudan source borders before South Sudan independence' if country=='SDN' and year<=2011 else 'UCDP source-country territory')},
                            quality_note='UCDP territory-coded best estimate; not intensity-band floor. Israel/Palestine source unit and pre-2012 Sudan are excluded from unmatched WDI population rates.'))
    return frame(rows)


def unhcr(client,countries,start_year):
    url='https://api.unhcr.org/population/v1/population/'
    params={'yearFrom':start_year,'yearTo':dt.date.today().year-1,
            'coo_all':'true','page':1,'limit':1000}
    rows=[];seen=set()
    while True:
        data=client.json(url,params)
        if 'items' not in data or 'maxPages' not in data:raise ValueError('UNHCR pagination schema changed')
        for r in data['items']:
            country=r.get('coo_iso')
            if country not in countries:continue
            year=int(r['year'])
            if r.get('coa_iso')!='-':raise ValueError('Expected worldwide destination aggregate, not bilateral rows')
            for field,metric in [('refugees','refugees_origin_stock'),('asylum_seekers','asylum_seekers_origin_stock'),
                                 ('returned_refugees','returned_refugees_flow')]:
                key=(country,year,metric)
                if key in seen:raise ValueError('Duplicate UNHCR country/year')
                seen.add(key)
                rows.append(obs(country,f'{year}-01-01',f'{year}-12-31',metric,r.get(field),'people',
                                'unhcr',url,'live annual',quality_note='Origin-country aggregate. Stocks are not new displacement flows; dash remains missing.'))
        if params['page']>=int(data['maxPages']):break
        params['page']+=1
        if params['page']>100:raise ValueError('UNHCR pagination exceeded expected bound')
    return frame(rows)


def hdx_resource(client,package,filename_part):
    meta=client.json('https://data.humdata.org/api/3/action/package_show',{'id':package})
    if not meta.get('success'):raise ValueError(f'HDX package unavailable: {package}')
    resources=[r for r in meta['result']['resources'] if filename_part in r.get('url','')]
    if len(resources)!=1:raise ValueError(f'Ambiguous HDX resource for {package}: {filename_part}')
    resource=resources[0]
    d=pd.read_csv(io.BytesIO(client.get(resource['url'])),low_memory=False)
    # Some HDX CSVs insert an HXL tag row directly below their human-readable header.
    if not d.empty and str(d.iloc[0,0]).startswith('#'):d=d.iloc[1:].copy()
    return d,resource['url'],resource.get('last_modified') or meta['result'].get('metadata_modified')


def ipc(client,countries,start_year):
    d,url,published=hdx_resource(client,'global-acute-food-insecurity-country-data','ipc_global_national_long_latest.csv')
    required={'Country','From','To','Phase','Percentage','Number','Validity period','Date of analysis'}
    if not required<=set(d):raise ValueError('IPC CSV schema changed')
    assessment_keys=['Country','Date of analysis','Validity period','From','To']
    totals=d[d.Phase.astype(str).str.lower().eq('all')].copy()
    if totals.duplicated(assessment_keys).any():raise ValueError('Duplicate IPC assessment population totals')
    denominators=totals.set_index(assessment_keys)['Number']
    rows=[]
    for _,r in d.iterrows():
        if r['Country'] not in countries or str(r['From'])[:4]<str(start_year):continue
        phase=str(r['Phase'])
        if phase not in {'3+','3','4','5'}:continue
        value=number(r['Percentage'])
        if value is not None and not 0<=value<=1:raise ValueError('IPC fraction out of range')
        rows.append(obs(r['Country'],r['From'],r['To'],'ipc_phase_'+phase.replace('+','plus')+'_fraction',
                        value,'fraction_of_population_analyzed','ipc',url,'latest assessment',frequency='assessment',
                        numerator=r['Number'],denominator=denominators.get(tuple(r[k] for k in assessment_keys)),
                        dimensions={'assessment':r['Date of analysis'],'type':r['Validity period'],
                                    'source_total_country_population':number(r.get('Total country population')),
                                    'geographic_scope':'IPC population analyzed; territorial coverage not specified in national export',
                                    'geography_comparable_to_country':False},
                        published_at=published,provisional=str(r['Validity period']).lower()!='current',
                        quality_note='Fraction uses phase-all analyzed population, not total country population. Source percentages rounded. Territorial scope not certified; excluded from cross-source country lag tests. Assessment windows and projections kept separate.'))
    return frame(rows)


def normalize_idmc(d,country,url,published=None):
    """Keep the publisher's annual flow distinct from stocks and disaster event rows."""
    required={'iso3','country_name','year','new_displacement','total_displacement'}
    if not required<=set(d):raise ValueError('IDMC annual CSV schema changed')
    if 'event_name' in d:raise ValueError('IDMC event export cannot substitute for annual series')
    years=pd.to_numeric(d.year,errors='coerce')
    if years.isna().any() or (years%1!=0).any():raise ValueError('Invalid IDMC year')
    if not d.iso3.eq(country).all():raise ValueError('IDMC country mismatch')
    if d.duplicated(['iso3','year']).any():raise ValueError('Duplicate IDMC country/year')
    for field in ['new_displacement','total_displacement']:
        parsed=pd.to_numeric(d[field],errors='coerce')
        if (d[field].notna() & ~np.isfinite(parsed)).any():raise ValueError('Invalid IDMC displacement count')
    rows=[]
    for _,r in d.iterrows():
        year=int(r.year)
        for field,metric,unit in [('new_displacement','internal_displacements_flow','displacement movements'),
                                  ('total_displacement','internally_displaced_year_end_stock','people')]:
            value=number(r[field])
            if value is not None and value<0:raise ValueError('Negative IDMC displacement count')
            rows.append(obs(country,f'{year}-01-01',f'{year}-12-31',metric,value,unit,'idmc',url,
                'GIDD annual HDX export',published_at=published,
                dimensions={'source_country_name':r.country_name,'geographic_scope':'IDMC source-country territory',
                    'population_denominator_compatible':False,
                    'cause_scope':'Annual IDPs export; separate disaster-event export not aggregated or added'},
                quality_note='New displacements count movements, including repeated movements by one person. Year-end stock counts people. Annual export and separate disaster-event export are not interchangeable. Geography/cause comparability not certified for cross-source inference. Missing years/counts remain missing.'))
    return frame(rows)


def idmc(client,countries,start_year):
    parts=[]
    for country in countries:
        package=f'idmc-idp-data-{country.lower()}'
        d,url,published=hdx_resource(client,package,f'internal-displacements-new-displacements-idps_{country.lower()}.csv')
        normalized=normalize_idmc(d,country,url,published)
        parts.append(normalized[normalized.period_start.str[:4].astype(int)>=start_year])
    return pd.concat(parts,ignore_index=True)


def is_food_commodity(name):
    label=str(name).lower()
    return any(word in label for word in ['wheat','barley','maize','rice','sorghum','oil']) and not any(word in label for word in ['wage','milling cost','processing cost','transport cost'])


def kg_unit(unit):
    match=re.fullmatch(r'\s*(\d+(?:\.\d+)?)?\s*KG\s*',str(unit).upper())
    return float(match.group(1) or 1) if match else None


def normalize_wfp(d,country,url,published=None):
    required={'date','market_id','commodity','commodity_id','unit','priceflag','pricetype','currency','price'}
    if not required<=set(d):raise ValueError('WFP CSV schema changed')
    d=d[d.priceflag.str.lower().eq('actual')].copy()
    d['price']=pd.to_numeric(d.price,errors='coerce')
    d=d[d.price>0]
    rows=[]
    for _,r in d.iterrows():
        # Preserve distinct markets, commodities, units and retail/wholesale series.
        dims={k:str(r[k]) for k in ['market_id','commodity','commodity_id','unit','pricetype','currency']}
        day=pd.Timestamp(r['date']);end=(day+pd.offsets.MonthEnd(0)).date().isoformat()
        rows.append(obs(country,day.replace(day=1).date().isoformat(),end,('labor_wage' if 'wage' in str(r.commodity).lower() else 'food_price' if is_food_commodity(r.commodity) else 'food_processing_cost'),r.price,
                        f'{r.currency}/{r.unit}','wfp',url,'HDX current export',frequency='monthly',
                        dimensions=dims,published_at=published,
                        quality_note='Actual market quotes only; distinct baskets/markets/currencies are not interchangeable.'))
    # Food quantity per day's non-qualified labor wage, exact country/market/month/currency match.
    d['month']=pd.to_datetime(d.date).dt.to_period('M').astype(str)
    wages=d[d.commodity.str.contains(r'Wage.*non-qualified',case=False,regex=True,na=False)
            & d.unit.str.upper().str.strip().isin(['DAY','1 DAY'])]
    wage_keys=['market_id','month','currency']
    wage=wages.groupby(wage_keys).price.median()
    staples=d[d.pricetype.str.lower().eq('retail') & d.commodity.map(is_food_commodity) & d.commodity.str.contains(r'wheat|barley|maize|rice|sorghum',case=False,na=False)]
    for _,r in staples.iterrows():
        unitkg=kg_unit(r.unit);key=(r.market_id,r.month,r.currency)
        if not unitkg or key not in wage.index:continue
        day=pd.Timestamp(r.date);pricekg=r.price/unitkg
        rows.append(obs(country,day.replace(day=1).date().isoformat(),(day+pd.offsets.MonthEnd(0)).date().isoformat(),
                        'staple_kg_per_daily_wage',wage.loc[key]/pricekg,'kg/day_wage','wfp',url,
                        'matched actual market-month',frequency='monthly',numerator=wage.loc[key],denominator=pricekg,
                        dimensions={'market_id':str(r.market_id),'commodity':r.commodity,
                                    'commodity_id':str(r.commodity_id),'currency':r.currency},published_at=published,
                        quality_note='Local non-qualified labor wage divided by retail staple price/kg; unavailable without matched wages.'))
    return frame(rows)


def wfp(client,countries,start_year):
    frames=[]
    for country in countries:
        if country not in WFP_PACKAGES:continue
        d,url,published=hdx_resource(client,'wfp-food-prices-for-'+WFP_PACKAGES[country],f'wfp_food_prices_{country.lower()}.csv')
        d=d[pd.to_datetime(d.date,errors='coerce').dt.year>=start_year]
        # Retain staples, cooking oil and labor wages. Monitoring is not a global CPI.
        d=d[d.commodity.str.contains('wheat|barley|maize|rice|sorghum|oil|wage',case=False,na=False)]
        frames.append(normalize_wfp(d,country,url,published))
    return pd.concat(frames,ignore_index=True) if frames else frame([])


def normalize_who(d,url):
    rows=[]
    for _,r in d.iterrows():
        tested=number(r.get('SPEC_PROCESSED_NB'));positive=number(r.get('INF_ALL'))
        if positive is None:
            a,b=number(r.get('INF_A')),number(r.get('INF_B'))
            if a is not None and b is not None:positive=a+b
        if tested is None or tested<20 or positive is None or not 0<=positive<=tested:continue
        day=pd.Timestamp(r.ISO_WEEKSTARTDATE)
        rows.append(obs(r.COUNTRY_CODE,day.date().isoformat(),(day+pd.Timedelta(days=6)).date().isoformat(),
                        'influenza_positivity',positive/tested,'positive_fraction','who',url,'FluNet live',
                        frequency='weekly',numerator=positive,denominator=tested,
                        dimensions={'surveillance_origin':str(r.ORIGIN_SOURCE)},provisional=True,
                        quality_note='At least 20 specimens; surveillance origins kept separate. Not population infection prevalence.'))
    return frame(rows)


def who(client,countries,start_year):
    url='https://xmart-api-public.who.int/FLUMART/VIW_FNT';parts=[]
    for country in countries:
        params={'$filter':f"COUNTRY_CODE eq '{country}' and ISO_YEAR ge {start_year}",'$format':'json',
                '$select':'COUNTRY_CODE,ISO_WEEKSTARTDATE,ISO_YEAR,ORIGIN_SOURCE,SPEC_PROCESSED_NB,INF_ALL,INF_A,INF_B',
                '$top':10000,'$skip':0}
        while True:
            j=client.json(url,params)
            if 'value' not in j:raise ValueError('WHO OData response missing value')
            values=j['value']
            if values:parts.append(pd.DataFrame(values))
            next_url=j.get('@odata.nextLink')
            if next_url:
                # Follow official pagination, validating origin to avoid unexpected redirects.
                if urlparse(next_url).netloc != urlparse(url).netloc:raise ValueError('WHO pagination origin changed')
                raise ValueError('WHO supplied nextLink; update adapter before publishing incomplete data')
            if len(values)<params['$top']:break
            params['$skip']+=params['$top']
            if params['$skip']>100000:raise ValueError('Unexpected WHO pagination size')
    return normalize_who(pd.concat(parts,ignore_index=True),url) if parts else frame([])


def religion(client,countries,start_year):
    url='https://www.v-dem.net/media/datasets/V-Dem-CY-Core-v16_csv.zip'
    cols=['country_name','country_text_id','year','v2clrelig','v2clrelig_codelow','v2clrelig_codehigh']
    d=csv_zip(client.get(url),usecols=cols);rows=[]
    for _,r in d.iterrows():
        # V-Dem Gaza/West Bank units are not collapsed into an invented PSE mean.
        if r.country_text_id not in countries or r.year<start_year:continue
        year=int(r.year)
        rows.append(obs(r.country_text_id,f'{year}-01-01',f'{year}-12-31','religious_freedom',
                        r.v2clrelig,'V-Dem latent interval score','vdem',url,'16',
                        dimensions={'source_country_name':r.country_name,'interval_low':number(r.v2clrelig_codelow),'interval_high':number(r.v2clrelig_codehigh)},
                        quality_note='Expert-coded freedom of religion; higher = more freedom. Not incident count. PSE unit is West Bank, not combined Palestinian territories.'))
    return frame(rows)


def population(client,countries,start_year):
    url=f'https://api.worldbank.org/v2/country/{";".join(countries)}/indicator/SP.POP.TOTL'
    params={'format':'json','date':f'{start_year}:{dt.date.today().year-1}','per_page':1000,'page':1}
    rows=[]
    while True:
        j=client.json(url,params)
        if not isinstance(j,list) or len(j)!=2:raise ValueError('World Bank schema changed')
        for r in j[1] or []:
            year=int(r['date'])
            rows.append(obs(r['countryiso3code'],f'{year}-01-01',f'{year}-12-31','population',r['value'],'people',
                            'worldbank',url,'WDI live',published_at=j[0].get('lastupdated')))
        if params['page']>=int(j[0]['pages']):break
        params['page']+=1
    return frame(rows)


ADAPTERS={'ucdp':ucdp,'unhcr':unhcr,'ipc':ipc,'wfp':wfp,'who':who,'religion':religion,'population':population,'idmc':idmc}


def validate_observations(d):
    if list(d.columns)!=COLUMNS:raise ValueError('Observation schema mismatch')
    if d.empty:raise ValueError('No usable observations; keeping previous snapshot')
    if not np.isfinite(d.value.to_numpy(dtype=float)).all():raise ValueError('Nonfinite observed values')
    starts,ends=pd.to_datetime(d.period_start),pd.to_datetime(d.period_end)
    if starts.isna().any() or ends.isna().any():raise ValueError('Missing observation date')
    if (ends<starts).any():raise ValueError('Reversed observation interval')
    if not d.country.astype(str).str.fullmatch('[A-Z]{3}').all():raise ValueError('Invalid country identifier')
    if d.unit.isna().any() or d.unit.astype(str).str.strip().eq('').any():raise ValueError('Missing observation unit')
    for encoded in d.dimensions:
        if not isinstance(json.loads(encoded),dict):raise ValueError('Observation dimensions must be JSON object')
    ratios=d[d.metric.eq('influenza_positivity')]
    if not ratios.empty and (ratios.denominator.isna().any() or ratios.denominator.le(0).any() or not np.allclose(ratios.value,ratios.numerator/ratios.denominator)):
        raise ValueError('Inconsistent influenza positivity denominator')
    ipc_rows=d[d.metric.str.startswith('ipc_phase_')]
    if not ipc_rows.empty and (ipc_rows.denominator.isna().any() or ipc_rows.denominator.le(0).any() or not np.allclose(ipc_rows.value,ipc_rows.numerator/ipc_rows.denominator,atol=.015,rtol=0)):
        raise ValueError('IPC denominator must be population analyzed (rounding tolerance 1.5 percentage points)')
    keys=['country','period_start','period_end','metric','unit','dimensions']
    if d.duplicated(keys).any():
        # Exact duplicate input rows can be repeated upstream; conflicting observations are refused.
        groups=d.groupby(keys,dropna=False)[['value','numerator','denominator']].nunique(dropna=False)
        if (groups>1).any().any():raise ValueError('Conflicting duplicate observations')
        d=d.drop_duplicates(keys)
    return d.sort_values(keys).reset_index(drop=True)


def refresh(name,output=BASE/'data/monitoring',offline=False,config=CONFIG):
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    client=Client(offline=offline)
    d=ADAPTERS[name](client,config['countries'],config['start_year'])
    d=validate_observations(d)
    stamp=max(m['fetched_at'] for m in client.requests)
    d['fetched_at']=stamp
    target=output/(f'{name}.csv.gz' if name in {'wfp','who'} else f'{name}.csv')
    # A failed/truncated full refresh must not silently replace a good observation history.
    if target.exists():
        old=pd.read_csv(target)
        if name!='ipc' and len(d)<0.9*len(old):raise ValueError(f'{name}: suspicious shrink {len(old)} -> {len(d)}')
        if name=='ipc':
            # Public endpoint exposes latest assessments; preserve older fetched snapshots.
            d=pd.concat([old,d],ignore_index=True)
            d['_assessment']=d.dimensions.map(lambda x:json.loads(x).get('assessment'))
            d['_type']=d.dimensions.map(lambda x:json.loads(x).get('type'))
            d=d.drop_duplicates(['country','period_start','period_end','metric','_assessment','_type'],keep='last').drop(columns=['_assessment','_type'])
            d=validate_observations(d)
    text=d.to_csv(index=False).encode()
    payload=gzip.compress(text,mtime=0) if target.suffix=='.gz' else text
    if not target.exists() or target.read_bytes()!=payload:
        temp=target.with_name(target.name+'.tmp');temp.write_bytes(payload);temp.replace(target)
    projected=d.dimensions.map(lambda x:str(json.loads(x).get('type','current')).lower() not in {'current','observed','actual'})
    manifest={'schema_version':1,'source_id':name,'fetched_at':stamp,
              'observed_from':d.loc[~projected,'period_start'].min() if (~projected).any() else None,
              'observed_through':d.loc[~projected,'period_end'].max() if (~projected).any() else None,
              'projected_through':d.loc[projected,'period_end'].max() if projected.any() else None,
              'rows':len(d),'countries':sorted(d.country.unique()),'configured_countries':config['countries'],
              'sha256':hashlib.sha256(target.read_bytes()).hexdigest(),'requests':client.requests,
              'provenance_note':'Publication time may be unavailable; ingestion time is not publication time.'}
    write_json_if_changed(output/f'{name}.manifest.json',manifest)
    return manifest
