"""Toronto AQI Observatory: read-only forecasts, observations and model evidence."""

import os
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from aqi import category
from dashboard_data import (
    ROOT,
    MODEL_LABELS,
    load_bundle,
    freshness,
    observed_series,
    toronto_time,
)

st.set_page_config(
    page_title="Toronto AQI Observatory",
    page_icon="🌿",
    layout="wide",
    initial_sidebar_state="auto",
)
st.markdown(
    """<style>
.block-container{max-width:1440px;padding-top:2rem;padding-bottom:2rem}
h1{font-size:2.7rem!important;letter-spacing:-.055em;font-weight:750!important}
h2{letter-spacing:-.025em} h3{letter-spacing:-.02em}
[data-testid="stMetric"]{background:white;border:1px solid #e1e9ec;border-radius:14px;padding:20px}
[data-testid="stMetricLabel"]{color:#52707a}
[data-testid="stMetricValue"]{font-size:2rem}
[data-testid="stSidebar"]{border-right:1px solid #e1e9ec}
.eyebrow{color:#167466;font-size:.76rem;font-weight:750;letter-spacing:.14em;margin-bottom:12px}
.subhead{color:#58707a;font-size:1.04rem;max-width:760px;line-height:1.6}
.footnote{font-size:.78rem;color:#667f89;line-height:1.6}
</style>""",
    unsafe_allow_html=True,
)


@st.cache_data(ttl=300, show_spinner=False)
def reports(published):
    return load_bundle(published)


@st.cache_data(show_spinner=False)
def historical_snapshot():
    return pd.read_csv(
        ROOT / "data/processed/daily_aqi_latest.csv", parse_dates=["Date"]
    )


def style_chart(fig, height=390):
    fig.update_layout(
        height=height,
        margin=dict(l=12, r=20, t=20, b=12),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="white",
        font=dict(family="Arial", color="#26434e"),
        hovermode="x unified",
        legend=dict(orientation="h", y=1.13, x=0),
        xaxis=dict(showgrid=False),
        yaxis=dict(gridcolor="#edf1f3", zeroline=False),
        hoverlabel=dict(bgcolor="white"),
    )
    return fig


def forecast_chart(primary, challenger, observed, intervals, compare):
    fig = go.Figure()
    context = observed.loc[
        observed.Date >= primary.origin.iloc[0] - pd.Timedelta(days=21)
    ]
    fig.add_trace(
        go.Scatter(
            x=context.Date,
            y=context.AQI,
            name="Observed AQI",
            mode="lines",
            line=dict(color="#81959e", width=2),
            connectgaps=False,
        )
    )
    if (
        intervals
        and {"lower_AQI", "upper_AQI"} <= set(primary)
        and primary.lower_AQI.notna().all()
    ):
        fig.add_trace(
            go.Scatter(
                x=primary.Date,
                y=primary.upper_AQI,
                line=dict(width=0),
                showlegend=False,
                hoverinfo="skip",
            )
        )
        fig.add_trace(
            go.Scatter(
                x=primary.Date,
                y=primary.lower_AQI,
                fill="tonexty",
                fillcolor="rgba(22,116,102,.13)",
                line=dict(width=0),
                name="Experimental interval",
                hoverinfo="skip",
            )
        )
    fig.add_trace(
        go.Scatter(
            x=primary.Date,
            y=primary.predicted_AQI,
            name="Primary forecast",
            mode="lines+markers",
            line=dict(color="#167466", width=3),
            marker=dict(size=8),
            hovertemplate="%{y:.1f} AQI<extra></extra>",
        )
    )
    if compare and not challenger.empty:
        fig.add_trace(
            go.Scatter(
                x=challenger.Date,
                y=challenger.predicted_AQI,
                name="Weather-aware challenger",
                mode="lines+markers",
                line=dict(color="#ca8a33", width=2, dash="dot"),
            )
        )
    fig.add_hline(
        y=50,
        line_color="#b5c9c3",
        line_dash="dot",
        annotation_text="Good / Moderate",
        annotation_position="top left",
    )
    fig.add_vline(
        x=primary.origin.iloc[0].timestamp() * 1000,
        line_dash="dash",
        line_color="#c1cdd2",
    )
    fig.update_yaxes(title="AQI points", rangemode="tozero")
    return style_chart(fig)


with st.sidebar:
    st.markdown("### 🌿 Toronto AQI")
    st.caption("OBSERVATORY · TORONTO WEST")
    offline = os.environ.get("AQI_DASHBOARD_OFFLINE") == "1"
    source = st.radio(
        "Report source",
        ["Latest published reports", "Bundled snapshot"],
        index=1 if offline else 0,
    )
    if st.button("Refresh reports", width="stretch"):
        reports.clear()
        st.rerun()
    st.caption(
        "Refreshes displayed reports. Forecasts are generated automatically twice daily."
    )
    st.divider()
    horizon = st.slider("Days to display", min_value=1, max_value=7, value=7)
    show_interval = st.toggle("Show uncertainty band", value=True)
    show_challenger = st.toggle("Compare weather-aware model", value=False)
    st.divider()
    st.caption(
        "Toronto West · 125 Resources Road\n\nEPA 2024 · four-pollutant reconstruction\n\nPrimary model · Ridge, alpha 1"
    )
    st.link_button(
        "Source code & methodology",
        "https://github.com/AhmedOT22/Air-Quality-Forecasting",
        width="stretch",
    )

try:
    with st.spinner("Reading forecast reports…"):
        bundle = reports(source == "Latest published reports")
except (OSError, ValueError, KeyError) as error:
    st.error(f"Forecast reports cannot be loaded: {error}")
    st.stop()

st.markdown(
    '<div class="eyebrow">ENVIRONMENTAL INTELLIGENCE / TORONTO WEST</div>',
    unsafe_allow_html=True,
)
st.title("Toronto air quality outlook")
st.markdown(
    '<p class="subhead">Seven-day forecasts for Toronto West, with uncertainty estimates and performance tracked against observations.</p>',
    unsafe_allow_html=True,
)
state, reason = freshness(bundle)
status = bundle["status"]
if state in ["Historical snapshot", "Refresh blocked"]:
    st.warning(f"{state} · {reason}")
else:
    st.caption(
        f"● {state}  ·  Updated {toronto_time(status['attempted_at'])}  ·  {bundle['source']}"
    )
for warning in bundle["warnings"]:
    st.warning(warning)

forecast = bundle["forecast"]
primary = (
    forecast.loc[forecast.model.eq("ridge_1")].sort_values("horizon").head(horizon)
)
challenger = (
    forecast.loc[forecast.model.eq("ridge_forecast_weather_1")]
    .sort_values("horizon")
    .head(horizon)
)
if primary.empty:
    st.error("The primary forecast is unavailable.")
    st.stop()
history = historical_snapshot()
observed = observed_series(bundle, history)
next_row = primary.iloc[0]
peak = primary.loc[primary.predicted_AQI.idxmax()]
metrics = bundle.get("metrics", pd.DataFrame())
scored = int(status.get("prospective_scores", 0))
a, b, c, d = st.columns(4)
a.metric(
    f"Forecast · {next_row.Date:%b %d}",
    f"{next_row.predicted_AQI:.0f}",
    category(int(np.floor(next_row.predicted_AQI + 0.5))),
    delta_color="off",
)
b.metric(
    "Highest in selected outlook",
    f"{peak.predicted_AQI:.0f}",
    f"{peak.Date:%a, %b %d}",
    delta_color="off",
)
c.metric(
    "Forecast origin",
    f"{next_row.origin:%b %d}",
    f"{next_row.origin:%Y} · completed EST day",
    delta_color="off",
)
d.metric(
    "Prospective outcomes",
    f"{scored:,}",
    "Collecting observations" if scored == 0 else "Model / horizon pairs",
    delta_color="off",
)

outlook, observations, performance, method = st.tabs(
    ["Forecast outlook", "Observed history", "Performance", "About the model"]
)
with outlook:
    st.subheader("The upcoming outlook")
    st.caption(
        "Solid green: retained Ridge model. Shading: experimental nominal 90% interval. Vertical line: last completed forecast origin."
    )
    st.plotly_chart(
        forecast_chart(primary, challenger, observed, show_interval, show_challenger),
        width="stretch",
        config={"displayModeBar": False},
    )
    st.info(
        "Uncertainty is experimental: the nominal 90% intervals covered 79–87% of observations in the later retrospective evaluation. They do not guarantee 90% live coverage."
    )
    left, right = st.columns([2, 1])
    with left:
        table = primary[["Date", "predicted_AQI"]].copy()
        table["Category"] = table.predicted_AQI.map(
            lambda v: category(int(np.floor(v + 0.5)))
        )
        if show_interval and {"lower_AQI", "upper_AQI"} <= set(primary):
            table["Lower estimate"] = primary.lower_AQI.to_numpy()
            table["Upper estimate"] = primary.upper_AQI.to_numpy()
        table = table.rename(
            columns={"Date": "Forecast date", "predicted_AQI": "Predicted AQI"}
        )
        st.dataframe(
            table,
            hide_index=True,
            width="stretch",
            column_config={
                "Predicted AQI": st.column_config.NumberColumn(format="%.1f"),
                "Lower estimate": st.column_config.NumberColumn(format="%.1f"),
                "Upper estimate": st.column_config.NumberColumn(format="%.1f"),
                "Forecast date": st.column_config.DateColumn(format="ddd, MMM D"),
            },
        )
    with right:
        st.markdown("**Read the outlook**")
        st.markdown(
            "**0–50** · Good\n\n**51–100** · Moderate\n\n**101–150** · Unhealthy for sensitive groups\n\n**151–200** · Unhealthy\n\n**201–300** · Very unhealthy\n\n**301+** · Hazardous"
        )
    st.caption(
        "The first forecast is a same-day estimate. Only forecasts issued before the target date starts enter prospective metrics. The weather-aware challenger is experimental and does not replace the primary model."
    )
    st.download_button(
        "Download displayed forecasts",
        primary.to_csv(index=False),
        "toronto-aqi-forecast.csv",
        "text/csv",
    )
    if show_challenger and challenger.empty:
        st.warning(
            "The experimental challenger is unavailable for this issuance. The primary forecast is retained."
        )
    weather = bundle.get("weather", pd.DataFrame())
    if not weather.empty:
        with st.expander("Forecast weather at Pearson"):
            st.dataframe(weather.head(horizon), hide_index=True, width="stretch")
            st.caption(
                "Forecast temperature (°C), humidity (%), wind (km/h), pressure (kPa). Open-Meteo.com, CC BY 4.0. Forecast values are distinct from observed weather."
            )
with observations:
    st.subheader("How air quality has changed")
    st.caption(
        "Historical context combines the frozen daily dataset with subsequently recorded observations. Gaps remain visible; values are not interpolated."
    )
    window = st.selectbox(
        "History window", ["Last 90 days", "Last year", "All data since 2020"]
    )
    stop = observed.Date.max()
    start = (
        stop - pd.Timedelta(days=90 if window == "Last 90 days" else 365)
        if window != "All data since 2020"
        else observed.Date.min()
    )
    view = (
        observed.loc[observed.Date >= start]
        .set_index("Date")
        .reindex(pd.date_range(start.normalize(), stop, freq="D"))
    )
    fig = go.Figure(
        go.Scatter(
            x=view.index,
            y=view.AQI,
            name="Observed AQI",
            mode="lines",
            connectgaps=False,
            line=dict(color="#167466", width=1.8),
        )
    )
    fig.update_yaxes(title="AQI points")
    st.plotly_chart(style_chart(fig), width="stretch", config={"displayModeBar": False})
    st.caption(
        f"Latest available daily observation: {stop:%b %d, %Y}. Daily AQI is delayed because ozone windows include next-morning readings."
    )
    component = st.selectbox(
        "Pollutant detail", ["PM2.5", "Ozone", "Nitrogen dioxide", "Sulphur dioxide"]
    )
    column = {
        "PM2.5": "PM25_AQI",
        "Ozone": "O3_AQI",
        "Nitrogen dioxide": "NO2_AQI",
        "Sulphur dioxide": "SO2_AQI",
    }[component]
    detail = history.loc[history.Date >= start, ["Date", column]].set_index("Date")
    st.line_chart(
        detail.rename(columns={column: f"{component} sub-index"}),
        color="#527c91",
        height=230,
    )
    st.caption(
        f"Component detail uses the frozen snapshot through {history.Date.max():%b %d, %Y}; it is an AQI sub-index, not pollutant concentration."
    )
with performance:
    st.subheader("Evidence, with the time boundary intact")
    st.markdown("**Prospective monitoring**")
    if metrics.empty:
        st.info(
            "Waiting for observed outcomes. Predictions are recorded now; genuine prospective scores appear only after their target AQI becomes available. No live accuracy is claimed yet."
        )
    else:
        st.dataframe(
            metrics.rename(
                columns={"MAE": "MAE · AQI points", "RMSE": "RMSE · AQI points"}
            ),
            hide_index=True,
            width="stretch",
        )
        rolling = bundle.get("rolling", pd.DataFrame())
        if not rolling.empty:
            with st.expander("Latest 30 scored dates per model and horizon"):
                st.dataframe(rolling, hide_index=True, width="stretch")
    alerts = bundle.get("alerts", {}).get("alerts", [])
    for alert in alerts:
        st.warning(
            f"{MODEL_LABELS.get(alert['model'], alert['model'])} · horizon {alert['horizon']}: {alert['reason'].replace('_', ' ')}"
        )
    st.divider()
    st.markdown("**Retrospective evaluation · 2025**")
    st.caption(
        "Model selection used earlier years. These historical results are separate from prospective scores. Errors use identical eligible dates within each horizon."
    )
    backtest = pd.read_csv(ROOT / "reports/workflow/test_metrics.csv")
    fig = go.Figure()
    for model, group in backtest.groupby("model"):
        fig.add_trace(
            go.Scatter(
                x=group.horizon,
                y=group.MAE,
                name={
                    "ridge_1": "Primary Ridge",
                    "persistence": "Persistence",
                    "weekly": "Weekly baseline",
                }.get(model, model),
                mode="lines+markers",
            )
        )
    fig.update_layout(legend=dict(orientation="h"))
    fig.update_xaxes(title="Forecast horizon (days)", dtick=1)
    fig.update_yaxes(title="MAE · AQI points")
    st.plotly_chart(
        style_chart(fig, 320), width="stretch", config={"displayModeBar": False}
    )
    with st.expander("See evaluation counts and interval coverage"):
        st.dataframe(backtest, hide_index=True, width="stretch")
        st.dataframe(
            pd.read_csv(ROOT / "reports/uncertainty/calibration.csv"),
            hide_index=True,
            width="stretch",
        )
    with st.expander("Forecast-weather challenger · exploratory 2026 comparison"):
        st.dataframe(
            pd.read_csv(ROOT / "reports/weather/comparison.csv"),
            hide_index=True,
            width="stretch",
        )
        st.caption(
            "Archived lead-specific forecasts are proxies for original issuance-time weather. This is exploratory evidence; there is no automatic promotion."
        )
with method:
    st.subheader("From observations to an upcoming forecast")
    st.markdown(
        "**01 · Observe**  NAPS Toronto West history from 2020, extended with Ontario observations and ECCC Pearson weather.\n\n**02 · Prepare**  Fixed-EST hourly alignment, strict coverage, all four pollutants required, no imputed AQI targets.\n\n**03 · Forecast**  Ridge regression, alpha 1, one model per horizon. Available AQI lags, seasonal terms and completed-day weather.\n\n**04 · Verify**  First-issued forecasts are preserved and later compared with observed AQI. Stale or incomplete refreshes block new issuance."
    )
    st.warning(
        "This is a four-pollutant station reconstruction, not an official Toronto city AQI, Canadian AQHI, or health advisory. Recent observations are provisional."
    )
    st.markdown(
        "Forecast publication runs twice daily at **11:17 and 17:17 UTC**. Scheduled runs can be delayed. The dashboard refresh button reads published reports and does not retrain models."
    )
    st.caption(f"Report source: {bundle['source']} · Revision: {bundle['revision']}")
    with st.expander("Data provenance and refresh status"):
        st.json(status)
        st.json(bundle["manifest"])
    st.link_button(
        "Full methods and limitations",
        "https://github.com/AhmedOT22/Air-Quality-Forecasting/blob/main/docs/operations.md",
    )
st.divider()
st.markdown(
    '<div class="footnote">Ahmed Ouazzani · Toronto AQI Observatory<br>Station-level experimental forecasts. NAPS / ECCC / Government of Ontario. Weather forecasts: Open-Meteo.com, CC BY 4.0.</div>',
    unsafe_allow_html=True,
)
