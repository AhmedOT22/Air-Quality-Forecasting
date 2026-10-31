"""Data freshness, safe fallback and real Streamlit interaction tests."""
import copy
import os
import unittest
from pathlib import Path
from unittest.mock import patch
import pandas as pd
from dashboard_data import local_bundle,load_bundle,freshness,validate_bundle

try:
    import streamlit as st
    from streamlit.testing.v1 import AppTest
except ImportError:
    AppTest=None

ROOT=Path(__file__).resolve().parents[1]


class DashboardDataTests(unittest.TestCase):
    def test_old_success_is_not_labelled_current(self):
        bundle=local_bundle()
        label,_=freshness(bundle,now='2030-01-01T12:00:00Z')
        self.assertEqual(label,'Historical snapshot')

    def test_failed_refresh_keeps_historical_forecast_visible(self):
        bundle=local_bundle()
        bundle['status']={'publication_status':'blocked','attempted_at':'2026-10-31T12:00:00Z','error':'Missing source data'}
        validate_bundle(bundle)
        label,reason=freshness(bundle,now='2026-10-31T13:00:00Z')
        self.assertEqual(label,'Refresh blocked')
        self.assertIn('Missing source',reason)

    def test_unavailable_published_data_falls_back_with_notice(self):
        with patch('dashboard_data.published_bundle',side_effect=OSError('network unavailable')):
            bundle=load_bundle(True)
        self.assertEqual(bundle['source'],'Bundled snapshot')
        self.assertTrue(any('bundled snapshot' in w for w in bundle['warnings']))

    def test_latest_model_version_is_displayed_without_merging_issuances(self):
        bundle=local_bundle();old=bundle['forecast'].copy()
        new=old.copy();new['model_id']='new-version'
        new['issued_at']='2026-10-31T23:00:00+00:00'
        new['predicted_AQI']=new.predicted_AQI+1
        bundle['forecast']=pd.concat([old,new],ignore_index=True)
        result=validate_bundle(bundle)['forecast']
        self.assertEqual(len(result),len(old))
        self.assertTrue(result.model_id.eq('new-version').all())

    def test_duplicate_and_invalid_forecast_dates_are_rejected(self):
        bundle=local_bundle()
        for kind in ['duplicate','past']:
            changed=copy.deepcopy(bundle)
            if kind=='duplicate':changed['forecast']=pd.concat([changed['forecast'],changed['forecast'].iloc[[0]]])
            else:changed['forecast'].loc[0,'Date']=changed['forecast'].loc[0,'origin']
            with self.subTest(kind=kind),self.assertRaises(ValueError):validate_bundle(changed)


@unittest.skipIf(AppTest is None,'Install requirements-app.txt for Streamlit integration tests')
class DashboardUITests(unittest.TestCase):
    def setUp(self):
        self.environment=patch.dict(os.environ,{'AQI_DASHBOARD_OFFLINE':'1'})
        self.environment.start();self.addCleanup(self.environment.stop)
        st.cache_data.clear()

    def app(self):
        app=AppTest.from_file(str(ROOT/'app.py'),default_timeout=30).run()
        self.assertFalse(app.exception,[e.message for e in app.exception])
        return app

    def test_default_dashboard_and_horizon_and_challenger_controls(self):
        app=self.app()
        self.assertEqual(len(app.metric),4)
        self.assertEqual([t.label for t in app.tabs],['Forecast outlook','Observed history','Performance','About the model'])
        app.slider[0].set_value(3).run()
        app.toggle[1].set_value(True).run()
        app.toggle[0].set_value(False).run()
        self.assertFalse(app.exception)
        self.assertEqual(len(app.dataframe[0].value),3)

    def test_empty_live_scores_are_not_presented_as_zero_error(self):
        app=self.app()
        self.assertTrue(any('Waiting for observed outcomes' in info.value for info in app.info))
        self.assertTrue(any('79–87%' in info.value for info in app.info))
        app.selectbox[0].select('All data since 2020').run()
        app.selectbox[1].select('Ozone').run()
        self.assertFalse(app.exception)

    def test_blocked_refresh_is_visible_without_crashing(self):
        bundle=local_bundle()
        bundle['status']['publication_status']='blocked'
        bundle['status']['error']='Provider is unavailable'
        with patch('dashboard_data.load_bundle',return_value=bundle):
            # app imports the function at execution time.
            app=self.app()
        self.assertTrue(any('Refresh blocked' in w.value for w in app.warning))
        self.assertFalse(app.exception)
