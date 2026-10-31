"""Read-only dashboard data access and presentation rules, independent of Streamlit."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import io
import json
from pathlib import Path
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo
import pandas as pd

ROOT=Path(__file__).resolve().parent
REPOSITORY='AhmedOT22/Air-Quality-Forecasting'
FILES={'status':'status.json','forecast':'latest_forecast.csv','manifest':'latest_manifest.json',
       'metrics':'metrics.csv','rolling':'rolling_metrics.csv','scores':'scores.csv',
       'observations':'observation_history.csv','alerts':'alerts.json','weather_status':'weather_status.json',
       'weather':'forecast_weather.csv'}
REQUIRED={'status','forecast','manifest'}
MODEL_LABELS={'ridge_1':'Ridge · primary','ridge_forecast_weather_1':'Weather-aware Ridge · experimental'}


def request(url):
    with urlopen(Request(url,headers={'User-Agent':'TorontoAQIDashboard/1.0'}),timeout=12) as response:
        return response.read()


def decode(content,filename):
    if filename.endswith('.json'):return json.loads(content)
    return pd.read_csv(io.BytesIO(content))


def validate_bundle(bundle):
    frame=bundle['forecast']
    required={'origin','Date','model','predicted_AQI','horizon'}
    if frame.empty or not required<=set(frame):raise ValueError('Forecast report is empty or missing required fields')
    frame=frame.copy()
    # A model release can create a new immutable issuance for the same origin.
    # Display its newest version; reject duplicates within that version.
    if {'model_id','issued_at'}<=set(frame):
        order=frame.assign(_issued=pd.to_datetime(frame.issued_at,utc=True,format='ISO8601',errors='raise'))
        versions=order.sort_values('_issued').groupby('model').tail(1).set_index('model').model_id
        frame=frame.loc[frame.model_id.eq(frame.model.map(versions))].copy()
    for name in ['origin','Date']:frame[name]=pd.to_datetime(frame[name],errors='raise')
    if (frame.Date<=frame.origin).any() or frame.duplicated(['model','Date']).any():
        raise ValueError('Invalid or duplicate forecast dates')
    if not pd.to_numeric(frame.predicted_AQI,errors='raise').ge(0).all():
        raise ValueError('Invalid AQI predictions')
    if frame.origin.nunique()!=1:raise ValueError('Forecast report mixes issuance origins')
    if bundle['status'].get('origin') and str(frame.origin.iloc[0].date())!=bundle['status']['origin']:
        raise ValueError('Forecast and status origins disagree')
    bundle['forecast']=frame
    return bundle


def local_bundle(root=ROOT):
    result={};warnings=[]
    for key,name in FILES.items():
        path=Path(root)/'reports/operational'/name
        try:result[key]=decode(path.read_bytes(),name)
        except (OSError,ValueError) as error:
            if key in REQUIRED:raise ValueError(f'Cannot read {name}: {error}') from error
            warnings.append(f'{name} is unavailable')
    result.update(source='Bundled snapshot',revision='local checkout',warnings=warnings)
    return validate_bundle(result)


def published_bundle():
    ref=json.loads(request(f'https://api.github.com/repos/{REPOSITORY}/git/ref/heads/main'))
    sha=ref['object']['sha']
    def read(item):
        key,name=item
        try:return key,decode(request(f'https://raw.githubusercontent.com/{REPOSITORY}/{sha}/reports/operational/{name}'),name),None
        except (OSError,ValueError) as error:return key,None,str(error)
    result={};warnings=[]
    with ThreadPoolExecutor(max_workers=6) as pool:
        for key,value,error in pool.map(read,FILES.items()):
            if error:
                if key in REQUIRED:raise ValueError(f'Published {FILES[key]} unavailable: {error}')
                warnings.append(f'{FILES[key]} is unavailable')
            else:result[key]=value
    result.update(source='Latest published reports',revision=sha,warnings=warnings)
    return validate_bundle(result)


def load_bundle(published=True):
    if not published:return local_bundle()
    try:return published_bundle()
    except (OSError,ValueError,KeyError) as error:
        result=local_bundle()
        result['warnings'].insert(0,f'Could not retrieve published reports; showing the bundled snapshot. {error}')
        return result


def freshness(bundle,now=None):
    now=pd.Timestamp(now or datetime.now(timezone.utc))
    if now.tzinfo is None:raise ValueError('Current time must be timezone-aware')
    now=now.tz_convert('UTC')
    stamp=pd.to_datetime(bundle['status'].get('attempted_at'),utc=True,errors='coerce')
    origin=bundle['forecast'].origin.iloc[0]
    expected=now.tz_convert('Etc/GMT+5').tz_localize(None).normalize()-pd.Timedelta(days=1)
    blocked=bundle['status'].get('publication_status')!='current'
    stale=pd.isna(stamp) or (now-stamp)>pd.Timedelta(hours=26) or origin!=expected
    if blocked:return 'Refresh blocked',bundle['status'].get('error','The latest refresh did not publish a valid forecast.')
    if stale:return 'Historical snapshot','Forecast dates are no longer current. Treat these as archived predictions.'
    label='Current forecast' if bundle['source']=='Latest published reports' else 'Dated snapshot'
    return label,'Forecast origin uses the latest completed fixed-EST day.'


def observed_series(bundle,history):
    series=history[['Date','AQI']].copy()
    observations=bundle.get('observations',pd.DataFrame())
    if not observations.empty and {'Date','AQI'}<=set(observations):
        recent=observations.drop_duplicates('Date',keep='last')[['Date','AQI']]
        series=pd.concat([series,recent],ignore_index=True).drop_duplicates('Date',keep='last')
    series.Date=pd.to_datetime(series.Date)
    return series.sort_values('Date')


def toronto_time(value):
    return pd.to_datetime(value,utc=True).tz_convert(ZoneInfo('America/Toronto')).strftime('%b %d, %Y · %I:%M %p %Z')
