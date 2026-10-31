"""Refresh observations, issue immutable forecasts and score genuinely future predictions."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

import numpy as np
import pandas as pd

from etl_contract import CONTRACT_VERSION, validate
from extend_data import EST, extend
from forecast import make_features, seasonal_lag
from workflow import forward

ROOT = Path(__file__).resolve().parent
REPORTS = ROOT / 'reports/operational'
HISTORY_COLUMNS = ['forecast_id','issued_at','origin','Date','horizon','model','model_id',
                   'predicted_AQI','lower_AQI','upper_AQI','nominal_coverage','persistence','weekly','evaluation_type','input_sha256','code_revision']
OBS_COLUMNS = ['Date','AQI','first_seen_at','input_sha256','verification_status']


def utc(value=None):
    stamp = pd.Timestamp(value or datetime.now(timezone.utc))
    if stamp.tzinfo is None:
        raise ValueError('Issuance time must include a timezone')
    return stamp.tz_convert('UTC')


def read_table(path, columns):
    return pd.read_csv(path).reindex(columns=columns) if path.exists() else pd.DataFrame(columns=columns)


def append_unique(previous, new, keys):
    if new.empty:
        return previous.copy()
    return pd.concat([previous, new] if not previous.empty else [new], ignore_index=True).drop_duplicates(keys, keep='first')


def freshness(frame, manifest, now):
    local_now = utc(now).tz_convert(EST).tz_localize(None)
    expected_origin = local_now.normalize() - pd.Timedelta(days=1)
    if frame.index[-1] != expected_origin:
        raise ValueError(f'Stale daily input: expected completed origin {expected_origin.date()}, got {frame.index[-1].date()}')
    latest = pd.Timestamp(manifest['latest_pollution_hour_est'])
    age = (local_now - latest - pd.Timedelta(hours=1)).total_seconds() / 3600
    if age < -1 or age > 6:
        raise ValueError(f'Pollution readings are stale or future-dated: age {age:.1f} hours')
    weather = ['temperature_c','humidity_pct','wind_speed_kmh','pressure_kpa']
    if frame[weather].iloc[-1].isna().any():
        raise ValueError('Latest completed-day weather is incomplete; no new forecast issued')
    _, _, eligible = make_features(frame, 1)
    if not eligible.iloc[-1]:
        raise ValueError('Latest origin lacks required AQI history; no stale-origin fallback')
    return {'origin': str(expected_origin.date()), 'pollution_age_hours': age}


def issue(frame, config, lock, now, history, code_revision, forecast_override=None, intervals=None):
    now = utc(now)
    today = now.tz_convert(EST).tz_localize(None).normalize()
    model_bytes = json.dumps(config, sort_keys=True).encode() + (ROOT / 'workflow.py').read_bytes() + (ROOT / 'forecast.py').read_bytes() + ((ROOT / 'weather_model.py').read_bytes() if config['name'].startswith('ridge_forecast') else b'')
    model_id = hashlib.sha256(model_bytes).hexdigest()[:16]
    # First issuance per origin/configuration wins, including on reruns with revised data.
    origin = frame.index[-1]
    expected_ids = [hashlib.sha256(f'{origin.date()}|{h}|{model_id}'.encode()).hexdigest()[:24] for h in range(1,8)]
    if set(expected_ids) <= set(history.forecast_id):
        return history.copy(), pd.DataFrame()
    future = forecast_override if forecast_override is not None else forward(frame, config)
    if intervals is not None:
        from uncertainty import attach
        future = attach(future, intervals)
    rows = []
    for row in future.itertuples():
        h = row.horizon
        rows.append({'forecast_id': expected_ids[h-1], 'issued_at': now.isoformat(),
            'origin': str(origin.date()), 'Date': str(row.Date.date()), 'horizon': h,
            'model': row.model, 'model_id': model_id, 'predicted_AQI': row.predicted_AQI,
            'lower_AQI': getattr(row,'lower_AQI',np.nan), 'upper_AQI': getattr(row,'upper_AQI',np.nan),
            'nominal_coverage': getattr(row,'nominal_coverage',np.nan),
            'persistence': float(frame.AQI.iloc[-2]),
            'weekly': float(frame.AQI.iloc[-1-seasonal_lag(h, 1)]),
            'evaluation_type': 'prospective' if row.Date > today else 'same_day',
            'input_sha256': lock['input_sha256'], 'code_revision': code_revision})
    new = pd.DataFrame(rows)
    return append_unique(history, new, ['forecast_id']), new


def observe(frame, lock, now, previous):
    # AQI(D) can include next-morning ozone; score only after completed D+1.
    now = utc(now)
    today = now.tz_convert(EST).tz_localize(None).normalize()
    mature = frame.loc[frame.index <= today - pd.Timedelta(days=2)].dropna(subset=['AQI'])
    # Preserve first truth and record later value/quality revisions, including reversions.
    rows = pd.DataFrame({'Date': mature.index.strftime('%Y-%m-%d'), 'AQI': mature.AQI.to_numpy(),
        'first_seen_at': now.isoformat(), 'input_sha256': lock['input_sha256'],
        'verification_status': mature.verification_status.to_numpy()})
    if rows.empty:
        return previous.copy()
    if not previous.empty:
        last = previous.drop_duplicates('Date', keep='last').set_index('Date')
        unchanged = rows.apply(lambda row: row.Date in last.index and
            float(last.loc[row.Date, 'AQI']) == float(row.AQI) and
            last.loc[row.Date, 'verification_status'] == row.verification_status, axis=1)
        rows = rows.loc[~unchanged]
    return pd.concat([previous, rows] if not previous.empty else [rows], ignore_index=True)


def score(history, observations):
    columns = ['forecast_id','Date','horizon','model','issued_at','observed_at','actual_first',
        'actual_latest','verification_status','model_abs_error','persistence_abs_error','weekly_abs_error',
               'model_id','predicted_AQI','lower_AQI','upper_AQI','interval_covered']
    metrics_columns = ['model','model_id','horizon','n','MAE','RMSE','persistence_MAE','weekly_MAE','MAE_skill','interval_n','interval_coverage']
    if history.empty or observations.empty:
        return pd.DataFrame(columns=columns), pd.DataFrame(columns=metrics_columns)
    first = observations.drop_duplicates('Date', keep='first').rename(columns={'AQI':'actual_first','first_seen_at':'observed_at'})
    last = observations.drop_duplicates('Date', keep='last')[['Date','AQI']].rename(columns={'AQI':'actual_latest'})
    eligible = history.loc[history.evaluation_type.eq('prospective')].merge(
        first[['Date','actual_first','observed_at','verification_status']], on='Date', validate='many_to_one').merge(last,on='Date',validate='many_to_one')
    eligible = eligible.loc[pd.to_datetime(eligible.issued_at,utc=True) < pd.to_datetime(eligible.observed_at,utc=True)].copy()
    if eligible.empty:
        return pd.DataFrame(columns=columns), pd.DataFrame(columns=metrics_columns)
    for name, field in [('model','predicted_AQI'),('persistence','persistence'),('weekly','weekly')]:
        eligible[f'{name}_abs_error'] = (eligible[field] - eligible.actual_first).abs()
    for field in ('lower_AQI','upper_AQI'):
        if field not in eligible: eligible[field]=np.nan
    has_interval=eligible[['lower_AQI','upper_AQI']].notna().all(axis=1)
    eligible['interval_covered']=np.where(has_interval,eligible.actual_first.between(eligible.lower_AQI,eligible.upper_AQI).astype(float),np.nan)
    rows = []
    for (model, model_id, horizon), group in eligible.groupby(['model','model_id','horizon']):
        mae = group.model_abs_error.mean(); baseline = group.persistence_abs_error.mean()
        rows.append({'model': model, 'model_id':model_id, 'horizon': horizon, 'n': len(group), 'MAE': mae,
            'interval_n':int(group.interval_covered.notna().sum()),'interval_coverage':group.interval_covered.mean(),
            'RMSE': float(np.sqrt(((group.predicted_AQI-group.actual_first)**2).mean())),
            'persistence_MAE': baseline, 'weekly_MAE': group.weekly_abs_error.mean(),
            'MAE_skill': 1-mae/baseline if baseline > 0 else np.nan})
    return eligible[columns], pd.DataFrame(rows, columns=metrics_columns)


def monitor(scores, window=30, minimum=20):
    columns=['model','model_id','horizon','n','window_start','window_end','MAE','RMSE','persistence_MAE','MAE_skill']
    rows=[];alerts=[]
    if scores.empty:
        return pd.DataFrame(columns=columns),{'status':'collecting_observations','minimum_samples':minimum,'alerts':[]}
    for (model,version,h),group in scores.groupby(['model','model_id','horizon']):
        ordered=group.sort_values('Date');recent=ordered.tail(window)
        mae=recent.model_abs_error.mean();baseline=recent.persistence_abs_error.mean()
        rows.append({'model':model,'model_id':version,'horizon':int(h),'n':len(recent),
            'window_start':recent.Date.min(),'window_end':recent.Date.max(),'MAE':mae,
            'RMSE':float(np.sqrt((recent.model_abs_error**2).mean())),
            'persistence_MAE':baseline,'MAE_skill':1-mae/baseline if baseline>0 else np.nan})
        if len(recent)>=minimum and mae>baseline:
            alerts.append({'model':model,'horizon':int(h),'reason':'worse_than_persistence','n':len(recent)})
        prior=ordered.iloc[:-window].tail(window)
        if len(recent)>=minimum and len(prior)>=minimum and mae>1.5*prior.model_abs_error.mean():
            alerts.append({'model':model,'horizon':int(h),'reason':'MAE_exceeds_prior_window_by_50_percent','n':len(recent)})
    return pd.DataFrame(rows,columns=columns),{'status':'monitoring','minimum_samples':minimum,'alerts':alerts,
        'note':'Diagnostic thresholds, not statistical significance; overlapping forecasts are dependent'}


def atomic_csv(frame, path):
    temporary = path.with_suffix('.tmp')
    frame.to_csv(temporary, index=False)
    temporary.replace(path)


def run(refresh=True, now=None, reports=REPORTS):
    reports = Path(reports); reports.mkdir(parents=True, exist_ok=True)
    now_arg=now
    now = utc(now)
    # A failed refresh must leave a visible failure, never overwrite a successful forecast as current.
    status = {'attempted_at': now.isoformat(), 'publication_status': 'blocked', 'contract_version': CONTRACT_VERSION}
    try:
        validate(ROOT / 'data/processed/daily_aqi_latest.csv')  # validate the approved frozen release first
        release = json.loads((ROOT / 'reports/workflow/run.json').read_text())
        config = release['selected_config']  # no scheduled retuning or selection on prospective outcomes
        with tempfile.TemporaryDirectory(prefix='aqi-refresh-') as directory:
            directory = Path(directory)
            if refresh:
                shutil.copyfile(ROOT / 'data/processed/daily_aqi.manifest.json', directory / 'daily_aqi.manifest.json')
                _, manifest = extend(raw_dir=ROOT / 'data/raw', output_dir=directory, refresh=True)
                path = directory / 'daily_aqi_latest.csv'
            else:
                path = ROOT / 'data/processed/daily_aqi_latest.csv'
                manifest = json.loads(path.with_suffix('.manifest.json').read_text())
            frame, lock = validate(path, require_lock=False)
            stage_now=utc() if now_arg is None else now
            checks = freshness(frame, manifest, stage_now)
            history = read_table(reports / 'forecast_history.csv', HISTORY_COLUMNS)
            observations = read_table(reports / 'observation_history.csv', OBS_COLUMNS)
            # Record only observations for already issued target dates; no historical backfill performance.
            observed_frame = frame.loc[frame.index.strftime('%Y-%m-%d').isin(history.Date)].copy()
            observations = observe(observed_frame, lock, stage_now, observations)
            revision = os.environ.get('GITHUB_SHA') or subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
            calibration=pd.read_csv(ROOT / 'reports/uncertainty/calibration.csv')
            history, new = issue(frame, config, lock, stage_now, history, revision, intervals=calibration)
            # Supplementary provider failure must not prevent a valid primary forecast.
            weather_status={'status':'unavailable'}
            try:
                from forecast_weather import archive,current
                from weather_model import CONFIG,forward as weather_forward
                archive_table,archive_sources=archive(end=str(frame.index[-1].date()),raw=ROOT/'data/raw/forecast_weather')
                start=str((frame.index[-1]+pd.Timedelta(days=1)).date())
                stop=str((frame.index[-1]+pd.Timedelta(days=7)).date())
                live,weather_source=current(start,stop,raw=ROOT/'data/raw/forecast_weather')
                weather_forecast=weather_forward(frame,archive_table,live)
                weather_now=utc() if now_arg is None else now
                history,new_weather=issue(frame,CONFIG,lock,weather_now,history,revision,forecast_override=weather_forecast)
                new=pd.concat([new,new_weather],ignore_index=True)
                live.reset_index().to_csv(reports/'forecast_weather.csv',index=False)
                weather_status={'status':'issued_experimental_challenger','retrieved_before':weather_now.isoformat(),
                    'source':weather_source,'archive_sources':archive_sources,'attribution':'Open-Meteo.com, CC BY 4.0'}
            except Exception as error:
                weather_status['error']=f'{type(error).__name__}: {error}'
            (reports/'weather_status.json').write_text(json.dumps(weather_status,indent=2)+'\n')
            scored, metrics = score(history, observations)
            # Archive the actual production snapshot in workflow artifacts; do not mutate notebook inputs.
            artifact = ROOT / 'data/operational'; artifact.mkdir(parents=True, exist_ok=True)
            for filename in ['daily_aqi_latest.csv','daily_aqi_latest.manifest.json','hourly_pollution_2020_latest.csv.gz']:
                shutil.copyfile(path.parent / filename, artifact / filename)
            (artifact / 'daily_aqi_latest.lock.json').write_text(json.dumps(lock,indent=2)+'\n')
            atomic_csv(history, reports / 'forecast_history.csv')
            atomic_csv(observations, reports / 'observation_history.csv')
            atomic_csv(scored, reports / 'scores.csv')
            atomic_csv(metrics, reports / 'metrics.csv')
            rolling,alerts=monitor(scored)
            atomic_csv(rolling,reports/'rolling_metrics.csv')
            (reports/'alerts.json').write_text(json.dumps(alerts,indent=2)+'\n')
            latest = history.loc[history.origin.eq(str(frame.index[-1].date()))]
            atomic_csv(latest, reports / 'latest_forecast.csv')
            (reports / 'latest_manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
            status.update(publication_status='current', **checks, issued_rows=len(new),
                prospective_scores=len(scored), weather_status=weather_status['status'], input_sha256=lock['input_sha256'],
                note='First issuance retained; same-day forecasts excluded from prospective metrics; unverified truth can be revised')
    except Exception as error:
        status['error'] = f'{type(error).__name__}: {error}'
        raise
    finally:
        (reports / 'status.json').write_text(json.dumps(status,indent=2)+'\n')
    return status


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', action='store_true', help='Use frozen inputs for a freshness-checked smoke run')
    args = parser.parse_args()
    print(json.dumps(run(refresh=not args.snapshot),indent=2))
