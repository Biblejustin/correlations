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


IPC_PERIOD_COLUMNS = ['Country','Date of analysis','Validity period','From','To']
IPC_HISTORY_RESOURCE = 'ipc_global_national_long.csv'
# Conservative consistency screen, not a claim that source counts are this precise.
# Match the existing 1.5 percentage-point population-ratio tolerance; allow five
# people for independently rounded small integer partitions.
IPC_COUNT_ROUNDING_FRACTION = .015
IPC_COUNT_ROUNDING_PEOPLE = 5


def ipc_period_key(country,assessment,validity,start,end):
    """Local composite identity, not a publisher analysis ID (absent from HDX CSV)."""
    fields=[str(x) for x in [country,assessment,validity,start,end]]
    return 'ipc-hdx-period-v1:'+hashlib.sha256(json.dumps(fields).encode()).hexdigest()


def normalize_ipc(d,countries,start_year,url,published=None):
    required=set(IPC_PERIOD_COLUMNS)|{'Phase','Percentage','Number'}
    if not required<=set(d):raise ValueError('IPC CSV schema changed')
    d=d[d.Country.isin(countries)].copy()
    if d[IPC_PERIOD_COLUMNS].isna().any().any():raise ValueError('Missing IPC assessment identity')
    starts,ends=pd.to_datetime(d.From,errors='coerce'),pd.to_datetime(d.To,errors='coerce')
    if starts.isna().any() or ends.isna().any() or (ends<starts).any():raise ValueError('Invalid IPC assessment dates')
    d=d[starts.dt.year.ge(start_year)].copy()
    if not d['Validity period'].isin(['current','first projection','second projection']).all():
        raise ValueError('Unknown IPC validity type')
    if not d.Phase.astype(str).isin(['all','1','2','3','4','5','3+']).all():raise ValueError('Unknown IPC phase')
    for field in ['Number','Percentage']:
        parsed=pd.to_numeric(d[field],errors='coerce')
        if (d[field].notna() & ~np.isfinite(parsed)).any() or parsed.lt(0).any():
            raise ValueError(f'Invalid IPC {field}')
        if field=='Percentage' and parsed.gt(1).any():raise ValueError('IPC fraction out of range')
    rows=[];quarantine=[];accepted=[];issues=[]
    for identity, original in d.groupby(IPC_PERIOD_COLUMNS,sort=False,dropna=False):
        country,assessment,validity,start,end=identity
        key=ipc_period_key(*identity)
        group=original.drop_duplicates()
        totals=group[group.Phase.eq('all')]
        reason=None;failure_kind='unresolved_denominator';partition_evidence={}
        if group.Phase.duplicated().any():reason='Conflicting rows share a derived period identity; publisher analysis ID/scope missing'
        elif len(totals)!=1:reason='Missing or nonunique phase-all assessed-population denominator'
        elif number(totals.iloc[0].Number) is None or float(totals.iloc[0].Number)<=0:
            reason='Missing or nonpositive assessed-population denominator'
        if reason is None:
            denominator=float(totals.iloc[0].Number)
            tolerance=max(IPC_COUNT_ROUNDING_PEOPLE,IPC_COUNT_ROUNDING_FRACTION*denominator)
            counts={str(r.Phase):number(r.Number) for _,r in group.iterrows()}
            for labels,total_label in [(['1','2','3','4','5'],'all'),(['3','4','5'],'3+')]:
                total=counts.get(total_label)
                if total is None:continue
                supplied=[counts[p] for p in labels if counts.get(p) is not None]
                summed=sum(supplied)
                complete=len(supplied)==len(labels)
                if summed>total+tolerance or (complete and abs(summed-total)>tolerance):
                    reason=f'Inconsistent phase-count partition: {"+".join(labels)} versus phase {total_label}'
                    failure_kind='invalid_partition'
                    partition_evidence={'partition_phases':labels,'reported_total_phase':total_label,
                        'reported_total':total,'supplied_phase_sum':summed,'complete_partition':complete,
                        'allowed_count_difference':tolerance}
                    break
        if reason:
            if group.Phase.duplicated().any():failure_kind='ambiguous_identity'
            issues.append({'period_key':key,**dict(zip(IPC_PERIOD_COLUMNS,identity)),
                'reason':reason,'failure_kind':failure_kind,'source_rows':len(original),**partition_evidence})
            quarantine.append(original.assign(quarantine_reason=reason,derived_period_key=key))
            continue
        denominator=float(totals.iloc[0].Number)
        accepted.append(key)
        for _,r in group.iterrows():
            phase=str(r.Phase)
            if phase not in {'3+','3','4','5'}:continue
            value,numerator=number(r.Percentage),number(r.Number)
            if value is None:continue
            if numerator is None or numerator>denominator or not np.isclose(value,numerator/denominator,atol=.015,rtol=0):
                raise ValueError('IPC numerator/percentage incompatible with exact-period assessed population')
            rows.append(obs(country,start,end,'ipc_phase_'+phase.replace('+','plus')+'_fraction',
                value,'fraction_of_population_analyzed','ipc',url,'HDX national assessment history v1',frequency='assessment',
                numerator=numerator,denominator=denominator,published_at=published,provisional=validity!='current',
                dimensions={'assessment':assessment,'type':validity,'source_analysis_id':None,
                    'derived_period_key':key,'identity_basis':'country, analysis month label, validity type and dates; no publisher analysis ID in CSV',
                    'source_snapshot_status':'present in full-history export',
                    'source_publication_kind':'export last-modified, not assessment publication date',
                    'source_total_country_population':number(r.get('Total country population')),
                    'geographic_scope':'IPC population analyzed; territorial coverage not specified in national export',
                    'geography_comparable_to_country':False},
                quality_note='Historical assessment. Fraction uses its exact-period phase-all analyzed population, not country population. Source percentages rounded. Export lacks publisher assessment IDs and boundary geometry; ambiguous identities quarantined. Territorial scope not certified; excluded from cross-source country lag tests. Current and projections remain separate.'))
    out=frame(rows)
    out.attrs['ipc_history']={'resource':IPC_HISTORY_RESOURCE,'source_rows':len(d),
        'accepted_period_keys':accepted,'quarantined_periods':issues,
        'partition_tolerance':{'relative_to_assessed_population':IPC_COUNT_ROUNDING_FRACTION,
            'minimum_people':IPC_COUNT_ROUNDING_PEOPLE,
            'interpretation':'Conservative consistency screen allowing source rounding/process differences; not a precision guarantee. Never replace reported denominator with phase sum.'},
        'publisher_analysis_ids_available':False,'geographic_comparability_verified':False}
    out.attrs['ipc_quarantine_csv']=(pd.concat(quarantine,ignore_index=True) if quarantine else
        pd.DataFrame(columns=list(d.columns)+['quarantine_reason','derived_period_key'])).to_csv(index=False)
    return out


def ipc(client,countries,start_year):
    d,url,published=hdx_resource(client,'global-acute-food-insecurity-country-data',IPC_HISTORY_RESOURCE)
    return normalize_ipc(d,countries,start_year,url,published)


def merge_ipc_history(old,new,history):
    """Replace entire matching periods; keep unmatched prior snapshots with explicit lineage."""
    accepted=set(history['accepted_period_keys'])
    quarantined={p['period_key'] for p in history['quarantined_periods']}
    invalid={p['period_key'] for p in history['quarantined_periods'] if p.get('failure_kind')=='invalid_partition'}
    retained=[]
    for row in old.to_dict('records'):
        desc=json.loads(row['dimensions'])
        if not desc.get('assessment') or not desc.get('type'):raise ValueError('Prior IPC record lacks assessment identity')
        key=ipc_period_key(row['country'],desc['assessment'],desc['type'],row['period_start'],row['period_end'])
        # A known count contradiction cannot be resurrected from a prior snapshot.
        # Raw source evidence and archived observations retain the exclusion lineage.
        if key in accepted or key in invalid:continue
        status=('retained prior snapshot; current history identity quarantined' if key in quarantined else
                'retained prior snapshot; period absent from current history export')
        desc.update(derived_period_key=key,source_analysis_id=None,source_snapshot_status=status,
                    geography_comparable_to_country=False)
        row['dimensions']=json.dumps(desc,sort_keys=True)
        note=' Prior validated snapshot retained with its original source URL/version and retrieval time; not certified as current full-history data.'
        if note.strip() not in row['quality_note']:row['quality_note']+=note
        retained.append(row)
    clean_new=new.copy();clean_new.attrs={}
    parts=[part for part in [frame(retained),clean_new] if not part.empty]
    return validate_observations(pd.concat(parts,ignore_index=True) if parts else frame([]))


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
    """Keep source quotes; pair only one exact daily-wage series per market/month.

    Multiple quotes *within* an exact food or wage series use their median for the
    derived ratio. Distinct wage names, IDs or price types never share a median.
    DAY/1 DAY labels represent the same daily unit; original labels remain lineage.
    """
    required={'date','market_id','commodity','commodity_id','unit','priceflag','pricetype','currency','price'}
    if not required<=set(d):raise ValueError('WFP CSV schema changed')
    d=d[d.priceflag.str.lower().eq('actual')].copy()
    d['price']=pd.to_numeric(d.price,errors='coerce')
    d=d[d.price.gt(0)&np.isfinite(d.price)].copy()
    d['month']=pd.to_datetime(d.date).dt.to_period('M').astype(str)
    identity=['market_id','commodity','commodity_id','unit','pricetype','currency']
    for col in identity:d[col]=d[col].astype(str)
    wage_keys=['market_id','month','currency']
    wages=d[d.commodity.str.contains(r'Wage.*non-qualified',case=False,regex=True,na=False)
            & d.unit.str.upper().str.strip().str.replace(' ','',regex=False).isin(['DAY','1DAY'])].copy()
    wages['signature']=wages.apply(lambda r:json.dumps({
        'commodity_id':r.commodity_id,'commodity':r.commodity,'unit':'DAY',
        'pricetype':r.pricetype,'currency':r.currency},sort_keys=True),axis=1) if len(wages) else pd.Series(dtype=str)
    wage={};signature_counts={}
    for key,g in wages.groupby(wage_keys,sort=True):
        signatures=g.signature.unique();signature_counts[key]=len(signatures)
        if len(signatures)==1:
            wage[key]={'value':float(g.price.median()),'signature':json.loads(signatures[0]),
                       'original_units':sorted(g.unit.unique()),'quote_count':len(g)}
    rows=[]
    # Duplicate raw quotes retain distinct lineage instead of failing validation or
    # overwriting each other. Ordinary source-series dimensions remain unchanged.
    d['quote_count']=d.groupby(identity+['month'],dropna=False).price.transform('size')
    d['quote_ordinal']=d.groupby(identity+['month'],dropna=False).cumcount()+1
    for _,r in d.iterrows():
        dims={k:r[k] for k in identity}
        if r.quote_count>1:
            dims.update(source_quote_ordinal=int(r.quote_ordinal),source_quote_date=str(r.date))
        key=(r.market_id,r.month,r.currency)
        if 'wage' in r.commodity.lower() and key in signature_counts:
            dims.update(affordability_wage_signature_count=signature_counts[key],
                        affordability_pairing_status=('unique daily wage series' if signature_counts[key]==1
                                                      else 'ambiguous daily wage series; ratios withheld'))
        day=pd.Timestamp(r['date']);end=(day+pd.offsets.MonthEnd(0)).date().isoformat()
        rows.append(obs(country,day.replace(day=1).date().isoformat(),end,
                        ('labor_wage' if 'wage' in r.commodity.lower() else 'food_price' if is_food_commodity(r.commodity) else 'food_processing_cost'),
                        r.price,f'{r.currency}/{r.unit}','wfp',url,'HDX current export',frequency='monthly',
                        dimensions=dims,published_at=published,
                        quality_note='Actual source market quotes retained; distinct baskets/markets/currencies are not interchangeable.'))
    staples=d[d.pricetype.str.lower().eq('retail') & d.commodity.map(is_food_commodity)
              & d.commodity.str.contains(r'wheat|barley|maize|rice|sorghum',case=False,na=False)]
    for _,g in staples.groupby(identity+['month'],sort=True,dropna=False):
        r=g.iloc[0];unitkg=kg_unit(r.unit);key=(r.market_id,r.month,r.currency)
        if not unitkg or key not in wage:continue
        w=wage[key];day=pd.Timestamp(r.date);pricekg=float(g.price.median()/unitkg)
        dims={'market_id':r.market_id,'commodity':r.commodity,'commodity_id':r.commodity_id,
              'currency':r.currency,'food_unit_original':r.unit,'food_unit_kg':unitkg,
              'food_normalized_unit':'KG','food_price_type':r.pricetype,
              'wage_series_signature':w['signature'],'wage_original_units':w['original_units'],
              'wage_quote_count':w['quote_count'],'food_quote_count':len(g),
              'pairing_rule':'unique_daily_wage_series_v1; within-series median quotes'}
        rows.append(obs(country,day.replace(day=1).date().isoformat(),(day+pd.offsets.MonthEnd(0)).date().isoformat(),
                        'staple_kg_per_daily_wage',w['value']/pricekg,'kg/day_wage','wfp',url,
                        'matched actual market-month; exact wage signature v1',frequency='monthly',
                        numerator=w['value'],denominator=pricekg,dimensions=dims,published_at=published,
                        quality_note='Local non-qualified daily wage / retail staple price per kg. Median quotes only within each exact series; ambiguous wage signatures withheld. No national wage or CPI interpretation.'))
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
    ipc_history=d.attrs.get('ipc_history') if name=='ipc' else None
    ipc_quarantine=d.attrs.get('ipc_quarantine_csv') if name=='ipc' else None
    d=validate_observations(d)
    stamp=max(m['fetched_at'] for m in client.requests)
    d['fetched_at']=stamp
    target=output/(f'{name}.csv.gz' if name in {'wfp','who'} else f'{name}.csv')
    # A failed/truncated full refresh must not silently replace a good observation history.
    if target.exists():
        old=pd.read_csv(target)
        if name!='ipc' and len(d)<0.9*len(old):raise ValueError(f'{name}: suspicious shrink {len(old)} -> {len(d)}')
        if name=='ipc':
            previous_manifest=output/'ipc.manifest.json'
            previous_rows=(json.loads(previous_manifest.read_text()).get('history',{}).get('source_rows')
                           if previous_manifest.exists() else None)
            if previous_rows and ipc_history['source_rows']<.9*previous_rows:
                raise ValueError(f'ipc: suspicious full-history source shrink {previous_rows} -> {ipc_history["source_rows"]}')
            d=merge_ipc_history(old,d,ipc_history)
    if name=='ipc':
        # Diagnostics are outside the observation CSV glob. Prior values remain auditable.
        diagnostics=output.parent/'diagnostics/ipc_history'
        diagnostics.mkdir(parents=True,exist_ok=True)
        if target.exists() and old.drop(columns='fetched_at').to_csv(index=False)!=d.drop(columns='fetched_at').to_csv(index=False):
            previous=target.read_bytes();previous_hash=hashlib.sha256(previous).hexdigest()
            archive=diagnostics/'prior_snapshots'/f'{previous_hash}.csv'
            archive.parent.mkdir(parents=True,exist_ok=True)
            if not archive.exists():archive.write_bytes(previous)
            previous_manifest=output/'ipc.manifest.json'
            if previous_manifest.exists():
                archived_manifest=archive.with_suffix('.manifest.json')
                if not archived_manifest.exists():archived_manifest.write_bytes(previous_manifest.read_bytes())
        evidence=ipc_quarantine.encode()
        evidence_hash=hashlib.sha256(evidence).hexdigest()
        quarantine_path=diagnostics/f'quarantine_{evidence_hash}.csv'
        if not quarantine_path.exists():quarantine_path.write_bytes(evidence)
        snapshot_status=d.dimensions.map(lambda x:json.loads(x).get('source_snapshot_status',''))
        ipc_status={k:v for k,v in ipc_history.items() if k!='accepted_period_keys'}
        ipc_status.update(accepted_periods=len(ipc_history['accepted_period_keys']),
            retained_prior_rows=int(snapshot_status.str.startswith('retained prior snapshot').sum()),
            quarantine_evidence=str(quarantine_path.relative_to(output.parent)),
            quarantine_sha256=evidence_hash,
            revision_policy='Only an unambiguous matching country/analysis-month/type/start/end period replaces prior rows, including withdrawn phase fields. Absent or ambiguous periods retain prior observations with original lineage; confirmed count-partition conflicts exclude matching prior observations from active data while preserving archives. No selection among ambiguous source rows.',
            requests=client.requests)
        write_json_if_changed(diagnostics/'history_status.json',ipc_status)
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
    if name=='ipc':manifest['history']=ipc_status
    write_json_if_changed(output/f'{name}.manifest.json',manifest)
    return manifest
