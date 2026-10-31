"""Chronological development, model selection, final evaluation and forward AQI forecasts."""
import json
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression, Ridge
from sklearn.pipeline import make_pipeline
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler
from sklearn.ensemble import RandomForestRegressor
from aqi import category
from etl_contract import validate
from forecast import make_features, seasonal_lag

HORIZONS = range(1, 8)
TREES = 100
CANDIDATES = [dict(name='autoregression', family='autoregression'),
              dict(name='ridge_10', family='ridge', alpha=10.),
              dict(name='forest_lags_5', family='forest_lags', leaf=5),
              dict(name='forest_weather_5', family='forest_weather', leaf=5),
              dict(name='persistence', family='persistence'),
              dict(name='weekly', family='weekly')]
BASELINES = ('persistence', 'weekly')


def estimator(config):
    family = config['family']
    if family == 'autoregression':
        return make_pipeline(StandardScaler(), LinearRegression())
    preprocessing = [SimpleImputer(strategy='median', add_indicator=True, keep_empty_features=True)]
    if family == 'ridge':
        return make_pipeline(*preprocessing, StandardScaler(), Ridge(alpha=config['alpha']))
    return make_pipeline(*preprocessing, RandomForestRegressor(n_estimators=TREES,
        min_samples_leaf=config['leaf'], random_state=42, n_jobs=1))


def fit(frame, end, horizon, config):
    features, lag_columns, eligible = make_features(frame, horizon)
    columns = (lag_columns if config['family'] == 'forest_lags' else
               [c for c in lag_columns if c.startswith('aqi_')] if config['family'] == 'autoregression'
               else features.columns.tolist())
    y = frame.AQI.shift(-horizon)
    training = eligible & y.notna() & (frame.index + pd.Timedelta(days=horizon + 1) <= pd.Timestamp(end))
    if training.sum() < 30:
        raise ValueError('Insufficient chronological training rows')
    model = estimator(config).fit(features.loc[training, columns], y.loc[training])
    fitted = np.maximum(0, model.predict(features.loc[training, columns]))
    training_mae = float(np.abs(fitted - y.loc[training]).mean())
    return model, features, columns, eligible, training_mae, int(training.sum())


def evaluate(frame, fit_end, evaluation_end, configs, horizons=HORIZONS):
    """Fit before evaluation; all candidates share identical origins within a horizon."""
    frame = frame.loc[:evaluation_end]
    fit_end = pd.Timestamp(fit_end)
    records, diagnostics = [], []
    for h in horizons:
        features, _, eligible = make_features(frame, h)
        target = frame.AQI.shift(-h)
        dates = frame.index + pd.Timedelta(days=h)
        mask = eligible & target.notna() & (frame.index >= fit_end) & (dates > fit_end)
        origins = frame.index[mask]
        if origins.empty:
            raise ValueError('No eligible evaluation pairs')
        actual = target.loc[mask].to_numpy()
        persistence = frame.AQI.shift(1).loc[mask].to_numpy()
        for config in configs:
            family = config['family']
            if family in BASELINES:
                lag = 1 if family == 'persistence' else seasonal_lag(h, 1)
                predicted = frame.AQI.shift(lag).loc[mask].to_numpy()
                training_mae, count = np.nan, 0
            else:
                model, features, columns, _, training_mae, count = fit(frame, fit_end, h, config)
                predicted = np.maximum(0, model.predict(features.loc[mask, columns]))
            error = predicted - actual
            diagnostics.append({'model': config['name'], 'horizon': h, 'n': len(actual),
                'training_n': count, 'training_MAE': training_mae, 'MAE': float(np.abs(error).mean()),
                'RMSE': float(np.sqrt(np.mean(error ** 2))),
                'MAE_skill': float(1 - np.abs(error).mean() / np.abs(persistence - actual).mean())})
            records.extend({'origin': origin, 'Date': origin + pd.Timedelta(days=h), 'horizon': h,
                            'model': config['name'], 'actual': a, 'predicted': p}
                           for origin, a, p in zip(origins, actual, predicted))
    return pd.DataFrame(records), pd.DataFrame(diagnostics)


def tuning_grid(winner):
    family = winner['family']
    if family == 'ridge':
        return [dict(name=f'ridge_{alpha:g}', family=family, alpha=alpha) for alpha in (1., 10., 100.)]
    if family.startswith('forest'):
        return [dict(name=f'{family}_{leaf}', family=family, leaf=leaf) for leaf in (5, 10, 20)]
    return [winner]  # fixed AR structure or baseline; no fictitious tuning step


def choose(metrics, configs):
    # Equal weight per horizon/fold, independent of the number of eligible days.
    name = metrics.groupby('model').MAE.mean().idxmin()
    return next(config for config in configs if config['name'] == name)


def forward(frame, config):
    origin = frame.index[-1]
    rows = []
    for h in HORIZONS:
        features, _, eligible = make_features(frame, h)
        if not eligible.iloc[-1]:
            raise ValueError('Latest completed origin lacks required AQI history; do not issue a stale forecast')
        if config['family'] in BASELINES:
            lag = 1 if config['family'] == 'persistence' else seasonal_lag(h, 1)
            prediction = float(frame.AQI.iloc[-1-lag])
        else:
            model, features, columns, _, _, _ = fit(frame, origin, h, config)
            prediction = max(0., float(model.predict(features[columns].iloc[[-1]])[0]))
        rows.append({'origin': origin, 'Date': origin + pd.Timedelta(days=h), 'horizon': h,
                     'model': config['name'], 'predicted_AQI': prediction,
                     'predicted_category': category(int(np.floor(prediction + .5)))})
    return pd.DataFrame(rows)


def run(output='reports/workflow'):
    frame, lock = validate()
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    fold_tables = []
    for year in (2022, 2023):
        _, metrics = evaluate(frame, f'{year-1}-12-31', f'{year}-12-31', CANDIDATES)
        fold_tables.append(metrics.assign(fold=year))
    cv = pd.concat(fold_tables, ignore_index=True)
    cv.to_csv(output / 'candidate_comparison.csv', index=False)
    candidate = choose(cv, CANDIDATES)
    grid = tuning_grid(candidate)
    # Keep both baselines in the tuning comparison and allow either to win.
    grid += [c for c in CANDIDATES if c['family'] in BASELINES and c['name'] not in {g['name'] for g in grid}]
    _, tuning = evaluate(frame, '2023-12-31', '2024-12-31', grid)
    tuning.to_csv(output / 'tuning.csv', index=False)
    selected = choose(tuning, grid)
    finalists = [selected] + [c for c in CANDIDATES if c['family'] in BASELINES and c['name'] != selected['name']]
    predictions, test = evaluate(frame, '2024-12-31', '2025-12-31', finalists)
    predictions.to_csv(output / 'test_predictions.csv', index=False)
    test.to_csv(output / 'test_metrics.csv', index=False)
    one = predictions.loc[predictions.horizon.eq(1)].copy()
    one['month'] = one.Date.dt.to_period('M').astype(str)
    one['observed_category'] = one.actual.map(category)
    one['absolute_error'] = (one.predicted - one.actual).abs()
    for field in ('month', 'observed_category'):
        diagnostic = one.groupby(['model', field]).absolute_error.agg(['mean', 'count']).reset_index()
        diagnostic.to_csv(output / f'test_errors_by_{field}.csv', index=False)
    forecast = forward(frame, selected)
    forecast.to_csv(output / 'forecast.csv', index=False)
    metadata = {'dataset_lock': lock, 'candidate_folds': [2022, 2023], 'tuning_period': 2024,
                'final_evaluation_period': 2025, 'selected_config': selected, 'candidate_winner': candidate,
                'selection_rule': 'Lowest mean MAE with equal weight per fold and horizon; selection excludes 2025',
                'horizons': list(HORIZONS), 'forest_trees': TREES, 'seed': 42,
                'latest_completed_origin': str(frame.index[-1].date()),
                'forecast_status': 'Forecast after the latest completed observation day; freshness depends on input refresh',
                'caveats': ['2022-2024 previously inspected; retrospective development, not pristine tests',
                    '2025 is held out from this selection procedure, not a permanent untouched test after publication',
                    '2025 includes provisional Ontario observations and a source precision change',
                    'No calibrated uncertainty intervals or health-warning capability claimed',
                    'Daily AQI availability delayed one full day; no future measured weather used']}
    (output / 'run.json').write_text(json.dumps(metadata, indent=2) + '\n')
    return cv, tuning, test, forecast


if __name__ == '__main__':
    cv, tuning, test, forecast = run()
    print(test.to_string(index=False))
    print(forecast.to_string(index=False))
