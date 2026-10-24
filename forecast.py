"""Past-only daily forecasting and rolling-origin evaluation of an AQI series."""

import argparse
import hashlib
import json
import platform
from importlib.metadata import version
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor

LAGS = (1, 2, 3, 7, 14)


def load_series(path):
    frame = pd.read_csv(path)
    if not {'Date', 'AQI'}.issubset(frame.columns):
        raise ValueError('CSV must contain Date and AQI columns.')
    dates = pd.to_datetime(frame['Date'], errors='raise')
    if dates.isna().any() or dates.dt.tz is not None or not dates.eq(dates.dt.normalize()).all():
        raise ValueError('Date must contain timezone-free calendar dates, without times.')
    series = pd.Series(pd.to_numeric(frame['AQI'], errors='raise').to_numpy(), index=dates, name='AQI').sort_index()
    if series.index.has_duplicates:
        raise ValueError('Expected exactly one AQI observation per date.')
    if series.empty or not np.isfinite(series.to_numpy(dtype=float)).all() or (series < 0).any():
        raise ValueError('AQI must contain finite, non-negative observed values; do not impute targets.')
    if not series.index.equals(pd.date_range(series.index[0], periods=len(series), freq='D')):
        raise ValueError('Expected consecutive daily observations; resolve missing dates at the source.')
    return series.astype(float)


def feature_row(history, date):
    """History ends on the day before date; calendar features are known in advance."""
    values = [float(history[-lag]) for lag in LAGS]
    angle = 2 * np.pi * pd.Timestamp(date).dayofyear / 365.25
    return values + [float(np.sin(angle)), float(np.cos(angle))]


def fit_model(series, trees=200):
    if len(series) <= max(LAGS):
        raise ValueError(f'Training requires more than {max(LAGS)} observations.')
    rows = [feature_row(series.iloc[:i].to_numpy(), series.index[i]) for i in range(max(LAGS), len(series))]
    model = RandomForestRegressor(n_estimators=trees, min_samples_leaf=3, random_state=42, n_jobs=1)
    model.fit(rows, series.iloc[max(LAGS):].to_numpy())
    return model


def recursive_forecast(model, history, horizon=7):
    if horizon < 1 or len(history) < max(LAGS):
        raise ValueError('Need a positive horizon and at least 14 historical observations.')
    values = history.to_list()
    predictions = []
    dates = pd.date_range(history.index[-1] + pd.Timedelta(days=1), periods=horizon, freq='D')
    for date in dates:
        prediction = float(model.predict([feature_row(values, date)])[0])
        predictions.append(prediction)
        values.append(prediction)
    return pd.Series(predictions, index=dates, name='prediction')


def backtest(series, test_days=90, horizon=7, trees=200):
    """Fit once before the holdout; reveal observations only after each forecast origin."""
    if test_days < horizon or horizon < 1 or test_days >= len(series) - max(LAGS):
        raise ValueError('Require 1 <= horizon <= test_days and more than 14 training days.')
    split = len(series) - test_days
    model = fit_model(series.iloc[:split], trees)
    records = []
    for end in range(split, len(series) - horizon + 1):
        history = series.iloc[:end]
        predictions = recursive_forecast(model, history, horizon)
        for step, (date, prediction) in enumerate(predictions.items(), 1):
            # Seasonal naive repeats the last observed week, including for horizons > 7.
            seasonal = float(history.iloc[-7 + (step - 1) % 7])
            records.append({'origin': history.index[-1], 'Date': date, 'horizon': step,
                            'actual': float(series.loc[date]), 'random_forest': prediction,
                            'persistence': float(history.iloc[-1]), 'seasonal_naive': seasonal})
    predictions = pd.DataFrame(records)
    metrics = []
    for step, group in predictions.groupby('horizon'):
        for name in ('random_forest', 'persistence', 'seasonal_naive'):
            error = group[name] - group['actual']
            metrics.append({'model': name, 'horizon': int(step), 'n_forecasts': len(group),
                            'MAE': float(error.abs().mean()), 'RMSE': float(np.sqrt((error ** 2).mean()))})
    return predictions, pd.DataFrame(metrics)


def run(input_path, output_dir, test_days=90, horizon=7, trees=200):
    series = load_series(input_path)
    predictions, metrics = backtest(series, test_days, horizon, trees)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    predictions.to_csv(output / 'backtest.csv', index=False)
    metrics.to_csv(output / 'metrics.csv', index=False)
    # Refit only after holdout evaluation, for the separate future forecast.
    future = recursive_forecast(fit_model(series, trees), series, horizon)
    future.rename_axis('Date').to_csv(output / 'forecast.csv')
    metadata = {'input_sha256': hashlib.sha256(Path(input_path).read_bytes()).hexdigest(),
                'observations': len(series), 'start': str(series.index[0].date()),
                'end': str(series.index[-1].date()), 'train_end': str(series.index[-test_days - 1].date()),
                'holdout_start': str(series.index[-test_days].date()), 'test_days': test_days,
                'horizon': horizon, 'lags': list(LAGS), 'trees': trees, 'random_state': 42,
                'evaluation': 'fixed training window, rolling forecast origins, recursive multi-step',
                'python': platform.python_version(),
                'packages': {p: version(p) for p in ('pandas', 'numpy', 'scikit-learn', 'matplotlib')}}
    (output / 'run.json').write_text(json.dumps(metadata, indent=2) + '\n')
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    one_day = predictions[predictions['horizon'] == 1]
    fig, ax = plt.subplots(figsize=(11, 4))
    for name in ('actual', 'random_forest', 'persistence'):
        ax.plot(one_day['Date'], one_day[name], label=name.replace('_', ' '), linewidth=1.2)
    ax.set(xlabel='Target date', ylabel='Input AQI-series units', title='One-day forecasts at rolling origins (fixed training window)')
    ax.legend()
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(output / 'backtest.png', dpi=160)
    plt.close(fig)
    return metrics


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True, help='CSV with consecutive daily Date,AQI observations')
    parser.add_argument('--output', type=Path, default=Path('reports/latest'))
    parser.add_argument('--test-days', type=int, default=90)
    parser.add_argument('--horizon', type=int, default=7)
    parser.add_argument('--trees', type=int, default=200)
    args = parser.parse_args()
    if args.trees < 1:
        parser.error('--trees must be positive')
    try:
        print(run(args.input, args.output, args.test_days, args.horizon, args.trees).to_string(index=False))
    except (ValueError, FileNotFoundError) as error:
        parser.exit(2, f'Input error: {error}\n')


if __name__ == '__main__':
    main()
