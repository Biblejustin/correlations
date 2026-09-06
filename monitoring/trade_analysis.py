"""Frozen monthly trade/FX and local food-price comparisons; exploratory only."""
from __future__ import annotations

import hashlib
import itertools
import json
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.api as sm

from monitoring.feeds import is_food_commodity
from statistical_helpers import bh_adjust

PLAN_PATH=Path(__file__).with_name('trade_plan.json')
COUNTRIES=('ISR','PSE','LBN','UKR','SDN','ETH','SOM','YEM')
PREDICTORS=('suez_transit_decline_yoy','bab_el_mandeb_transit_decline_yoy','hormuz_transit_decline_yoy','official_fx_log_yoy')
FITS=('time_season_baseline','fx_climate_adjusted')
LAGS=(0,1,3)
SHIPPING_NAMES=dict(zip(PREDICTORS[:3],('Suez Canal','Bab el-Mandeb','Strait of Hormuz')))
MIN_MONTHS=60
MIN_DF=8
HAC_LAGS=12
FAMILY_SIZE=192


def plan():
    value=json.loads(PLAN_PATH.read_text())
    fixed={'countries':list(COUNTRIES),'predictors':list(PREDICTORS),'fits':list(FITS),'monthly_lags':list(LAGS),
        'minimum_contiguous_months':MIN_MONTHS,'minimum_residual_degrees_of_freedom':MIN_DF,'hac_maxlags':HAC_LAGS,
        'family_size':FAMILY_SIZE,'fdr_alpha':.05,'food_baseline_years':[2015,2019],
        'food_minimum_baseline_months':24,'food_minimum_series':3,'food_required_coverage':.7}
    for key,expected in fixed.items():
        if value.get(key)!=expected:raise ValueError(f'Trade rule differs from frozen design: {key}')
    return value


def _last_month(as_of):
    stamp=pd.Timestamp(as_of)
    if pd.isna(stamp):raise ValueError('Trade reference timestamp is missing')
    if stamp.tzinfo:stamp=stamp.tz_convert('America/Chicago').tz_localize(None)
    return stamp.to_period('M')-1


def monthly_food(observations, as_of):
    """Same fixed price basket as original annual panel; explicit monthly gaps."""
    p=plan();last=_last_month(as_of)
    frame=observations[observations.metric.eq('food_price')].copy() if 'metric' in observations else pd.DataFrame()
    series=[];members=[];diagnostics=[]
    if len(frame):
        required={'country','period_start','period_end','dimensions','value','frequency'}
        if not required<=set(frame):raise ValueError('Missing normalized food-price columns')
        good=[]
        for index,row in frame.iterrows():
            try:
                d=json.loads(row.dimensions) if isinstance(row.dimensions,str) else dict(row.dimensions)
                if row.country not in COUNTRIES:continue
                if str(d.get('pricetype','')).lower()!='retail' or not is_food_commodity(d.get('commodity','')):continue
                if not d.get('currency') or not d.get('unit'):raise ValueError('missing currency or unit')
                if str(d.get('type','actual')).lower() not in {'actual','current','observed'}:raise ValueError('projected price')
                start,end=pd.Timestamp(row.period_start),pd.Timestamp(row.period_end)
                month=start.to_period('M')
                if row.frequency!='monthly' or start!=month.start_time or end!=month.end_time.normalize():raise ValueError('incomplete monthly period')
                if month>last:continue
                if not np.isfinite(float(row.value)) or float(row.value)<=0:raise ValueError('invalid price')
                identity={k:v for k,v in d.items() if k not in {'source_quote_ordinal','source_quote_date'}}
                good.append({'country':row.country,'month':month,'value':float(row.value),'dimensions':json.dumps(identity,sort_keys=True),'currency':d['currency']})
            except (ValueError,TypeError,KeyError) as error:
                diagnostics.append({'source_row':str(index),'country':row.country,'reason':str(error)})
        if good:
            for (country,identity),group in pd.DataFrame(good).groupby(['country','dimensions'],sort=True):
                values=group.groupby('month').value.median()
                baseline=values[(values.index.year>=2015)&(values.index.year<=2019)]
                identifier=hashlib.sha256((country+identity).encode()).hexdigest()
                eligible=len(baseline)>=24
                members.append({'country':country,'series_id':identifier,'dimensions':identity,'currency':group.currency.iloc[0],
                                'baseline_months':len(baseline),'eligible':eligible})
                if not eligible:continue
                values=values.reindex(pd.period_range(values.index.min(),last,freq='M'))
                changes=np.log(values/values.shift(12))
                for month,value in changes.items():
                    if pd.notna(value):series.append({'country':country,'month':str(month),'value':float(value),'series_id':identifier})
    members=pd.DataFrame(members,columns=['country','series_id','dimensions','currency','baseline_months','eligible'])
    valid=members[members.eligible] if len(members) else members
    points=pd.DataFrame(series,columns=['country','month','value','series_id'])
    rows=[]
    for country in COUNTRIES:
        fixed=valid[valid.country.eq(country)];expected=len(fixed);currencies=sorted(fixed.currency.unique())
        fx_currency=p['exchange_rate']['food_currency_match'][country]
        matched=bool(expected and currencies==[fx_currency])
        source=points[points.country.eq(country)]
        groups={m:g for m,g in source.groupby('month')}
        for month in pd.period_range('2015-01',last,freq='M'):
            group=groups.get(str(month));n=len(group) if group is not None else 0
            enough=expected>0 and n>=max(3,int(np.ceil(.7*expected)))
            value=float(group.value.median()) if enough else np.nan
            rows.append({'country':country,'month':str(month),'food_log_yoy':value,
                'food_yoy_pct':float(100*np.expm1(value)) if enough else np.nan,
                'observed_members':n,'expected_members':expected,'member_coverage':n/expected if expected else np.nan,
                'currencies':';'.join(currencies),'official_currency':fx_currency,'fx_currency_compatible':matched,
                'status':'eligible' if enough else 'incomplete fixed price basket' if expected else 'no eligible fixed price basket'})
    return pd.DataFrame(rows),members,pd.DataFrame(diagnostics,columns=['source_row','country','reason'])


def monthly_fx(frame, as_of):
    """Monthly official-rate log changes; no annual interpolation or gap bridging."""
    last=_last_month(as_of);rows=[]
    if frame.duplicated(['country','month']).any():raise ValueError('Duplicate monthly FX source rows')
    for country in COUNTRIES:
        g=frame[frame.country.eq(country)].copy()
        values=pd.Series(g.value.to_numpy(dtype=float),index=pd.PeriodIndex(g.month,freq='M'))
        usable=g.usable.to_numpy(dtype=bool)
        values.iloc[np.flatnonzero(~usable)]=np.nan
        values=values.reindex(pd.period_range('2015-01',last,freq='M'))
        values=values.where(np.isfinite(values)&values.gt(0))
        changes=np.log(values/values.shift(12))
        for month in values.index:
            rows.append({'country':country,'month':str(month),'official_fx':values.loc[month],
                         'official_fx_log_yoy':changes.loc[month],
                         'official_fx_yoy_pct':100*np.expm1(changes.loc[month]) if pd.notna(changes.loc[month]) else np.nan})
    return pd.DataFrame(rows)


def monthly_shipping(daily, as_of, *, date_column='date', name_column='chokepoint', value_column='capacity'):
    """Aggregate all days, after the predeclared seven-day source lag."""
    plan();bound=pd.Timestamp(as_of)
    bound=bound.tz_localize('UTC') if bound.tzinfo is None else bound.tz_convert('UTC')
    if not {date_column,name_column,value_column}<=set(daily):raise ValueError('Missing shipping daily fields')
    d=daily.copy();d['_date']=pd.to_datetime(d[date_column],utc=True,errors='raise').dt.normalize()
    d['_month']=d['_date'].dt.tz_localize(None).dt.to_period('M')
    if d.duplicated([name_column,'_date']).any():raise ValueError('Duplicate shipping day')
    rows=[]
    for predictor,name in SHIPPING_NAMES.items():
        subset=d[d[name_column].eq(name)]
        grouped={month:frame for month,frame in subset.groupby('_month')}
        for month in pd.period_range('2019-01',_last_month(as_of),freq='M'):
            group=grouped.get(month)
            expected=month.days_in_month
            old_enough=(month.end_time.tz_localize('UTC')+pd.Timedelta(days=7))<=bound
            values=pd.to_numeric(group[value_column],errors='coerce') if group is not None else pd.Series(dtype=float)
            observed=np.isfinite(values)&values.ge(0)
            if group is not None and 'source_observed' in group:
                observed &= group.source_observed.eq(True)
            n=int(observed.sum())
            usable=observed.copy()
            if group is not None and 'usable' in group:
                usable &= group.usable.eq(True)
            complete=bool(n==expected and usable.all() and old_enough)
            rows.append({'name':name,'predictor':predictor,'month':str(month),'observed_days':n,'expected_days':expected,
                'reporting_lag_complete':old_enough,'daily_mean_tons':float(values.mean()) if complete else np.nan,
                'status':'eligible' if complete else 'reporting lag' if not old_enough else 'incomplete or invalid daily coverage'})
    result=pd.DataFrame(rows);result['transit_decline_yoy']=np.nan
    for _,indices in result.groupby('predictor').groups.items():
        values=result.loc[indices].set_index('month').daily_mean_tons
        for index in indices:
            month=pd.Period(result.at[index,'month'],freq='M');current=result.at[index,'daily_mean_tons'];previous=values.get(str(month-12),np.nan)
            if np.isfinite(current) and np.isfinite(previous) and previous>0:result.at[index,'transit_decline_yoy']=1-current/previous
    return result


def _longest(frame):
    finite=frame.replace([np.inf,-np.inf],np.nan).dropna()
    if finite.empty:return finite
    ordinal=finite.index.astype('int64')
    groups=np.cumsum(np.r_[True,np.diff(ordinal)!=1])
    runs=[x for _,x in finite.groupby(groups)]
    return max(runs,key=len)  # chronological order breaks ties toward earliest.


def _controls(months):
    ordinal=months.astype('int64').to_numpy(dtype=float)
    columns=[np.ones(len(months)),ordinal-ordinal.mean()];names=['intercept','linear_month_trend']
    occupied=sorted(set(months.month))
    for month in occupied[1:]:columns.append((months.month==month).astype(float));names.append(f'month_{month}')
    return np.column_stack(columns),names


def _fit(frame, controls, names, label):
    row={'fit':label,'n':len(frame),'status':'unavailable','reason':'','control_columns':';'.join(names),
         'df_resid':np.nan,'partial_r':np.nan,'beta':np.nan,'beta_ci_low':np.nan,'beta_ci_high':np.nan,'p_hac':np.nan}
    if len(frame)<MIN_MONTHS:row['reason']='insufficient_contiguous_months';return row
    x,y=frame.x.to_numpy(),frame.y.to_numpy();xs,ys=x.std(),y.std()
    if min(xs,ys)<=1e-12:row['reason']='constant_series';return row
    x=(x-x.mean())/xs;y=(y-y.mean())/ys
    scale=np.sqrt(np.mean(controls**2,axis=0))
    if np.any(scale<=1e-12):row['reason']='singular_controls';return row
    controls=controls/scale
    if np.linalg.matrix_rank(controls)!=controls.shape[1]:row['reason']='singular_controls';return row
    rx=x-controls@np.linalg.lstsq(controls,x,rcond=None)[0];ry=y-controls@np.linalg.lstsq(controls,y,rcond=None)[0]
    if min(rx.std(),ry.std())<=1e-10:row['reason']='constant_after_controls';return row
    design=np.column_stack([controls,x]);rank=np.linalg.matrix_rank(design);row['df_resid']=len(frame)-rank
    if rank!=design.shape[1] or np.linalg.cond(design)>1e10:row['reason']='singular_or_ill_conditioned_design';return row
    if row['df_resid']<MIN_DF:row['reason']='insufficient_residual_df';return row
    result=sm.OLS(y,design).fit(cov_type='HAC',cov_kwds={'maxlags':HAC_LAGS,'use_correction':True},use_t=True)
    if np.std(result.resid)<=1e-10 or not np.isfinite(result.pvalues[-1]) or result.bse[-1]<=0:row['reason']='invalid_residual_variance_or_covariance';return row
    lo,hi=result.conf_int()[-1]*ys/xs
    row.update(status='eligible',partial_r=float(np.corrcoef(rx,ry)[0,1]),beta=float(result.params[-1]*ys/xs),
        beta_ci_low=float(lo),beta_ci_high=float(hi),p_hac=float(result.pvalues[-1]))
    return row


def compare(food, shipping, fx, climate_monthly, as_of):
    p=plan();last=_last_month(as_of);rows=[]
    climate=climate_monthly[climate_monthly['index'].isin(['rni','dmi']) & climate_monthly.usable].copy()
    climate['month']=pd.PeriodIndex(pd.to_datetime(climate.period_start),freq='M')
    if climate.duplicated(['index','month']).any():raise ValueError('Duplicate monthly climate periods')
    ocean=climate.pivot(index='month',columns='index',values='value').reindex(columns=['rni','dmi'])
    for country,predictor,lag in itertools.product(COUNTRIES,PREDICTORS,LAGS):
        local=food[food.country.eq(country)].copy();local.index=pd.PeriodIndex(local.month,freq='M')
        rates=fx[fx.country.eq(country)].copy();rates.index=pd.PeriodIndex(rates.month,freq='M')
        if not local.index.is_unique or not rates.index.is_unique:raise ValueError('Duplicate monthly panel values')
        if predictor=='official_fx_log_yoy':x=rates.official_fx_log_yoy.copy()
        else:
            transport=shipping[shipping.predictor.eq(predictor)];x=pd.Series(transport.transit_decline_yoy.to_numpy(),index=pd.PeriodIndex(transport.month,freq='M'))
        x.index=x.index+lag
        columns={'x':x,'y':local.food_log_yoy,'rni_response':ocean.rni,'dmi_response':ocean.dmi}
        if lag:
            for key in ['rni','dmi']:
                shifted=ocean[key].copy();shifted.index=shifted.index+lag;columns[key+'_predictor']=shifted
        if predictor!='official_fx_log_yoy' or lag:
            columns['fx_response']=rates.official_fx_log_yoy
        if predictor!='official_fx_log_yoy' and lag:
            shifted=rates.official_fx_log_yoy.copy();shifted.index=shifted.index+lag;columns['fx_predictor']=shifted
        frame=pd.DataFrame(columns);frame=frame.loc[frame.index<=last]
        compatible=bool(len(local) and local.fx_currency_compatible.all())
        if not compatible:frame['y']=np.nan
        frame=_longest(frame);months=frame.index
        base,names=_controls(months) if len(frame) else (np.empty((0,0)),[])
        added=[x for x in frame.columns if x not in ['x','y']]
        adjusted=np.column_stack([base,frame[added].to_numpy()])
        identity={'country':country,'predictor':predictor,'response':'retail_food_log_yoy','lag_months':lag,
            'pair_id':f'{country}__{predictor}__lag{lag}','sample_start':str(months.min()) if len(frame) else '',
            'sample_end':str(months.max()) if len(frame) else '', 'sample_months':';'.join(map(str,months)),
            'sample_sha256':hashlib.sha256(frame.to_csv(float_format='%.17g').encode()).hexdigest(),
            'currency_compatible':compatible}
        for design,labels,label in [(base,names,FITS[0]),(adjusted,names+added,FITS[1])]:
            row=_fit(frame,design,labels,label)
            if not compatible:row['reason']='no_verified_single_currency_food_basket'
            rows.append({**identity,**row})
    result=pd.DataFrame(rows)
    assert len(result)==FAMILY_SIZE
    result['q_family']=bh_adjust(result.p_hac.fillna(1.0).to_numpy());result['family_size']=FAMILY_SIZE
    result['reject_fdr']=result.status.eq('eligible')&result.q_family.lt(.05)
    result.attrs={'plan_sha256':hashlib.sha256(PLAN_PATH.read_bytes()).hexdigest(),'plan':p,
        'as_of':pd.Timestamp(as_of).isoformat(),'last_complete_month':str(last),
        'interpretation':'Historical exploratory associations; repeated shipping exposures and common crisis shocks limit causal interpretation. Official FX may differ from market rates. Pointwise slope intervals are not simultaneous.'}
    return result
