"""Calibration, unit conversion and lead-specific weather feature regression checks."""
import unittest
import numpy as np
import pandas as pd
from forecast_weather import daily, VARIABLES
from uncertainty import residual_width, attach
from weather_model import features
from tests.test_forecast import fixture


class ForecastAdditionsTests(unittest.TestCase):
    def test_residual_quantile_uses_finite_sample_rank_and_nonnegative_bounds(self):
        self.assertEqual(residual_width(np.arange(1,101),.90),91)
        with self.assertRaises(ValueError):residual_width([1,2])
        result=attach(pd.DataFrame({'horizon':[1],'predicted_AQI':[5.]}),
                      pd.DataFrame({'horizon':[1],'half_width':[10.],'nominal_coverage':[.9]}))
        self.assertEqual(result.lower_AQI.iloc[0],0.)
        self.assertEqual(result.upper_AQI.iloc[0],15.)

    def test_forecast_units_precision_coverage_and_timezone(self):
        hours=pd.date_range('2026-01-01',periods=24,freq='h')
        data={'utc_offset_seconds':-18000,'hourly':{'time':hours.astype(str).tolist()},'hourly_units':{}}
        for variable,unit in zip(VARIABLES.values(),['°C','%','km/h','hPa']):
            data['hourly'][variable]=[1000.]*24
            data['hourly_units'][variable]=unit
        result=daily(data)
        self.assertEqual(result.pressure_kpa.iloc[0],100.)
        data['hourly']['temperature_2m'][:7]=[None]*7
        self.assertTrue(np.isnan(daily(data).temperature_c.iloc[0]))
        data['utc_offset_seconds']=0
        with self.assertRaises(ValueError):daily(data)

    def test_archived_weather_joins_target_day_and_matching_horizon(self):
        frame=fixture().rename(columns={'PM25':'AQI'})
        rows=[]
        for h in [1,7]:
            for date in frame.index:
                rows.append({'Date':date,'horizon':h,**{name:float(date.day+h*100) for name in VARIABLES}})
        weather=pd.DataFrame(rows)
        x,valid=features(frame,7,weather)
        origin=frame.index[25]
        self.assertEqual(x.loc[origin,'forecast_temperature_c'],float((origin+pd.Timedelta(days=7)).day+700))
        self.assertTrue(valid.loc[origin])
        altered=weather.copy()
        altered.loc[altered.horizon.eq(1),'temperature_c']=9999
        again,_=features(frame,7,altered)
        pd.testing.assert_frame_equal(x,again)
