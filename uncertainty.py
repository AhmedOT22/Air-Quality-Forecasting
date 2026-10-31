"""Horizon-specific residual prediction intervals with chronological calibration."""
import json
from pathlib import Path
import numpy as np
import pandas as pd
from etl_contract import validate
from workflow import evaluate


def residual_width(errors, coverage=.90):
    errors = np.asarray(errors,dtype=float)
    errors = errors[np.isfinite(errors)]
    if len(errors)<30: raise ValueError('At least 30 calibration residuals required per horizon')
    rank=min(len(errors),int(np.ceil((len(errors)+1)*coverage)))
    return float(np.sort(np.abs(errors))[rank-1])


def calibrate(output='reports/uncertainty'):
    frame,lock=validate();output=Path(output);output.mkdir(parents=True,exist_ok=True)
    config=json.loads(Path('reports/workflow/run.json').read_text())['selected_config']
    predictions,_=evaluate(frame,'2025-12-31','2026-09-30',[config])
    rows=[]
    for h,group in predictions.groupby('horizon'):
        calibration=group.loc[group.Date<'2026-07-01']
        test=group.loc[group.Date>='2026-07-01']
        width=residual_width(calibration.predicted-calibration.actual)
        lower=(test.predicted-width).clip(lower=0);upper=test.predicted+width
        rows.append({'horizon':int(h),'nominal_coverage':.9,'calibration_n':len(calibration),
            'half_width':width,'evaluation_n':len(test),
            'observed_coverage':float(test.actual.between(lower,upper).mean()),
            'mean_interval_width':float((upper-lower).mean())})
    table=pd.DataFrame(rows);table.to_csv(output/'calibration.csv',index=False)
    (output/'run.json').write_text(json.dumps({'dataset_lock':lock,'config':config,
        'fit_end':'2025-12-31','calibration':'2026-01-01/2026-06-30','evaluation':'2026-07-01/2026-09-30',
        'method':'Finite-sample absolute residual quantile by horizon; bounded below at zero',
        'limitations':['Serial dependence and nonstationarity invalidate an unconditional coverage guarantee',
        'Operational model is refit on later data; calibration widths are estimates, not guaranteed 90% coverage',
        '2026 interval evaluation is retrospective; report live coverage separately']},indent=2)+'\n')
    return table


def attach(forecast, table):
    result=forecast.merge(table[['horizon','half_width','nominal_coverage']],on='horizon',validate='one_to_one')
    if len(result)!=len(forecast):raise ValueError('Missing interval calibration horizon')
    result['lower_AQI']=(result.predicted_AQI-result.half_width).clip(lower=0)
    result['upper_AQI']=result.predicted_AQI+result.half_width
    return result


if __name__=='__main__':print(calibrate().to_string(index=False))
