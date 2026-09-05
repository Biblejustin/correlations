"""Geographically aligned descriptive panel and predeclared exploratory lag family."""
from __future__ import annotations

import datetime as dt
import json
import hashlib
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

from monitoring.feeds import BASE,CONFIG,is_food_commodity

PANEL_COLUMNS=['country','year','metric','value','unit','n_observations','geographic_scope','population_denominator_compatible','quality_note']
ANNUAL_UNITS={'population':'people','religious_freedom':'V-Dem latent interval score',
              'refugees_origin_stock':'people','asylum_seekers_origin_stock':'people','returned_refugees_flow':'people',
              'conflict_total_deaths':'deaths','conflict_battle_deaths':'deaths','conflict_nonstate_deaths':'deaths','conflict_civilian_targeting_deaths':'deaths'}

def dimensions(value):
    decoded=json.loads(value) if isinstance(value,str) else value
    if not isinstance(decoded,dict):raise ValueError('Dimensions must be JSON object')
    return decoded

def is_projection(value):
    return str(dimensions(value).get('type','current')).strip().lower() not in {'current','actual','observed'}


def load_observations(root=BASE/'data/monitoring'):
    paths=sorted(Path(root).glob('*.csv'))+sorted(Path(root).glob('*.csv.gz'))
    return pd.concat([pd.read_csv(p) for p in paths],ignore_index=True) if paths else pd.DataFrame()


def food_price_changes(d):
    """Compare each market/commodity/unit/currency series with itself, 12 months earlier."""
    prices=d[d.metric.eq('food_price')].copy()
    if prices.empty:return pd.DataFrame(columns=['country','year','metric','value','n_observations','quality_note'])
    prices=prices[prices.value.gt(0)&np.isfinite(prices.value)].copy()
    prices['month']=pd.to_datetime(prices.period_start).dt.to_period('M')
    changes=[];basket_sizes={}
    for (country,dimensions),g in prices.groupby(['country','dimensions']):
        desc=json.loads(dimensions)
        commodity=str(desc.get('commodity','')).lower()
        if str(desc.get('pricetype','')).lower()!='retail' or 'wage' in commodity:continue
        if not is_food_commodity(commodity):continue
        if not desc.get('currency') or not desc.get('unit'):continue
        g=g.groupby('month').value.median()
        # Fixed membership based on information before monitor period, not observed price jumps.
        baseline=g[(g.index.year>=2015)&(g.index.year<=2019)]
        if len(baseline)<24:continue
        basket_sizes[country]=basket_sizes.get(country,0)+1
        g=g.reindex(pd.period_range(g.index.min(),g.index.max(),freq='M'))
        yoy=np.log(g/g.shift(12))
        for month,value in yoy.dropna().items():
            changes.append({'country':country,'month':month,'value':value,'series':dimensions})
    if not changes:return pd.DataFrame(columns=['country','year','metric','value','n_observations','quality_note'])
    c=pd.DataFrame(changes);totals=pd.Series(basket_sizes)
    m=c.groupby(['country','month']).agg(value=('value','median'),n=('series','nunique')).reset_index()
    m=m[m.apply(lambda r:r['n']>=max(3,int(np.ceil(.7*totals.loc[r.country]))),axis=1)].copy()
    m['year']=m.month.map(lambda x:x.year)
    annual=m.groupby(['country','year']).agg(value=('value','mean'),n_observations=('month','nunique')).reset_index()
    annual=annual[annual.n_observations>=9].copy()
    annual['value']=100*np.expm1(annual.value)
    annual['metric']='retail_staple_price_yoy_pct'
    annual['unit']='percent year-on-year'
    annual['geographic_scope']='fixed observed market basket within country'
    annual['quality_note']='Matched-series median price changes; fixed 2015–19 basket membership, >=70% series and >=9 months; not CPI.'
    return annual


def build_annual_panel(observations,as_of=None):
    today=pd.Timestamp(as_of or dt.date.today()).normalize()
    if observations.empty:return pd.DataFrame(columns=PANEL_COLUMNS)
    d=observations.copy()
    starts,ends=pd.to_datetime(d.period_start),pd.to_datetime(d.period_end)
    if starts.isna().any() or ends.isna().any() or (ends<starts).any():raise ValueError('Invalid observation dates')
    d=d.loc[starts<=today].copy()
    d['_dimensions']=d.dimensions.map(dimensions)
    d['_projected']=d.dimensions.map(is_projection)
    d['year']=pd.to_datetime(d.period_end).dt.year
    rows=[]
    annual=d[d.frequency.eq('annual') & ~d._projected & (d.year<today.year)]
    for _,r in annual.iterrows():
        if r.metric not in ANNUAL_UNITS:continue
        if r.unit!=ANNUAL_UNITS[r.metric]:raise ValueError(f'Incompatible unit for {r.metric}: {r.unit}')
        if r.metric=='religious_freedom' and ('West Bank' in str(r._dimensions.get('source_country_name','')) or r.country=='PSE'):continue
        start,end=pd.Timestamp(r.period_start),pd.Timestamp(r.period_end)
        if start!=pd.Timestamp(year=r.year,month=1,day=1) or end!=pd.Timestamp(year=r.year,month=12,day=31):
            raise ValueError('Annual observation must cover its declared complete calendar year')
        rows.append({'country':r.country,'year':r.year,'metric':r.metric,'value':r.value,'unit':r.unit,
                     'n_observations':1,'geographic_scope':r._dimensions.get('geographic_scope','source country definition'),
                     'population_denominator_compatible':r._dimensions.get('population_denominator_compatible',not (r.source_id=='ucdp' and (r.country=='ISR' or (r.country=='SDN' and r.year<=2011)))),
                     'quality_note':r.quality_note})
    # Latest actual assessment, only when its territorial scope is explicitly comparable.
    # IPC country code alone does not certify that its population analyzed is the whole country.
    ipc=d[d.metric.eq('ipc_phase_3plus_fraction') & ~d._projected & (d.year<today.year)
          & d._dimensions.map(lambda x:x.get('geography_comparable_to_country') is True)]
    for (country,year),g in ipc.groupby(['country','year']):
        row=g.sort_values(['period_end','published_at'],na_position='first').iloc[-1]
        rows.append({'country':country,'year':year,'metric':'ipc_current_3plus_fraction','value':row.value,
                     'unit':'fraction_of_population_analyzed','n_observations':1,'geographic_scope':'verified comparable assessment geography',
                     'quality_note':'Latest current assessment this year; not annual mean. Explicit geographic match required.'})
    who=d[d.metric.eq('influenza_positivity') & ~d._projected & d._dimensions.map(
        lambda x:str(x.get('surveillance_origin','')).upper()=='SENTINEL')].copy()
    if not who.empty:
        # Thursday determines ISO-week year; a cross-year week is counted once.
        who['year']=(pd.to_datetime(who.period_start)+pd.Timedelta(days=3)).dt.year
        who=who[(who.year<today.year)&(pd.to_datetime(who.period_end)<=today)]
    for (country,year),g in who.groupby(['country','year']):
        if g.unit.ne('positive_fraction').any() or g.denominator.le(0).any() or not np.allclose(g.value,g.numerator/g.denominator):
            raise ValueError('Incompatible influenza positivity units/denominators')
        if g.period_start.duplicated().any():raise ValueError('Duplicate sentinel surveillance week')
        if g.period_start.nunique()<26:continue
        rows.append({'country':country,'year':year,'metric':'influenza_sentinel_positivity',
                     'value':g.numerator.sum()/g.denominator.sum(),'unit':'positive_fraction',
                     'n_observations':g.period_start.nunique(),'geographic_scope':'reported sentinel surveillance sites',
                     'quality_note':'Specimen-weighted sentinel positivity, >=26 reported ISO weeks; not population prevalence.'})
    panel=pd.DataFrame(rows,columns=PANEL_COLUMNS)
    prices=d[~d._projected & (pd.to_datetime(d.period_end)<=today)]
    annual_prices=food_price_changes(prices)
    if not annual_prices.empty:panel=pd.concat([panel,annual_prices[annual_prices.year<today.year]],ignore_index=True)
    if panel.empty:return pd.DataFrame(columns=PANEL_COLUMNS)
    if panel.duplicated(['country','year','metric']).any():raise ValueError('Incompatible observations in annual panel')
    wide=panel.pivot(index=['country','year'],columns='metric',values='value')
    extras=[]
    for (country,year),r in wide.iterrows():
        population=r.get('population',np.nan)
        if np.isfinite(population) and population>0:
            for metric in ['conflict_total_deaths','conflict_battle_deaths','conflict_civilian_targeting_deaths']:
                if pd.notna(r.get(metric)):
                    source_rows=panel[panel.country.eq(country)&panel.year.eq(year)&panel.metric.eq(metric)]
                    if len(source_rows) and source_rows.iloc[0].get('population_denominator_compatible') != True:continue
                    extras.append(dict(country=country,year=year,metric=metric+'_per_100k',
                        value=r[metric]/population*1e5,unit='deaths per 100000 people',n_observations=1,
                        geographic_scope='source country definitions; political borders may differ',
                        quality_note='UCDP best estimate / same-country same-year WDI population; territory definitions require care.'))
        if 'refugees_origin_stock' in r and year-1 in wide.loc[country].index:
            before=wide.loc[(country,year-1)].get('refugees_origin_stock',np.nan)
            if pd.notna(before) and pd.notna(r['refugees_origin_stock']):
                extras.append(dict(country=country,year=year,metric='refugees_origin_stock_change',
                    value=r['refugees_origin_stock']-before,unit='people net stock change',n_observations=2,
                    geographic_scope='worldwide destinations by source country of origin',
                    quality_note='Net stock change, not newly displaced people; returns/reclassification also contribute.'))
    return pd.concat([panel,pd.DataFrame(extras)],ignore_index=True).sort_values(['country','year','metric'])


def bh_full_family(p_values):
    """Unavailable prespecified tests stay in family as p=1, not silently removed."""
    p=np.array([1 if pd.isna(x) else x for x in p_values],dtype=float)
    order=np.argsort(p);q=np.empty(len(p))
    q[order]=np.minimum.accumulate((p[order]*len(p)/np.arange(1,len(p)+1))[::-1])[::-1]
    return np.minimum(q,1)


def contiguous_longest(frame):
    frame=frame.sort_index()
    groups=frame.index.to_series().diff().ne(1).cumsum()
    return max((g for _,g in frame.groupby(groups)),key=len) if len(frame) else frame


def lag_tests(panel,config=CONFIG,n_permutations=1999):
    if n_permutations<1:raise ValueError('Permutation count must be positive')
    pairs=[('conflict_total_deaths_per_100k','refugees_origin_stock_change'),
           ('conflict_total_deaths_per_100k','ipc_current_3plus_fraction'),
           ('retail_staple_price_yoy_pct','ipc_current_3plus_fraction')]
    rows=[];rng=np.random.default_rng(config['seed'])
    for country in config['countries']:
        sub=panel[panel.country.eq(country)]
        wide=sub.pivot(index='year',columns='metric',values='value')
        for a,b in pairs:
            for lag in config['annual_lags']:
                row=dict(country=country,predictor=a,response=b,lag_years=lag,n=0,r=np.nan,p_block=np.nan,
                         status='insufficient comparable years')
                if a not in wide or b not in wide:
                    rows.append(row);continue
                x=wide[a].copy();x.index=x.index+lag
                common=contiguous_longest(pd.concat([x.rename('x'),wide[b].rename('y')],axis=1).dropna())
                row['n']=len(common)
                row['start_year']=int(common.index.min()) if len(common) else None
                row['end_year']=int(common.index.max()) if len(common) else None
                if len(common)<config['minimum_test_years']:
                    rows.append(row);continue
                years=common.index.to_numpy(dtype=float)
                # Signed log accommodates net stock reductions; raw units retained in panel.
                values=[]
                for name in ['x','y']:
                    v=common[name].to_numpy(dtype=float)
                    v=np.sign(v)*np.log1p(np.abs(v))
                    values.append(v-np.polyval(np.polyfit(years,v,1),years))
                x,y=values
                if np.std(x)<1e-12 or np.std(y)<1e-12:
                    row['status']='constant residual series';rows.append(row);continue
                observed=stats.pearsonr(x,y).statistic
                cell_seed=int.from_bytes(hashlib.sha256(f'{config["seed"]}:{country}:{a}:{b}:{lag}'.encode()).digest()[:8],'little')
                rng=np.random.default_rng(cell_seed)
                blocks=[x[i:i+3] for i in range(0,len(x),3)]
                exceed=0
                for _ in range(n_permutations):
                    shuffled=np.concatenate([blocks[i] for i in rng.permutation(len(blocks))])
                    exceed+=abs(stats.pearsonr(shuffled,y).statistic)>=abs(observed)
                row.update(r=float(observed),p_block=(exceed+1)/(n_permutations+1),status='exploratory')
                rows.append(row)
    out=pd.DataFrame(rows);out['q_family']=bh_full_family(out.p_block)
    return out


def synchrony(panel,config=CONFIG,n_permutations=1999):
    """Fixed-domain exceedances plus country-level circular-shift sensitivity.

    Independent circular shifts retain each domain's ordered serial structure
    and break same-year alignment across domains. Calibration tests the fraction
    of compound years over a contiguous observed run, not each year's rarity.
    Historical baseline/threshold reuse makes this exploratory, not prospective.
    """
    domains={'conflict':'conflict_total_deaths_per_100k','food':'retail_staple_price_yoy_pct',
             'respiratory':'influenza_sentinel_positivity','religious_restriction':'religious_freedom'}
    rows=[];calibration=[];rng=np.random.default_rng(config['seed'])
    for country in config['countries']:
        p=panel[panel.country.eq(country)].pivot(index='year',columns='metric',values='value').sort_index()
        z={}
        for domain,metric in domains.items():
            if metric not in p:continue
            series=p[metric].copy()
            if domain=='religious_restriction':series=-series
            baseline=series.loc[config['baseline_years'][0]:config['baseline_years'][1]].dropna()
            if len(baseline)<config['minimum_baseline_years'] or baseline.std()<1e-12:continue
            z[domain]=(series-baseline.mean())/baseline.std()
        calibration_row={'country':country,'calibration_n_years':0,'calibration_start':None,'calibration_end':None,
                         'calibration_observed_fraction':np.nan,'p_joint':np.nan,
                         'calibration_status':'unavailable: missing fixed domain/baseline coverage'}
        if len(z)==len(domains):
            complete=contiguous_longest(pd.DataFrame(z).dropna())
            calibration_row['calibration_n_years']=len(complete)
            calibration_row['calibration_status']='unavailable: insufficient contiguous complete years'
            if len(complete)>=config['minimum_test_years'] and n_permutations>0:
                country_seed=int.from_bytes(hashlib.sha256(f'{config["seed"]}:synchrony:{country}'.encode()).digest()[:8],'little')
                rng=np.random.default_rng(country_seed)
                matrix=(complete.to_numpy()>config['extreme_z']).astype(int)
                observed=float(np.mean(matrix.sum(axis=1)>=2))
                extreme=0
                for _ in range(n_permutations):
                    shifted=np.column_stack([np.roll(matrix[:,i],rng.integers(len(matrix))) for i in range(matrix.shape[1])])
                    extreme+=float(np.mean(shifted.sum(axis=1)>=2))>=observed
                calibration_row.update(calibration_start=int(complete.index.min()),calibration_end=int(complete.index.max()),
                    calibration_observed_fraction=observed,p_joint=(extreme+1)/(n_permutations+1),
                    calibration_status='exploratory country-level compound-year frequency; independent domain circular shifts')
        calibration.append(calibration_row)
        years=p.index if len(p) else [dt.date.today().year-1]
        for year in years:
            available=[key for key,values in z.items() if year in values.index and pd.notna(values.loc[year])]
            eligible=len(available)==len(domains)
            count=sum(z[key].loc[year]>config['extreme_z'] for key in available) if eligible else np.nan
            rows.append(dict(country=country,year=year,eligible=eligible,extreme_domains=count,
                             compound_extreme=(count>=2) if eligible else None,
                             missing_domains=','.join(sorted(set(domains)-set(available))),
                             interpretation='Fixed-threshold descriptive year; calibration pertains to whole country time series'))
    calibrated=pd.DataFrame(calibration)
    calibrated['q_joint_country_family']=bh_full_family(calibrated.p_joint)
    return pd.DataFrame(rows).merge(calibrated,on='country',validate='many_to_one')


def regional_spread(sync,config=CONFIG):
    rows=[]
    for year,group in sync.groupby('year'):
        eligible=group[group.eligible]
        complete=set(eligible.country)==set(config['countries'])
        numerator=int(eligible.compound_extreme.fillna(False).astype(bool).sum())
        rows.append({'year':year,'observed_pilot_countries':len(eligible),'configured_countries':len(config['countries']),
                     'compound_countries':numerator if len(eligible) else np.nan,
                     'fraction_fixed_pilot':numerator/len(eligible) if complete else np.nan,
                     'status':'descriptive fixed pilot; not global prevalence' if complete else 'unavailable: incomplete fixed pilot coverage'})
    return pd.DataFrame(rows)


def israel_summary(root=BASE/'data/israel_monitoring'):
    """Read copied feeder artifacts only; central report remains portable."""
    root=Path(root)
    rain=root/'israel-rain-agriculture'
    lines=['## Israel crop and water observations','']
    water=rain/'data/water_security_metadata.json'
    if water.exists():
        info=json.loads(water.read_text());lake=info['kinneret']
        lines.append(f"Kinneret latest observation: **{lake['latest_level_m']:.3f} m**, {lake['observation_end']}; "
                     f"{lake['observations']:,} measurements. Source dates/gaps retained; "
                     f"{lake['unobserved_days_within_span']:,} unobserved dates inside catalog span. "
                     f"[Official measurements]({lake['source_url']}).")
        lines.append(f"Historical rainfall remains CRU TS4.08 through complete rain year {info['historical_rain']['last_complete_rain_year']}; current rainfall not integrated. Lake level also responds to pumping/transfers/evaporation.")
    else:lines.append('Kinneret copied source metadata unavailable. Run sync_feeders.py; missing values are not zero.')
    decomposition=rain/'results/wheat_decomposition.csv'
    if decomposition.exists():
        d=pd.read_csv(decomposition)
        selected=d[d['start'].eq(1991)&d.rain.eq('total_mm')]
        lines+=['','| Wheat outcome × total rain, 1991–2023 | n | r | HAC q, full 30-test follow-up |',
                '|---|---:|---:|---:|']
        for _,r in selected.iterrows():lines.append(f'| {r.outcome} | {r.n} | {r.r:+.3f} | {r.q_hac_family30:.6f} |')
        lines.append('Historical exploratory associations after linear detrending. Production, area and yield are dependent measures; source yield identity checked. Future holdout starts 2025; no held-out success claimed.')
    else:lines.append('Wheat decomposition artifact unavailable.')
    irrigation=rain/'results/irrigation_sensitivity.csv'
    if irrigation.exists():
        d=pd.read_csv(irrigation);r=d[d.rain_measure.eq('total_mm')&d.coefficient.eq('rain')].iloc[0]
        lines.append(f"Reported irrigation-share sensitivity: {r.n} observed years, gaps retained; adjusted rain coefficient {r.estimate:+.2f} kg/ha/mm, calendar-HAC q={r.q_calendar_hac_family6:.3f} across six supplementary tests. National irrigation share is not wheat-specific; no causal attribution.")
    pressure=root/'israel-pressure-disasters/data/test_results.csv'
    if pressure.exists():
        d=pd.read_csv(pressure)
        lines.append(f"Historical US diplomacy/disaster tests, frozen 1991–2024: minimum circular-shift BH q={d.q.min():.3f}. Pressure uses upper tail; control deficit uses lower tail. Curated lists are not a current diplomacy feed.")
    return lines


def latest_monitor_tables(observations,panel,today,config=CONFIG):
    """Display fixed-country latest observations; never select largest outcomes."""
    lines=['','## Latest annual conflict and displacement observations','',
           '| Country | Conflict year | Organized-violence deaths, best estimate | Deaths per 100k / population denominator | Refugee-stock year | Refugees by country of origin |',
           '|---|---:|---:|---|---:|---:|']
    for country in config['countries']:
        sub=panel[panel.country.eq(country)]
        deaths=sub[sub.metric.eq('conflict_total_deaths')].sort_values('year')
        refugee=sub[sub.metric.eq('refugees_origin_stock')].sort_values('year')
        cy,death,rate='—','unavailable','unavailable'
        if len(deaths):
            r=deaths.iloc[-1];cy=str(int(r.year));death=f'{r.value:,.0f}'
            rates=sub[sub.year.eq(r.year)&sub.metric.eq('conflict_total_deaths_per_100k')]
            populations=sub[sub.year.eq(r.year)&sub.metric.eq('population')]
            if len(rates) and len(populations):rate=f'{rates.iloc[0].value:.2f} / {populations.iloc[0].value:,.0f} people'
        ry,stock='—','unavailable'
        if len(refugee):
            r=refugee.iloc[-1];ry=str(int(r.year));stock=f'{r.value:,.0f}'
        label='ISR (UCDP Israel/Palestine unit)' if country=='ISR' and len(deaths) else country
        lines.append(f'| {label} | {cy} | {death} | {rate} | {ry} | {stock} |')
    lines+=['','UCDP total organized-violence deaths combine state-based, non-state and one-sided violence. Rates use same-country, same-year WDI population only where territory is comparable. The UCDP Israel source unit includes Palestinian territories, so its total is not Israeli deaths and no ISR-only population rate/lag is computed; pre-2012 Sudan also lacks a matched post-partition denominator. UNHCR origin-country stocks span worldwide destinations; these are not new-displacement flows. Latest annual year is shown explicitly.',
            '', '## Latest sentinel respiratory observations','',
            '| Country | Observed week | Influenza-positive specimens | Specimens tested | Positivity |',
            '|---|---|---:|---:|---:|']
    who=observations[observations.metric.eq('influenza_positivity') & ~observations.projected
         & observations.dimensions.map(lambda x:str(dimensions(x).get('surveillance_origin','')).upper()=='SENTINEL')
         & (pd.to_datetime(observations.period_end)<=today)]
    for country in config['countries']:
        sub=who[who.country.eq(country)].sort_values(['period_end','period_start'])
        if sub.empty:lines.append(f'| {country} | unavailable | — | — | — |');continue
        r=sub.iloc[-1]
        lines.append(f'| {country} | {r.period_start}–{r.period_end} | {r.numerator:,.0f} | {r.denominator:,.0f} | {r.value:.1%} |')
    lines+=['','WHO sentinel samples require at least 20 specimens. Provisional surveillance observations; positivity is not population prevalence. Missing/non-sentinel weeks are not substituted.',
            '', '## Latest religious-freedom observations','',
            '| Country code | Source territory | Year | V-Dem religious-freedom score |',
            '|---|---|---:|---:|']
    religion=observations[observations.metric.eq('religious_freedom') & ~observations.projected
              & (pd.to_datetime(observations.period_end).dt.year<today.year)]
    for country in config['countries']:
        sub=religion[religion.country.eq(country)].sort_values('period_end')
        if sub.empty:lines.append(f'| {country} | unavailable | — | — |');continue
        r=sub.iloc[-1];scope=str(dimensions(r.dimensions).get('source_country_name','source country definition')).replace('|',' / ')
        lines.append(f'| {country} | {scope} | {pd.Timestamp(r.period_end).year} | {r.value:+.3f} |')
    lines+=['','V-Dem v16 latent interval score; higher means more religious freedom. Expert-coded annual estimate, not incident count. PSE here denotes the source West Bank territory and is excluded from combined-territory country regressions.',
            '', '## Latest food-affordability examples','',
            '| Country | Market ID | Staple | Reference month | kg per daily non-qualified labor wage |',
            '|---|---|---|---|---:|']
    affordable=observations[observations.metric.eq('staple_kg_per_daily_wage') & observations.dimensions.map(lambda x:is_food_commodity(dimensions(x).get('commodity',''))) & ~observations.projected
                 & (pd.to_datetime(observations.period_end)<=today)]
    for country in config['countries']:
        sub=affordable[affordable.country.eq(country)].copy()
        if sub.empty:lines.append(f'| {country} | unavailable | — | — | — |');continue
        sub=sub[sub.period_start.eq(sub.period_start.max())].copy()
        sub['_market']=sub.dimensions.map(lambda x:str(dimensions(x).get('market_id','')))
        sub['_commodity']=sub.dimensions.map(lambda x:str(dimensions(x).get('commodity','')))
        sub['_currency']=sub.dimensions.map(lambda x:str(dimensions(x).get('currency','')))
        r=sub.sort_values(['_market','_commodity','_currency']).iloc[0]
        commodity=r['_commodity'].replace('|',' / ')
        lines.append(f"| {country} | {r['_market']} | {commodity} | {r.period_start[:7]} | {r.value:.2f} |")
    lines+=['','Nonrepresentative market examples. Selection is fixed: latest available matched month, then alphabetical market ID/staple/currency; never highest or lowest outcome. Wage and retail staple must share market, month and currency; quantities require an explicit kg unit.']
    return lines


def write_report(observations,panel,tests,sync,output,as_of=None,n_permutations=1999):
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    today=pd.Timestamp(as_of or dt.date.today()).normalize()
    panel.to_csv(output/'regional_annual_panel.csv',index=False)
    tests.to_csv(output/'regional_lag_tests.csv',index=False)
    sync.to_csv(output/'regional_synchrony.csv',index=False)
    regional_spread(sync).to_csv(output/'regional_spread.csv',index=False)
    lines=['# Regional monitoring','',f'Generated {today.date()}. Fixed pilot: '+', '.join(CONFIG['countries'])+'.',
           '', 'Observed dates, source coverage and projections remain separate. This is a research monitor, not a prophetic fulfillment score.',
           '', '| Source | Rows | Latest observed/assessment reference end | Latest projected reference end |', '|---|---:|---|---|']
    d=observations.copy()
    if d.empty:d=pd.DataFrame(columns=['dimensions','period_start','period_end','source_id','metric','country','published_at','value','numerator','denominator'])
    d['projected']=d.dimensions.map(is_projection)
    for source,g in d.groupby('source_id'):
        observed=g[~g.projected & (pd.to_datetime(g.period_start)<=today)]
        projected=g[g.projected]
        lines.append(f'| {source} | {len(g):,} | {observed.period_end.max() if len(observed) else "unavailable"} | {projected.period_end.max() if len(projected) else "—"} |')
    lines += ['', '## Food security: latest current assessment', '',
              '| Country | Reference window | IPC 3+ share of analyzed population | Population analyzed | Coverage |','|---|---|---:|---:|---|']
    ipc=d[d.metric.eq('ipc_phase_3plus_fraction') & ~d.projected & (pd.to_datetime(d.period_start)<=today)]
    for country in CONFIG['countries']:
        g=ipc[ipc.country.eq(country)].sort_values(['period_end','published_at'],na_position='first')
        if g.empty:lines.append(f'| {country} | unavailable | — | — | no fetched current assessment |');continue
        row=g.iloc[-1];expired=pd.Timestamp(row.period_end)<today
        lines.append(f'| {country} | {row.period_start}–{row.period_end} | {row.value:.1%} | {row.denominator:,.0f} | {"expired assessment; not present-day estimate" if expired else "current assessment window"}; country-wide territorial match unverified |')
    affordable=d[d.metric.eq('staple_kg_per_daily_wage') & d.dimensions.map(lambda x:is_food_commodity(dimensions(x).get('commodity','')))]
    lines += ['',f'Food affordability: {len(affordable):,} matched market/staple/month observations. Units: kg per daily non-qualified labor wage. No affordability estimate where matching wages are absent.']
    lines+=latest_monitor_tables(d,panel,today)
    lines += ['', '## Prespecified exploratory lag family','',
              f'{len(tests)} country/pair/lag cells; '+str(int(tests.status.eq('exploratory').sum()))+' estimable. Missing tests remain in correction family.',
              '', '| Country | Predictor → response | Lag years | n | r | Adjusted q |','|---|---|---:|---:|---:|---:|']
    for _,r in tests[tests.status.eq('exploratory')].sort_values('q_family').head(10).iterrows():
        lines.append(f'| {r.country} | {r.predictor} → {r.response} | {r.lag_years} | {r.n} | {r.r:+.3f} | {r.q_family:.3f} |')
    lines += ['', 'Signed-log annual residuals; separate linear time trends; 3-year block permutation with stable per-cell seeds; BH across the entire fixed family. Lag association does not identify causation. Net refugee-stock change is not new displacement.',
              '', 'IPC public export contains latest assessments and a phase-all population analyzed. Percentages are not shares of total national population. Territorial scope is not certified; assessments remain in this source table and are excluded from cross-source country lag inference until comparable geography is verified. Earlier snapshots accumulate prospectively.',
              '', '## Regional synchrony','',f'{int(sync.eligible.sum())} country-years meet all four fixed domains and baseline requirements. Ineligible years remain unavailable. Country-level calibration requires at least {CONFIG["minimum_test_years"]} contiguous complete years; independent circular shifts retain each domain time ordering while breaking cross-domain alignment. BH includes all fixed pilot countries. This is historical sensitivity, not a prospective rarity score.',
              '', 'Religious freedom source PSE refers to West Bank; excluded from the combined-territory annual panel. WHO sentinel series need 26 weeks/year. Country coverage varies across source definitions.',
              '', '| Country | Calibration years | Country-level joint p | Status |','|---|---:|---:|---|']
    for _,r in sync.drop_duplicates('country').iterrows():
        ptext=f'{r.p_joint:.3f}' if pd.notna(r.p_joint) else 'unavailable'
        lines.append(f'| {r.country} | {r.calibration_n_years} | {ptext} | {r.calibration_status} |')
    lines+=['']+israel_summary()+['','See MONITORING.md for source commands, scope and interpretation.']
    if observations.empty:lines.insert(6,'No source observations available. All regional estimates remain unavailable; run refresh_monitoring.py.')
    (output/'monitoring_report.md').write_text('\n'.join(lines)+'\n')
    fingerprint=hashlib.sha256(pd.util.hash_pandas_object(observations,index=False).to_numpy().tobytes()).hexdigest()
    manifest={'schema_version':1,'generated_date':str(today.date()),'config':CONFIG,'n_permutations':n_permutations,
              'input_observation_rows':len(observations),'observation_table_fingerprint':fingerprint,
              'annual_panel_rows':len(panel),'registered_lag_tests':len(tests),
              'estimable_lag_tests':int(tests.status.eq('exploratory').sum()),'eligible_synchrony_country_years':int(sync.eligible.sum()),
              'calibrated_synchrony_countries':int(sync.drop_duplicates('country').p_joint.notna().sum()),
              'design':'Historical exploratory fixed pilot. Dates are observation reference periods, not a reconstruction of release-time availability. IPC geography requires explicit matching. Missing is not zero.'}
    (output/'analysis_manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')


def main():
    import argparse
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--data-dir',type=Path,default=BASE/'data/monitoring')
    ap.add_argument('--out',type=Path,default=BASE/'results/monitoring')
    ap.add_argument('--permutations',type=int,default=1999)
    args=ap.parse_args()
    d=load_observations(args.data_dir)
    panel=build_annual_panel(d);tests=lag_tests(panel,n_permutations=args.permutations)
    sync=synchrony(panel,n_permutations=args.permutations)
    write_report(d,panel,tests,sync,args.out,n_permutations=args.permutations)
    print(f'{len(panel)} annual observations; {len(tests)} registered lag tests; report {args.out/"monitoring_report.md"}')


if __name__=='__main__':main()
