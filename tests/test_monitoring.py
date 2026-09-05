"""Integrity gates for regional source semantics and calibrated analysis artifacts."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

from monitoring import feeds as F, analysis as A


def annual(country,year,metric,value,unit='people',dimensions=None):
    return F.obs(country,f'{year}-01-01',f'{year}-12-31',metric,value,unit,'fixture','https://example.org',dimensions=dimensions)


class SourceSemantics(unittest.TestCase):
    def test_ipc_denominator_is_population_analyzed(self):
        raw=pd.DataFrame([
            {'Country':'ETH','Date of analysis':'May 2021','Validity period':'current','From':'2021-05-01','To':'2021-06-30','Phase':'all','Number':500,'Percentage':1,'Total country population':1000},
            {'Country':'ETH','Date of analysis':'May 2021','Validity period':'current','From':'2021-05-01','To':'2021-06-30','Phase':'3+','Number':150,'Percentage':.3,'Total country population':1000},
        ])
        with patch.object(F,'hdx_resource',return_value=(raw,'https://example.org','2021-05-01')):
            output=F.ipc(None,['ETH'],2000)
        row=output.iloc[0]
        self.assertEqual(row.denominator,500)
        self.assertAlmostEqual(row.value,row.numerator/row.denominator)
        self.assertFalse(json.loads(row.dimensions)['geography_comparable_to_country'])
        F.validate_observations(output)

    def test_affordability_requires_same_market_currency_and_kg(self):
        columns=['date','market_id','commodity','commodity_id','unit','priceflag','pricetype','currency','price']
        raw=pd.DataFrame([
            ['2024-01-15',1,'Wage (non-qualified labour)',277,'Day','actual','Retail','AAA',500],
            ['2024-01-15',1,'Wheat',1,'50 KG','actual','Retail','AAA',1000],
            ['2024-01-15',2,'Wheat',1,'KG','actual','Retail','AAA',1],
            ['2024-01-15',1,'Wheat',1,'KG','actual','Retail','BBB',1],
            ['2024-01-15',1,'Wheat',1,'bag','actual','Retail','AAA',1],
            ['2024-01-15',1,'Wheat',1,'KG','forecast','Retail','AAA',1],
            ['2024-01-15',1,'Milling cost (wheat)',99,'KG','actual','Retail','AAA',1],
        ],columns=columns)
        output=F.normalize_wfp(raw,'ETH','https://example.org')
        affordable=output[output.metric.eq('staple_kg_per_daily_wage')]
        self.assertEqual(len(affordable),1)
        self.assertEqual(affordable.iloc[0].value,25)
        self.assertEqual(output.metric.eq('labor_wage').sum(),1)
        self.assertFalse(output[output.metric.eq('food_price')].dimensions.str.contains('Wage').any())

    def test_duplicate_ratio_with_different_denominator_is_conflict(self):
        rows=[F.obs('ISR','2024-01-01','2024-01-07','influenza_positivity',.1,'positive_fraction','who','https://example.org',numerator=n,denominator=10*n,frequency='weekly') for n in [10,100]]
        with self.assertRaisesRegex(ValueError,'Conflicting duplicate'):F.validate_observations(F.frame(rows))

    def test_missing_dates_and_units_refused(self):
        row=annual('ISR',2024,'population',100)
        bad=F.frame([row]);bad.loc[0,'period_start']=None
        with self.assertRaisesRegex(ValueError,'Missing observation date'):F.validate_observations(bad)
        bad=F.frame([row]);bad.loc[0,'unit']=None
        with self.assertRaisesRegex(ValueError,'Missing observation unit'):F.validate_observations(bad)


class RegionalPanelRules(unittest.TestCase):
    def test_population_denominator_matches_country_and_year(self):
        rows=[annual('ISR',2023,'conflict_total_deaths',10,'deaths'),annual('ISR',2023,'population',100000),
              annual('ISR',2024,'conflict_total_deaths',20,'deaths'),annual('PSE',2024,'population',200000)]
        output=A.build_annual_panel(F.frame(rows),as_of='2026-01-01')
        rates=output[output.metric.eq('conflict_total_deaths_per_100k')]
        self.assertEqual(len(rates),1)
        self.assertEqual(rates.iloc[0].value,10)
        self.assertEqual(rates.iloc[0].year,2023)

    def test_ucdp_territory_mismatch_prevents_isr_and_prepartition_sudan_rates(self):
        rows=[]
        for country,year in [('ISR',2024),('SDN',2010),('SDN',2012)]:
            row=annual(country,year,'conflict_total_deaths',100,'deaths');row['source_id']='ucdp'
            rows.extend([row,annual(country,year,'population',100000)])
        panel=A.build_annual_panel(F.frame(rows),as_of='2026-01-01')
        rates=panel[panel.metric.eq('conflict_total_deaths_per_100k')]
        self.assertEqual(len(rates),1)
        self.assertEqual((rates.iloc[0].country,rates.iloc[0].year),('SDN',2012))

    def test_projections_future_year_and_unmatched_geography_excluded(self):
        rows=[annual('PSE',2024,'religious_freedom',2,'V-Dem latent interval score',{'source_country_name':'Palestine/West Bank'}),
              annual('ISR',2026,'population',100)]
        for typ,scope in [('current',False),('first projection',True)]:
            rows.append(F.obs('ETH','2024-06-01','2024-08-31','ipc_phase_3plus_fraction',.3,'fraction_of_population_analyzed','ipc','https://example.org',frequency='assessment',dimensions={'type':typ,'geography_comparable_to_country':scope}))
        self.assertTrue(A.build_annual_panel(F.frame(rows),as_of='2026-09-04').empty)

    def test_refugee_stock_change_never_bridges_missing_year(self):
        rows=[annual('ISR',2020,'refugees_origin_stock',10),annual('ISR',2022,'refugees_origin_stock',30),annual('ISR',2023,'refugees_origin_stock',15)]
        output=A.build_annual_panel(F.frame(rows),as_of='2026-01-01')
        changes=output[output.metric.eq('refugees_origin_stock_change')]
        self.assertEqual(len(changes),1)
        self.assertEqual(changes.iloc[0].value,-15)
        self.assertIn('not newly displaced',changes.iloc[0].quality_note)

    def test_food_basket_excludes_wages_and_does_not_fill_months(self):
        rows=[]
        for commodity in ['Wheat','Rice','Maize','Wage (non-qualified labour)']:
            for month in pd.date_range('2015-01-01','2020-12-01',freq='MS'):
                # Three foods double in 2020; the wage moves in opposite direction.
                value=(200 if month.year==2020 else 100) if 'Wage' not in commodity else (1 if month.year==2020 else 10000)
                desc={'market_id':'1','commodity':commodity,'commodity_id':commodity,'currency':'AAA','unit':'KG','pricetype':'Retail'}
                rows.append(F.obs('ETH',month.date(),(month+pd.offsets.MonthEnd()).date(),'food_price',value,'AAA/KG','wfp','https://example.org',frequency='monthly',dimensions=desc))
        raw=F.frame(rows);result=A.food_price_changes(raw)
        self.assertAlmostEqual(result[result.year.eq(2020)].iloc[0].value,100)
        # Remove ten baseline comparison months: do not fill them or turn prices into zeros.
        mask=(raw.period_start>='2019-01-01')&(raw.period_start<='2019-10-01')
        result=A.food_price_changes(raw[~mask])
        self.assertFalse(result.year.eq(2020).any())

    def test_sentinel_stream_and_week_coverage_not_pooled(self):
        rows=[]
        for source,nweeks,positive in [('SENTINEL',26,2),('NONSENTINEL',40,15)]:
            for date in pd.date_range('2024-01-01',periods=nweeks,freq='7D'):
                rows.append(F.obs('ISR',date.date(),(date+pd.Timedelta(days=6)).date(),'influenza_positivity',positive/20,'positive_fraction','who','https://example.org',frequency='weekly',numerator=positive,denominator=20,dimensions={'surveillance_origin':source}))
        result=A.build_annual_panel(F.frame(rows),as_of='2026-01-01')
        row=result[result.metric.eq('influenza_sentinel_positivity')].iloc[0]
        self.assertAlmostEqual(row.value,.1)
        self.assertEqual(row.n_observations,26)

    def test_annual_incompatible_units_fail(self):
        with self.assertRaisesRegex(ValueError,'Incompatible unit'):
            A.build_annual_panel(F.frame([annual('ISR',2024,'population',1,'thousands')]),as_of='2026-01-01')


class AnalysisArtifacts(unittest.TestCase):
    def config(self):
        return {**F.CONFIG,'countries':['ISR','PSE'],'baseline_years':[2000,2019],'minimum_baseline_years':10,'minimum_test_years':12}

    def test_lag_inference_never_bridges_gaps(self):
        rows=[]
        for year in list(range(2000,2008))+list(range(2010,2018)):
            for metric,value in [('conflict_total_deaths_per_100k',year%5),('refugees_origin_stock_change',year%3)]:
                rows.append(dict(country='ISR',year=year,metric=metric,value=value))
        result=A.lag_tests(pd.DataFrame(rows),config=self.config(),n_permutations=9)
        self.assertTrue(result.r.isna().all())
        self.assertTrue(result.q_family.eq(1).all())
        self.assertEqual(len(result),18)

    def test_missing_other_country_does_not_change_cell_permutation_seed(self):
        rng=np.random.default_rng(22);rows=[]
        for country in ['ISR','PSE']:
            for year in range(2000,2016):
                for metric in ['conflict_total_deaths_per_100k','refugees_origin_stock_change']:
                    rows.append(dict(country=country,year=year,metric=metric,value=float(rng.normal())))
        panel=pd.DataFrame(rows)
        full=A.lag_tests(panel,config=self.config(),n_permutations=19)
        partial=A.lag_tests(panel[panel.country.eq('PSE')],config=self.config(),n_permutations=19)
        np.testing.assert_allclose(full[full.country.eq('PSE')].p_block,partial[partial.country.eq('PSE')].p_block,equal_nan=True)

    def test_synchrony_calibration_requires_all_fixed_domains(self):
        years=np.arange(2000,2030)
        series=np.sin(years)+np.where(years>=2026,8,0)
        rows=[]
        names=['conflict_total_deaths_per_100k','retail_staple_price_yoy_pct','influenza_sentinel_positivity','religious_freedom']
        for metric in names:
            rows.extend(dict(country='ISR',year=int(year),metric=metric,value=float((-1 if metric=='religious_freedom' else 1)*value)) for year,value in zip(years,series))
        data=pd.DataFrame(rows)
        result=A.synchrony(data,config=self.config(),n_permutations=39)
        calibrated=result[result.country.eq('ISR')].iloc[0]
        self.assertEqual(calibrated.calibration_n_years,30)
        self.assertGreater(calibrated.p_joint,0)
        self.assertLessEqual(calibrated.p_joint,1)
        self.assertIn('circular shifts',calibrated.calibration_status)
        missing=result[result.country.eq('PSE')].iloc[0]
        self.assertTrue(pd.isna(missing.p_joint))
        self.assertFalse(missing.eligible)
        result=A.synchrony(data[data.metric.ne('influenza_sentinel_positivity')],config=self.config(),n_permutations=39)
        self.assertFalse(result.eligible.any())
        self.assertTrue(result.p_joint.isna().all())

    def test_empty_monitor_still_writes_honest_artifacts(self):
        observations=pd.DataFrame()
        panel=A.build_annual_panel(observations)
        tests=A.lag_tests(panel,n_permutations=9)
        sync=A.synchrony(panel,n_permutations=9)
        with tempfile.TemporaryDirectory() as directory:
            A.write_report(observations,panel,tests,sync,directory)
            self.assertTrue((Path(directory)/'regional_annual_panel.csv').exists())
            report=(Path(directory)/'monitoring_report.md').read_text()
            self.assertIn('0 estimable',report)
            self.assertIn('unavailable',report)
            self.assertEqual(len(pd.read_csv(Path(directory)/'regional_lag_tests.csv')),72)

    def test_affordability_example_selection_never_chooses_largest_value(self):
        rows=[]
        for start,market,value in [('2024-01-01','A',1),('2024-01-01','B',100),('2023-01-01','000',999)]:
            rows.append(F.obs('ETH',start,str(pd.Timestamp(start)+pd.offsets.MonthEnd())[:10],
                              'staple_kg_per_daily_wage',value,'kg/day_wage','wfp','https://example.org',
                              frequency='monthly',dimensions={'market_id':market,'commodity':'Wheat','currency':'AAA'}))
        observations=F.frame(rows);observations['projected']=False
        text='\n'.join(A.latest_monitor_tables(observations,pd.DataFrame(columns=A.PANEL_COLUMNS),pd.Timestamp('2026-01-01')))
        self.assertIn('| ETH | A | Wheat | 2024-01 | 1.00 |',text)
        self.assertNotIn('| ETH | B |',text)
        self.assertNotIn('| ETH | 000 |',text)

    def test_central_israel_summary_is_self_contained(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertIn('unavailable',' '.join(A.israel_summary(Path(directory))))
            root=Path(directory)/'israel-rain-agriculture'
            (root/'results').mkdir(parents=True)
            pd.DataFrame([{'start':1991,'rain':'total_mm','outcome':'yield_kg_ha','n':33,'r':.5,'q_hac_family30':.01}]).to_csv(root/'results/wheat_decomposition.csv',index=False)
            copied=' '.join(A.israel_summary(Path(directory)))
            self.assertIn('0.500',copied)
            self.assertIn('holdout starts 2025',copied)

if __name__=='__main__':unittest.main()
