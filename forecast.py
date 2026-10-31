"""Direct 1–7 day PM2.5 forecasts with chronological, station-specific backtests."""

import argparse
import hashlib
import json
import platform
from importlib.metadata import version
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from data_sources import WEATHER_FIELDS

LAGS = (0, 1, 2, 6, 13)
MODEL_NAMES = ('ridge_weather', 'forest_lags', 'forest_weather')
BASELINES = ('persistence', 'seasonal_naive')


def validate_frame(frame):
    if not isinstance(frame.index, pd.DatetimeIndex) or frame.index.tz is not None:
        raise ValueError('Expected timezone-free daily calendar dates')
    if (frame.empty or frame.index.hasnans or frame.index.has_duplicates
            or not frame.index.is_monotonic_increasing
            or not frame.index.equals(frame.index.normalize())):
        raise ValueError('Dates must be nonempty, sorted, and unique')
    if not frame.index.equals(pd.date_range(frame.index[0], frame.index[-1], freq='D', name=frame.index.name)):
        raise ValueError('Retain every calendar day, including days with missing PM25')
    if 'PM25' not in frame:
        raise ValueError('Expected PM25 concentration column, not the legacy derived AQI')
    values = pd.to_numeric(frame.PM25, errors='raise')
    if np.isinf(values).any() or (values.dropna() < 0).any() or values.notna().sum() < 60:
        raise ValueError('Need at least 60 finite, non-negative observed PM25 days; gaps may be NaN')
    for name in WEATHER_FIELDS:
        if name not in frame or np.isinf(pd.to_numeric(frame[name], errors='raise')).any():
            raise ValueError(f'Missing or infinite weather feature: {name}')
    for name in ('naps_station_id', 'climate_station_id'):
        if name in frame and (frame[name].isna().any() or frame[name].nunique() != 1):
            raise ValueError('A benchmark must contain one station pair, not mixed stations')
    return frame


def load_data(path):
    path = Path(path)
    manifest_path = path.with_suffix('.manifest.json')
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        if hashlib.sha256(path.read_bytes()).hexdigest() != manifest['prepared_sha256']:
            raise ValueError('Prepared data checksum differs from source manifest')
    frame = pd.read_csv(path, dtype={'naps_station_id': str, 'climate_station_id': str})
    if 'Date' not in frame:
        raise ValueError('CSV must contain Date')
    dates = pd.to_datetime(frame.pop('Date'), format='%Y-%m-%d', errors='raise')
    frame.index = pd.DatetimeIndex(dates, name='Date')
    return validate_frame(frame)


def make_features(frame, horizon):
    """Rows describe information available after the completed origin day only."""
    if not 1 <= horizon <= 7:
        raise ValueError('Supported horizons are 1 through 7 days')
    features = pd.DataFrame(index=frame.index)
    for lag in LAGS:
        features[f'pm25_lag_{lag}'] = frame.PM25.shift(lag)
    features['pm25_mean_7d'] = frame.PM25.rolling(7, min_periods=7).mean()
    target_dates = frame.index + pd.Timedelta(days=horizon)
    angle = 2 * np.pi * target_dates.dayofyear / 365.25
    features['target_day_sin'] = np.sin(angle)
    features['target_day_cos'] = np.cos(angle)
    lag_columns = features.columns.tolist()
    for name in WEATHER_FIELDS:
        features[name] = frame[name]  # completed origin day, never target-day weather
    # All pollution features must be observed; targets are never filled. Training-
    # only median imputation is reserved for missing weather predictors.
    eligible = features[lag_columns].notna().all(axis=1)
    return features, lag_columns, eligible


def new_model(name, trees=200):
    imputer = SimpleImputer(strategy='median', add_indicator=True, keep_empty_features=True)
    if name == 'ridge_weather':
        return make_pipeline(imputer, StandardScaler(), Ridge(alpha=10.0))
    if name in ('forest_lags', 'forest_weather'):
        return make_pipeline(imputer, RandomForestRegressor(
            n_estimators=trees, min_samples_leaf=5, random_state=42, n_jobs=1))
    raise ValueError(f'Unknown model: {name}')


def fit_horizon(frame, train_end, horizon, trees=200):
    if trees < 1:
        raise ValueError('trees must be positive')
    features, lag_columns, eligible = make_features(frame, horizon)
    target = frame.PM25.shift(-horizon)
    label_dates = frame.index + pd.Timedelta(days=horizon)
    training = eligible & target.notna() & (label_dates <= pd.Timestamp(train_end))
    if training.sum() < 30:
        raise ValueError(f'Fewer than 30 eligible training samples at horizon {horizon}')
    models = {}
    for name in MODEL_NAMES:
        columns = lag_columns if name == 'forest_lags' else features.columns.tolist()
        model = new_model(name, trees)
        model.fit(features.loc[training, columns], target.loc[training])
        models[name] = (model, columns)
    return models, features, eligible, int(training.sum())


def score_predictions(predictions):
    rows = []
    for horizon, group in predictions.groupby('horizon'):
        persistence_mae = (group.persistence - group.actual).abs().mean()
        for model in MODEL_NAMES + BASELINES:
            error = group[model] - group.actual
            mae = float(error.abs().mean())
            rows.append({'model': model, 'horizon': int(horizon), 'n_forecasts': len(group),
                         'MAE': mae, 'RMSE': float(np.sqrt((error ** 2).mean())),
                         'MAE_skill_vs_persistence': float(1 - mae / persistence_mae)
                         if persistence_mae > 0 else None})
    return pd.DataFrame(rows)


def backtest(frame, test_days=366, horizon=7, trees=200):
    """Fixed fit before holdout; direct models share identical observed evaluation pairs."""
    validate_frame(frame)
    if not 1 <= horizon <= 7 or test_days < horizon or test_days >= len(frame) - 60:
        raise ValueError('Require horizon 1–7 and a holdout leaving at least 60 training days')
    split = len(frame) - test_days
    train_end = frame.index[split - 1]
    records, training_counts = [], {}
    for step in range(1, horizon + 1):
        models, features, eligible, count = fit_horizon(frame, train_end, step, trees)
        training_counts[str(step)] = count
        target = frame.PM25.shift(-step)
        # Origins start at the last training day. Subsequent completed holdout
        # observations become available, but never enter model fitting.
        evaluate = eligible & target.notna() & (frame.index >= train_end)
        origins = frame.index[evaluate]
        if origins.empty:
            raise ValueError(f'No eligible observed holdout pairs at horizon {step}')
        result = pd.DataFrame({'origin': origins, 'Date': origins + pd.Timedelta(days=step),
                               'horizon': step, 'actual': target.loc[evaluate].to_numpy(),
                               'persistence': frame.loc[evaluate, 'PM25'].to_numpy(),
                               'seasonal_naive': frame.PM25.shift(7 - step).loc[evaluate].to_numpy()})
        for name, (model, columns) in models.items():
            result[name] = np.maximum(0, model.predict(features.loc[evaluate, columns]))
        records.append(result)
    predictions = pd.concat(records, ignore_index=True).sort_values(['origin', 'horizon'])
    predictions.attrs['training_samples_by_horizon'] = training_counts
    return predictions, score_predictions(predictions)


def future_forecast(frame, horizon=7, trees=200):
    """Refit after evaluation; forecast beyond the archive end, not live conditions."""
    output = []
    for step in range(1, horizon + 1):
        models, features, eligible, _ = fit_horizon(frame, frame.index[-1], step, trees)
        if not eligible.iloc[-1]:
            raise ValueError('Latest origin lacks observed pollution history; no future forecast issued')
        row = {'origin': frame.index[-1], 'Date': frame.index[-1] + pd.Timedelta(days=step), 'horizon': step}
        for name, (model, columns) in models.items():
            row[name] = max(0.0, float(model.predict(features.iloc[[-1]][columns])[0]))
        row['persistence'] = float(frame.PM25.iloc[-1])
        row['seasonal_naive'] = float(frame.PM25.iloc[-7 + step - 1])
        output.append(row)
    return pd.DataFrame(output)


def plot_results(predictions, metrics, output):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams.update({'axes.spines.top': False, 'axes.spines.right': False, 'font.size': 10})
    one = predictions.loc[predictions.horizon == 1].set_index('Date')
    one = one.reindex(pd.date_range(one.index.min(), one.index.max(), freq='D'))
    fig, ax = plt.subplots(figsize=(12, 4))
    for name, color in [('actual', '#122c36'), ('forest_weather', '#167466'), ('persistence', '#c27d32')]:
        ax.plot(one.index, one[name], label=name.replace('_', ' '), color=color, linewidth=1.1)
    ax.set(xlabel='Target date (local standard calendar)', ylabel='PM2.5 (µg/m³)',
           title='One-day forecasts: observed eligible holdout pairs')
    ax.legend(ncol=3)
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(output / 'backtest.png', dpi=160)
    plt.close(fig)
    fig, ax = plt.subplots(figsize=(8, 4))
    for model in MODEL_NAMES + BASELINES:
        data = metrics.loc[metrics.model == model]
        ax.plot(data.horizon, data.MAE, marker='o', label=model.replace('_', ' '))
    ax.set(xlabel='Forecast horizon (days)', ylabel='MAE (µg/m³)', title='Error by horizon; identical pairs per model')
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(output / 'horizon_errors.png', dpi=160)
    plt.close(fig)


def run(input_path, output_dir, test_days=366, horizon=7, trees=200, end_date=None):
    frame = load_data(input_path)
    if end_date:
        end = pd.Timestamp(end_date)
        if end not in frame.index:
            raise ValueError('end_date must be present in the prepared calendar')
        frame = frame.loc[:end]
    predictions, metrics = backtest(frame, test_days, horizon, trees)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    predictions.to_csv(output / 'backtest.csv', index=False)
    metrics.to_csv(output / 'metrics.csv', index=False)
    forecast_status = 'Archive-end projection; not a current forecast'
    try:
        future = future_forecast(frame, horizon, trees)
    except ValueError as error:
        future = pd.DataFrame(columns=['origin', 'Date', 'horizon', *MODEL_NAMES, *BASELINES])
        forecast_status = str(error)
    future.to_csv(output / 'forecast.csv', index=False)
    monthly = []
    one = predictions.loc[predictions.horizon == 1].copy()
    one['month'] = one.Date.dt.to_period('M').astype(str)
    for month, group in one.groupby('month'):
        for name in MODEL_NAMES + BASELINES:
            monthly.append({'month': month, 'model': name, 'n_forecasts': len(group),
                            'MAE': float((group[name] - group.actual).abs().mean())})
    pd.DataFrame(monthly).to_csv(output / 'monthly_metrics.csv', index=False)
    metadata = {'input_sha256': hashlib.sha256(Path(input_path).read_bytes()).hexdigest(),
                'target': 'PM25', 'units': 'µg/m³', 'calendar_days': len(frame),
                'observed_target_days': int(frame.PM25.notna().sum()),
                'missing_target_days': int(frame.PM25.isna().sum()),
                'start': str(frame.index[0].date()), 'end': str(frame.index[-1].date()),
                'train_end': str(frame.index[-test_days-1].date()),
                'holdout_start': str(frame.index[-test_days].date()), 'test_days': test_days,
                'horizon': horizon, 'trees': trees, 'seed': 42, 'ridge_alpha': 10,
                'pollution_lags_calendar_days': list(LAGS), 'weather_fields': list(WEATHER_FIELDS),
                'training_samples_by_horizon': predictions.attrs['training_samples_by_horizon'],
                'eligible_pairs_by_horizon': {str(h): len(g) for h, g in predictions.groupby('horizon')},
                'evaluation': 'Fixed pre-holdout fit; separate direct models per horizon; observed targets only',
                'availability_assumption': 'Completed origin-day finalized archive observations available; publication latency/revisions not simulated',
                'weather_imputation': 'Training-only median + missing indicators; no target imputation',
                'forecast_status': forecast_status, 'python': platform.python_version(),
                'packages': {p: version(p) for p in ('pandas', 'numpy', 'scikit-learn', 'matplotlib')}}
    (output / 'run.json').write_text(json.dumps(metadata, indent=2, ensure_ascii=False) + '\n')
    plot_results(predictions, metrics, output)
    return metrics


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, default=Path('data/processed/daily_pm25.csv'))
    parser.add_argument('--output', type=Path, default=Path('reports/latest'))
    parser.add_argument('--test-days', type=int, default=366)
    parser.add_argument('--horizon', type=int, default=7)
    parser.add_argument('--trees', type=int, default=200)
    parser.add_argument('--end-date', help='Optional retrospective evaluation endpoint, e.g. 2023-12-31')
    args = parser.parse_args()
    try:
        print(run(args.input, args.output, args.test_days, args.horizon, args.trees, args.end_date).to_string(index=False))
    except (ValueError, OSError, KeyError) as error:
        parser.exit(2, f'Forecast failed: {error}\n')


if __name__ == '__main__':
    main()
