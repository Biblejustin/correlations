"""Missing-data, lag direction, fixed family and independent HAC checks."""
import json
import unittest
import numpy as np
import pandas as pd
from scipy.stats import t
from monitoring import trade_analysis as T


def panel_fixture():
    rng=np.random.default_rng(876);months=pd.period_range('2015-01','2025-12',freq='M');n=len(months)
    x=rng.normal(size=n);rate=rng.normal(size=n);rni=rng.normal(size=n);dmi=rng.normal(size=n)
    y=np.r_[0,2*x[:-1]]+rng.normal(scale=.25,size=n)
    food=pd.DataFrame({'country':'ISR','month':months.astype(str),'food_log_yoy':y,'fx_currency_compatible':True})
    shipping=pd.concat([pd.DataFrame({'predictor':p,'month':months.astype(str),'transit_decline_yoy':x}) for p in T.PREDICTORS[:3]])
    fx=pd.DataFrame({'country':'ISR','month':months.astype(str),'official_fx_log_yoy':rate})
    climate=pd.concat([pd.DataFrame({'index':p,'period_start':months.start_time,'value':v,'usable':True}) for p,v in [('rni',rni),('dmi',dmi)]])
    return food,shipping,fx,climate


class TradeTests(unittest.TestCase):
    def test_daily_missing_leap_month_zero_and_seven_day_lag(self):
        dates=pd.date_range('2019-01-01','2021-02-28');daily=pd.DataFrame({'date':dates,'chokepoint':'Suez Canal','capacity':100.,'source_observed':True,'usable':True})
        daily.loc[daily.date.dt.year.eq(2020),'capacity']=0
        result=T.monthly_shipping(daily,'2021-03-07T00:00:00Z')
        leap=result.query("predictor == 'suez_transit_decline_yoy' and month == '2020-02'").iloc[0]
        self.assertEqual(leap.observed_days,29);self.assertEqual(leap.transit_decline_yoy,1)
        latest=result.query("predictor == 'suez_transit_decline_yoy' and month == '2021-02'").iloc[0]
        self.assertFalse(latest.reporting_lag_complete);self.assertTrue(pd.isna(latest.daily_mean_tons))
        daily.loc[daily.date.eq('2020-02-29'),'capacity']=np.nan
        incomplete=T.monthly_shipping(daily,'2021-03-08T00:00:00Z').query("predictor == 'suez_transit_decline_yoy' and month == '2020-02'").iloc[0]
        self.assertEqual(incomplete.observed_days,28);self.assertTrue(pd.isna(incomplete.daily_mean_tons))
        daily.loc[daily.date.eq('2020-01-01'),'usable']=False
        self.assertTrue(pd.isna(T.monthly_shipping(daily,'2021-03-08').query("predictor == 'suez_transit_decline_yoy' and month == '2020-01'").daily_mean_tons.iloc[0]))

    def test_fixed_food_membership_exact_calendar_pairs_and_currency_gate(self):
        rows=[]
        for market in range(4):
            for i,month in enumerate(pd.period_range('2015-01','2020-12',freq='M')):
                rows.append({'metric':'food_price','country':'ISR','period_start':str(month.start_time.date()),'period_end':str(month.end_time.date()),
                    'dimensions':json.dumps({'market':str(market),'commodity':'Wheat','unit':'KG','currency':'ILS','pricetype':'retail'}),'value':100*1.01**i,'frequency':'monthly'})
        food,members,errors=T.monthly_food(pd.DataFrame(rows),'2021-01-15')
        self.assertEqual(len(members[members.eligible]),4);self.assertTrue(errors.empty)
        row=food.query("country == 'ISR' and month == '2020-12'").iloc[0]
        self.assertAlmostEqual(row.food_log_yoy,12*np.log(1.01));self.assertTrue(row.fx_currency_compatible)
        missing=[r for r in rows if not(r['period_start']=='2019-12-01' and json.loads(r['dimensions'])['market'] in ['0','1'])]
        changed=T.monthly_food(pd.DataFrame(missing),'2021-01-15')[0].query("country == 'ISR' and month == '2020-12'").iloc[0]
        self.assertEqual(changed.expected_members,4);self.assertEqual(changed.observed_members,2);self.assertTrue(pd.isna(changed.food_log_yoy))
        for r in rows:
            if json.loads(r['dimensions'])['market']=='0':r['dimensions']=r['dimensions'].replace('ILS','USD')
        mixed=T.monthly_food(pd.DataFrame(rows),'2021-01-15')[0].query("country == 'ISR'")
        self.assertFalse(mixed.fx_currency_compatible.any())

    def test_monthly_fx_never_bridges_missing_previous_year(self):
        frame=pd.DataFrame({'country':['ISR']*3,'month':['2020-01','2021-01','2021-02'],'value':[2.,4.,5.],'usable':[True]*3})
        result=T.monthly_fx(frame,'2021-03-15').query("country == 'ISR'").set_index('month')
        self.assertAlmostEqual(result.loc['2021-01','official_fx_log_yoy'],np.log(2))
        self.assertTrue(pd.isna(result.loc['2021-02','official_fx_log_yoy']))

    def test_lag_direction_paired_sample_and_full_family_missing_cells(self):
        food,shipping,fx,climate=panel_fixture()
        result=T.compare(food,shipping,fx,climate,'2026-01-15')
        self.assertEqual(len(result),192);self.assertEqual(result.family_size.unique().tolist(),[192])
        selected=result.query("country == 'ISR' and predictor == 'suez_transit_decline_yoy' and lag_months == 1")
        self.assertTrue(selected.partial_r.gt(.98).all());self.assertEqual(selected.sample_sha256.nunique(),1)
        self.assertEqual(selected.n.tolist(),[131,131])
        self.assertTrue(result.query("country == 'PSE'").p_hac.isna().all())
        # A control gap splits both fits, even the baseline fit that omits that control.
        climate.loc[climate.period_start.eq('2020-01-01'),'usable']=False
        gap=T.compare(food,shipping,fx,climate,'2026-01-15').query("country == 'ISR' and predictor == 'suez_transit_decline_yoy' and lag_months == 1")
        self.assertEqual(gap.n.nunique(),1);self.assertEqual(gap.sample_start.unique().tolist(),['2020-03'])
        food.fx_currency_compatible=False
        blocked=T.compare(food,shipping,fx,climate,'2026-01-15')
        self.assertFalse(blocked.status.eq('eligible').any())

    def test_hac_matches_manual_bartlett_sandwich_and_student_t(self):
        rng=np.random.default_rng(621);months=pd.period_range('2018-01',periods=90,freq='M');x=rng.normal(size=90);y=.2*x+rng.normal(size=90)
        frame=pd.DataFrame({'x':x,'y':y},index=months);control,names=T._controls(months)
        result=T._fit(frame,control,names,T.FITS[0]);design=np.column_stack([control,x]);inv=np.linalg.inv(design.T@design)
        beta=inv@design.T@y;resid=y-design@beta;score=design*resid[:,None];meat=score.T@score
        for lag in range(1,13):
            cross=score[lag:].T@score[:-lag];meat+=(1-lag/13)*(cross+cross.T)
        covariance=inv@meat@inv*90/(90-design.shape[1]);se=np.sqrt(covariance[-1,-1]);df=90-design.shape[1]
        self.assertAlmostEqual(result['beta'],beta[-1],places=10)
        self.assertAlmostEqual(result['p_hac'],2*t.sf(abs(beta[-1]/se),df),places=10)
        self.assertAlmostEqual(result['beta_ci_low'],beta[-1]-t.ppf(.975,df)*se,places=10)
        self.assertEqual(T._fit(frame.iloc[:59],*T._controls(months[:59]),T.FITS[0])['reason'],'insufficient_contiguous_months')
