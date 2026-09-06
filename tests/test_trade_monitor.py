"""Exercise separate report writer with real models and synthetic sources."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import pandas as pd
from monitoring import trade_monitor as M, trade_analysis as T
from tests.test_trade_analysis import panel_fixture


class TradeReportTests(unittest.TestCase):
    def test_report_keeps_passing_cells_exclusions_and_input_hashes(self):
        food,shipping,fx,climate=panel_fixture()
        for key,value in {'currencies':'ILS','expected_members':3,'official_currency':'ILS'}.items():food[key]=value
        missing=[]
        for country in T.COUNTRIES[1:]:
            frame=food.copy();frame.country=country;frame.food_log_yoy=float('nan');frame.fx_currency_compatible=False;frame.currencies='';frame.expected_members=0;missing.append(frame)
        food=pd.concat([food,*missing]);shipping['name']=shipping.predictor.map(T.SHIPPING_NAMES);shipping['daily_mean_tons']=100.
        fx['official_fx_yoy_pct']=100*(fx.official_fx_log_yoy.map(__import__('math').exp)-1)
        grain=pd.DataFrame({'country':['ISR'],'period_end':['2023-12-31'],'period_start':['2021-01-01'],'usable':[True],'start_year':[2021],'end_year':[2023],'value':[50.],'flag':['E']})
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'source';source.mkdir();(source/'manifest.json').write_text('{}')
            with patch.object(M.trade_sources,'load_snapshot',return_value=({'daily.csv':pd.DataFrame()},{'snapshot_id':'shipping'})), \
                 patch.object(M.economic_sources,'load_snapshot',return_value=({'official_fx_monthly.csv':pd.DataFrame(),'cereal_dependence.csv':grain},{'snapshot_id':'economic'})), \
                 patch.object(M.climate_indices,'load_snapshot',return_value=({'monthly.csv':climate},{'snapshot_id':'climate'})), \
                 patch.object(T,'monthly_food',return_value=(food,pd.DataFrame(columns=['member']),pd.DataFrame(columns=['reason']))), \
                 patch.object(T,'monthly_shipping',return_value=shipping),patch.object(T,'monthly_fx',return_value=fx):
                manifest=M.run(pd.DataFrame(),root/'out',as_of='2026-01-15',shipping_root=source,economic_root=source,climate_root=source)
            self.assertEqual(manifest['planned_fits'],192);self.assertGreater(manifest['passing_fits'],0)
            report=(root/'out/trade_report.md').read_text();self.assertIn('2021–2023 / 50.0%',report)
            self.assertIn('| PSE | Unavailable | Unavailable | No eligible basket |',report)
            self.assertIn('not causal or prophetic-fulfillment claims',report)
            for name,record in manifest['outputs'].items():self.assertEqual(M.file_digest(root/'out'/name),record['sha256'])
