"""Experimental weather-forecast challenger; never replaces the approved Ridge silently."""
import json
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from etl_contract import validate
from forecast import make_features
from forecast_weather import VARIABLES
from workflow import evaluate

CONFIG={'name':'ridge_forecast_weather_1','family':'ridge','alpha':1.}


def features(frame,h,weather):
    x,_,eligible=make_features(frame,h)
    subset=weather.loc[weather.horizon.eq(h)].set_index('Date')
    subset.index=pd.to_datetime(subset.index)
    if subset.index.has_duplicates:raise ValueError('Duplicate archived forecast dates')
    dates=frame.index+pd.Timedelta(days=h)
    for name in VARIABLES:
        x['forecast_'+name]=subset[name].reindex(dates).to_numpy()
    return x,eligible & x[['forecast_'+n for n in VARIABLES]].notna().all(axis=1)


def fit(frame,h,weather,boundary):
    x,eligible=features(frame,h,weather)
    target=frame.AQI.shift(-h)
    mask=eligible & target.notna() & (frame.index+pd.Timedelta(days=h+1)<=pd.Timestamp(boundary))
    if mask.sum()<100:raise ValueError('Insufficient archived forecasts to train weather challenger')
    model=make_pipeline(SimpleImputer(strategy='median',add_indicator=True,keep_empty_features=True),
        StandardScaler(),Ridge(alpha=1.)).fit(x.loc[mask],target.loc[mask])
    return model,x,eligible,mask


def forward(frame,weather,live):
    rows=[];origin=frame.index[-1]
    for h in range(1,8):
        model,x,_,_=fit(frame,h,weather,origin)
        date=origin+pd.Timedelta(days=h)
        if date not in live.index or live.loc[date,list(VARIABLES)].isna().any():
            raise ValueError('Incomplete forecast weather; challenger not issued')
        for field in VARIABLES:x.loc[origin,'forecast_'+field]=live.loc[date,field]
        rows.append({'origin':origin,'Date':date,'horizon':h,'model':CONFIG['name'],
                     'predicted_AQI':max(0.,float(model.predict(x.iloc[[-1]])[0]))})
    return pd.DataFrame(rows)


def experiment(output='reports/weather'):
    frame,lock=validate();output=Path(output)
    weather=pd.read_csv(output/'archived_weather.csv',parse_dates=['Date'])
    frame=frame.loc[:'2026-09-30']
    baseline_configs=[{'name':'ridge_1','family':'ridge','alpha':1.},
                      {'name':'persistence','family':'persistence'}]
    base,_=evaluate(frame,'2025-12-31','2026-09-30',baseline_configs)
    all_predictions=[]
    for h in range(1,8):
        model,x,eligible,mask=fit(frame,h,weather,'2025-12-31')
        dates=frame.index+pd.Timedelta(days=h)
        target=frame.AQI.shift(-h)
        test=eligible & target.notna() & (frame.index>=pd.Timestamp('2025-12-31'))
        result=pd.DataFrame({'origin':frame.index[test],'Date':dates[test],'horizon':h,
                            'actual':target.loc[test].to_numpy(),
                            'predicted':np.maximum(0,model.predict(x.loc[test])),'model':CONFIG['name']})
        # Intersect with retained-model eligibility; every reported model shares pairs.
        keys=['origin','Date','horizon']
        available=base.loc[base.horizon.eq(h),keys].drop_duplicates()
        result=result.merge(available,on=keys,validate='one_to_one')
        matched=base.loc[base.horizon.eq(h)].merge(result[keys],on=keys,validate='many_to_one')
        all_predictions += [result,matched]
    predictions=pd.concat(all_predictions,ignore_index=True)
    rows=[]
    for (model,h),group in predictions.groupby(['model','horizon']):
        error=group.predicted-group.actual
        rows.append({'model':model,'horizon':h,'n':len(group),'MAE':error.abs().mean(),
                     'RMSE':np.sqrt((error**2).mean())})
    pd.DataFrame(rows).to_csv(output/'comparison.csv',index=False)
    predictions.to_csv(output/'predictions.csv',index=False)
    (output/'experiment.json').write_text(json.dumps({'dataset_lock':lock,'config':CONFIG,
        'fit_end':'2025-12-31','evaluation':'2026-01-01/2026-09-30',
        'retained_model':'ridge_1','promotion':'No automatic promotion; issue as experimental challenger',
        'availability_assumption':'Archived fixed h-day offsets are proxies for forecasts from origin day; exact vendor publication timestamps unavailable',
        'limitations':['Archive stitched fixed-lead fields are not exact stored issuance-time snapshots',
        'Retrospective comparison is exploratory, not proof of operational improvement',
        'Challenger has less training history (forecast fields available from 2024)',
        'Live retrieved forecast payload and retrieval time are archived before issuance'],
        'attribution':'Weather data by Open-Meteo.com (CC BY 4.0); model output, not station measurements'},indent=2)+'\n')


if __name__=='__main__':experiment()
