"""
Real Exchange Rate App
======================

A Streamlit app that downloads monthly consumer price indices (CPI) and
exchange rates from the IMF SDMX 3.0 API and computes a bilateral real
exchange rate index for any two IMF economies (plus the Euro area).

Definitions used throughout (they match the assignment brief exactly):

    S(t)    = units of Country 2 currency per ONE unit of Country 1 currency
    P1(t)   = monthly CPI of Country 1
    P2(t)   = monthly CPI of Country 2
    RER(t)  = S(t) x P1(t) / P2(t)
    RER*    = average of RER(t) over the valid months in the selected sample
    Index(t)= 100 x RER(t) / RER*

IMF exchange rates are published as local-currency units per US dollar
(series XDC_USD, period average).  Therefore

    S(t) = [Country 2 units per USD] / [Country 1 units per USD]

Example: UK as Country 1, US as Country 2  ->  S = (USD per USD) / (GBP per USD)
                                              = USD per GBP  (about 1.2-1.4).

Python 3.12 compatible.  Dependencies: streamlit, pandas, numpy, plotly, requests.
"""

from __future__ import annotations

import io
import os
import re
import unicodedata

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st
from plotly.subplots import make_subplots
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

IMF_BASE_URL = "https://api.imf.org/external/sdmx/3.0"
IMF_AGENCY = "IMF.STA"                 # agency that owns the CPI and ER dataflows
CPI_DATAFLOW = "CPI"                   # consumer price index dataflow
ER_DATAFLOW = "ER"                     # exchange rate dataflow
CPI_KEY_TEMPLATE = "{iso3}.CPI._T.IX.M"        # all-items CPI, index, monthly
ER_KEY_TEMPLATE = "{iso3}.XDC_USD.PA_RT.M"     # LCU per USD, period average, monthly

FIRST_MONTH = pd.Period("1976-01", freq="M")   # earliest month we keep
USD_CODE = "USA"                                # the IMF rate for the US is 1 by definition
EURO_AREA_CODE = "G163"                         # IMF code for the Euro area

REQUEST_TIMEOUT_SECONDS = 60
CACHE_TTL_SECONDS = 6 * 60 * 60                 # re-download from the IMF after 6 hours

# Chart colours (validated colour-blind-safe pair) and chrome
COLOR_REAL = "#2a78d6"      # blue  - real index
COLOR_NOMINAL = "#eb6834"   # orange - nominal exchange rate
COLOR_REFERENCE = "#898781" # muted grey - "average = 100" line
COLOR_GRID = "#e1e0d9"

# IMF member countries (ISO3 codes) plus the Euro area.
# Kosovo (an IMF member) has no official ISO3 code and is omitted.
COUNTRIES: dict[str, str] = {
    "Afghanistan": "AFG", "Albania": "ALB", "Algeria": "DZA", "Andorra": "AND",
    "Angola": "AGO", "Antigua and Barbuda": "ATG", "Argentina": "ARG", "Armenia": "ARM",
    "Australia": "AUS", "Austria": "AUT", "Azerbaijan": "AZE", "Bahamas, The": "BHS",
    "Bahrain": "BHR", "Bangladesh": "BGD", "Barbados": "BRB", "Belarus": "BLR",
    "Belgium": "BEL", "Belize": "BLZ", "Benin": "BEN", "Bhutan": "BTN",
    "Bolivia": "BOL", "Bosnia and Herzegovina": "BIH", "Botswana": "BWA", "Brazil": "BRA",
    "Brunei Darussalam": "BRN", "Bulgaria": "BGR", "Burkina Faso": "BFA", "Burundi": "BDI",
    "Cabo Verde": "CPV", "Cambodia": "KHM", "Cameroon": "CMR", "Canada": "CAN",
    "Central African Republic": "CAF", "Chad": "TCD", "Chile": "CHL", "China": "CHN",
    "Colombia": "COL", "Comoros": "COM", "Congo, Democratic Republic of the": "COD",
    "Congo, Republic of": "COG", "Costa Rica": "CRI", "Côte d'Ivoire": "CIV",
    "Croatia": "HRV", "Cyprus": "CYP", "Czech Republic": "CZE", "Denmark": "DNK",
    "Djibouti": "DJI", "Dominica": "DMA", "Dominican Republic": "DOM", "Ecuador": "ECU",
    "Egypt": "EGY", "El Salvador": "SLV", "Equatorial Guinea": "GNQ", "Eritrea": "ERI",
    "Estonia": "EST", "Eswatini": "SWZ", "Ethiopia": "ETH", "Euro area": EURO_AREA_CODE,
    "Fiji": "FJI", "Finland": "FIN", "France": "FRA", "Gabon": "GAB",
    "Gambia, The": "GMB", "Georgia": "GEO", "Germany": "DEU", "Ghana": "GHA",
    "Greece": "GRC", "Grenada": "GRD", "Guatemala": "GTM", "Guinea": "GIN",
    "Guinea-Bissau": "GNB", "Guyana": "GUY", "Haiti": "HTI", "Honduras": "HND",
    "Hungary": "HUN", "Iceland": "ISL", "India": "IND", "Indonesia": "IDN",
    "Iran": "IRN", "Iraq": "IRQ", "Ireland": "IRL", "Israel": "ISR",
    "Italy": "ITA", "Jamaica": "JAM", "Japan": "JPN", "Jordan": "JOR",
    "Kazakhstan": "KAZ", "Kenya": "KEN", "Kiribati": "KIR", "Korea, Republic of": "KOR",
    "Kuwait": "KWT", "Kyrgyz Republic": "KGZ", "Lao P.D.R.": "LAO", "Latvia": "LVA",
    "Lebanon": "LBN", "Lesotho": "LSO", "Liberia": "LBR", "Libya": "LBY",
    "Liechtenstein": "LIE", "Lithuania": "LTU", "Luxembourg": "LUX", "Madagascar": "MDG",
    "Malawi": "MWI", "Malaysia": "MYS", "Maldives": "MDV", "Mali": "MLI",
    "Malta": "MLT", "Marshall Islands": "MHL", "Mauritania": "MRT", "Mauritius": "MUS",
    "Mexico": "MEX", "Micronesia, Federated States of": "FSM", "Moldova": "MDA",
    "Mongolia": "MNG", "Montenegro": "MNE", "Morocco": "MAR", "Mozambique": "MOZ",
    "Myanmar": "MMR", "Namibia": "NAM", "Nauru": "NRU", "Nepal": "NPL",
    "Netherlands": "NLD", "New Zealand": "NZL", "Nicaragua": "NIC", "Niger": "NER",
    "Nigeria": "NGA", "North Macedonia": "MKD", "Norway": "NOR", "Oman": "OMN",
    "Pakistan": "PAK", "Palau": "PLW", "Panama": "PAN", "Papua New Guinea": "PNG",
    "Paraguay": "PRY", "Peru": "PER", "Philippines": "PHL", "Poland": "POL",
    "Portugal": "PRT", "Qatar": "QAT", "Romania": "ROU", "Russian Federation": "RUS",
    "Rwanda": "RWA", "Samoa": "WSM", "San Marino": "SMR", "São Tomé and Príncipe": "STP",
    "Saudi Arabia": "SAU", "Senegal": "SEN", "Serbia": "SRB", "Seychelles": "SYC",
    "Sierra Leone": "SLE", "Singapore": "SGP", "Slovak Republic": "SVK", "Slovenia": "SVN",
    "Solomon Islands": "SLB", "Somalia": "SOM", "South Africa": "ZAF", "South Sudan": "SSD",
    "Spain": "ESP", "Sri Lanka": "LKA", "St. Kitts and Nevis": "KNA", "St. Lucia": "LCA",
    "St. Vincent and the Grenadines": "VCT", "Sudan": "SDN", "Suriname": "SUR",
    "Sweden": "SWE", "Switzerland": "CHE", "Syria": "SYR", "Tajikistan": "TJK",
    "Tanzania": "TZA", "Thailand": "THA", "Timor-Leste": "TLS", "Togo": "TGO",
    "Tonga": "TON", "Trinidad and Tobago": "TTO", "Tunisia": "TUN", "Türkiye": "TUR",
    "Turkmenistan": "TKM", "Tuvalu": "TUV", "Uganda": "UGA", "Ukraine": "UKR",
    "United Arab Emirates": "ARE", "United Kingdom": "GBR", "United States": "USA",
    "Uruguay": "URY", "Uzbekistan": "UZB", "Vanuatu": "VUT", "Venezuela": "VEN",
    "Vietnam": "VNM", "Yemen": "YEM", "Zambia": "ZMB", "Zimbabwe": "ZWE",
}

# Labels shown in the drop-downs, e.g. "United Kingdom (GBR)", sorted ignoring accents
def _sort_key(item: tuple[str, str]) -> str:
    return unicodedata.normalize("NFKD", item[0]).encode("ascii", "ignore").decode().lower()


COUNTRY_LABELS = [f"{name} ({code})" for name, code in sorted(COUNTRIES.items(), key=_sort_key)]
LABEL_TO_CODE = {f"{name} ({code})": code for name, code in COUNTRIES.items()}
CODE_TO_NAME = {code: name for name, code in COUNTRIES.items()}


# ---------------------------------------------------------------------------
# IMF data access
# ---------------------------------------------------------------------------

class ImfFetchError(Exception):
    """Raised when an IMF series cannot be downloaded or parsed."""

    def __init__(self, message: str, url: str = ""):
        super().__init__(message)
        self.url = url


def get_api_key() -> str:
    """Optional IMF API key: environment variable first, then Streamlit Secrets.

    Normal downloads do not need a key.  If the IMF ever starts refusing
    anonymous requests, add IMF_API_KEY = "..." in the Streamlit Secrets box.
    """
    key = os.environ.get("IMF_API_KEY", "").strip()
    if key:
        return key
    try:
        return str(st.secrets.get("IMF_API_KEY", "")).strip()
    except Exception:          # no secrets file at all -> Streamlit raises
        return ""


def build_url(dataflow: str, series_key: str) -> str:
    """URL of one series.  '+' means 'latest version of the dataflow'."""
    return f"{IMF_BASE_URL}/data/dataflow/{IMF_AGENCY}/{dataflow}/+/{series_key}"


def _session_with_retries() -> requests.Session:
    """HTTP session that retries transient failures (rate limits, 5xx)."""
    retry = Retry(
        total=3,
        backoff_factor=1.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET"]),
        raise_on_status=False,
    )
    session = requests.Session()
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session


def _to_month(value) -> pd.Period | None:
    """Convert an SDMX time period ('1976-01', '1976-M01', '197601') to a monthly Period."""
    text = str(value).strip()
    if ": " in text:                       # SDMX-CSV 'id: label' style, keep the id
        text = text.split(": ", 1)[0]
    match = re.fullmatch(r"(\d{4})-?M?(\d{1,2})", text)
    if not match:
        return None
    year, month = int(match.group(1)), int(match.group(2))
    if not 1 <= month <= 12:
        return None
    return pd.Period(year=year, month=month, freq="M")


def _tidy(periods: list, values: list, url: str) -> pd.Series:
    """Build a clean monthly series from parallel lists of periods and values."""
    frame = pd.DataFrame({"period": periods, "value": pd.to_numeric(pd.Series(values, dtype="object"), errors="coerce")})
    frame = frame.dropna(subset=["period", "value"])
    if frame.empty:
        raise ImfFetchError("The IMF response contained no usable monthly observations.", url)
    frame = frame.drop_duplicates(subset="period", keep="last").sort_values("period")
    series = pd.Series(frame["value"].to_numpy(dtype=float),
                       index=pd.PeriodIndex(frame["period"].tolist(), freq="M"))
    return series[series.index >= FIRST_MONTH]


def parse_sdmx_csv(text: str, url: str) -> pd.Series:
    """Parse an SDMX-CSV 2.0 message.  Only TIME_PERIOD and OBS_VALUE are needed."""
    frame = pd.read_csv(io.StringIO(text), dtype=str, keep_default_na=False)
    upper = {col: col.strip().upper() for col in frame.columns}
    time_col = next((c for c, u in upper.items() if u.startswith("TIME_PERIOD")), None)
    value_col = next((c for c, u in upper.items() if u.startswith("OBS_VALUE")), None)
    if time_col is None or value_col is None:
        raise ImfFetchError(
            "The IMF response was not in the expected SDMX-CSV format "
            f"(columns found: {', '.join(map(str, frame.columns[:12]))}).", url)
    action_col = next((c for c, u in upper.items() if u == "ACTION"), None)
    if action_col is not None:          # 'D' rows are deletions, not data
        frame = frame[frame[action_col].str.upper() != "D"]
    periods = [_to_month(v) for v in frame[time_col]]
    return _tidy(periods, frame[value_col].tolist(), url)


def parse_sdmx_json(payload: dict, url: str) -> pd.Series:
    """Parse an SDMX-JSON (1.0 or 2.0) data message - fallback if the API ignores our CSV request."""
    data = payload.get("data", payload)
    structures = data.get("structures") or ([data["structure"]] if "structure" in data else [])
    if not structures:
        raise ImfFetchError("The IMF JSON response had no structure information.", url)
    obs_dims = structures[0].get("dimensions", {}).get("observation", [])
    time_pos = next((i for i, d in enumerate(obs_dims) if str(d.get("id", "")).upper() == "TIME_PERIOD"), None)
    if time_pos is None:
        raise ImfFetchError("The IMF JSON response had no TIME_PERIOD dimension.", url)
    time_values = [v.get("id") or v.get("name") for v in obs_dims[time_pos].get("values", [])]

    periods, values = [], []

    def take(obs_key: str, obs_value) -> None:
        parts = str(obs_key).split(":")
        idx = int(parts[time_pos]) if time_pos < len(parts) else int(parts[0])
        periods.append(_to_month(time_values[idx]))
        values.append(obs_value[0] if isinstance(obs_value, list) and obs_value else obs_value)

    for dataset in data.get("dataSets", []):
        for series in (dataset.get("series") or {}).values():
            for key, value in (series.get("observations") or {}).items():
                take(key, value)
        for key, value in (dataset.get("observations") or {}).items():
            take(key, value)
    return _tidy(periods, values, url)


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def fetch_imf_series(dataflow: str, series_key: str, _api_key: str = "") -> tuple[pd.Series, dict]:
    """Download one monthly series from the IMF.  Cached so repeated runs are instant.

    Returns (series indexed by monthly Period, info dict).  Raises ImfFetchError.
    """
    url = build_url(dataflow, series_key)
    headers = {
        "Accept": "application/vnd.sdmx.data+csv;version=2.0.0",
        "User-Agent": "real-exchange-rate-app/1.0 (Streamlit; educational use)",
    }
    if _api_key:
        headers["Ocp-Apim-Subscription-Key"] = _api_key

    try:
        response = _session_with_retries().get(url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)
    except requests.RequestException as exc:
        raise ImfFetchError(f"Could not reach the IMF API ({type(exc).__name__}).", url) from exc

    status = response.status_code
    if status == 404:
        raise ImfFetchError("The IMF has no series for this key (HTTP 404) - the country may not be covered.", url)
    if status in (401, 403):
        raise ImfFetchError(f"The IMF API refused the request (HTTP {status}). "
                            "If this persists, add an IMF_API_KEY in Streamlit Secrets.", url)
    if status == 429:
        raise ImfFetchError("The IMF API is rate-limiting requests (HTTP 429). Wait a minute and retry.", url)
    if status >= 400:
        raise ImfFetchError(f"The IMF API returned HTTP {status}: {response.text[:200]!r}", url)

    text = response.text.strip()
    if not text:
        raise ImfFetchError("The IMF API returned an empty response (no observations).", url)

    content_type = response.headers.get("Content-Type", "").lower()
    if text.startswith("{") or "json" in content_type:
        series = parse_sdmx_json(response.json(), url)
    else:
        series = parse_sdmx_csv(text, url)
    if series.empty:
        raise ImfFetchError(f"No observations from {FIRST_MONTH} onwards.", url)

    info = {
        "url": url,
        "observations": int(series.size),
        "first": str(series.index.min()),
        "last": str(series.index.max()),
    }
    return series, info


def load_country(iso3: str, api_key: str) -> dict:
    """Fetch CPI and exchange-rate series for one economy."""
    result = {"iso3": iso3, "cpi": None, "fx": None, "cpi_info": None, "fx_info": None,
              "errors": [], "notes": []}
    try:
        result["cpi"], result["cpi_info"] = fetch_imf_series(CPI_DATAFLOW, CPI_KEY_TEMPLATE.format(iso3=iso3), api_key)
    except ImfFetchError as exc:
        result["errors"].append(f"CPI for {iso3}: {exc}  \nURL: {exc.url}")

    if iso3 == USD_CODE:
        result["notes"].append("United States: exchange rate is 1 USD per USD by definition, so nothing is downloaded.")
    else:
        try:
            result["fx"], result["fx_info"] = fetch_imf_series(ER_DATAFLOW, ER_KEY_TEMPLATE.format(iso3=iso3), api_key)
        except ImfFetchError as exc:
            result["errors"].append(f"Exchange rate for {iso3}: {exc}  \nURL: {exc.url}")
    return result


# ---------------------------------------------------------------------------
# Economics
# ---------------------------------------------------------------------------

def build_dataset(country1: dict, country2: dict) -> pd.DataFrame:
    """Combine the four input series on one monthly calendar and compute S and RER.

    Columns:
      fx1_lcu_per_usd  Country 1 currency units per USD (IMF, period average)
      fx2_lcu_per_usd  Country 2 currency units per USD
      cpi1, cpi2       consumer price indices
      S                Country 2 units per 1 unit of Country 1 currency = fx2 / fx1
      RER              S x cpi1 / cpi2
    """
    available = [s for s in (country1["cpi"], country2["cpi"], country1["fx"], country2["fx"]) if s is not None]
    last_month = max(s.index.max() for s in available)
    calendar = pd.period_range(FIRST_MONTH, last_month, freq="M")

    data = pd.DataFrame(index=calendar)
    data.index.name = "month"
    data["fx1_lcu_per_usd"] = 1.0 if country1["fx"] is None else country1["fx"].reindex(calendar).to_numpy()
    data["fx2_lcu_per_usd"] = 1.0 if country2["fx"] is None else country2["fx"].reindex(calendar).to_numpy()
    data["cpi1"] = country1["cpi"].reindex(calendar).to_numpy()
    data["cpi2"] = country2["cpi"].reindex(calendar).to_numpy()

    data["S"] = data["fx2_lcu_per_usd"] / data["fx1_lcu_per_usd"]
    data["RER"] = data["S"] * data["cpi1"] / data["cpi2"]
    return data


def apply_sample_window(data: pd.DataFrame, start: pd.Period, end: pd.Period) -> tuple[pd.DataFrame, float]:
    """Restrict to the selected months, compute RER* on valid months and the real index."""
    window = data.loc[start:end].copy()
    window["valid"] = np.isfinite(window["RER"].to_numpy(dtype=float))   # S, P1 and P2 all present
    rer_star = float(window.loc[window["valid"], "RER"].mean()) if window["valid"].any() else float("nan")
    window["RER_star"] = rer_star
    window["real_index"] = 100.0 * window["RER"] / rer_star
    return window, rer_star


def export_frame(window: pd.DataFrame, code1: str, code2: str) -> pd.DataFrame:
    """Tidy table for the CSV download (all months in the window, gaps included)."""
    out = window.reset_index()
    out["month"] = out["month"].astype(str)
    out.insert(1, "country1_iso3", code1)
    out.insert(2, "country2_iso3", code2)
    out = out.rename(columns={
        "S": "S_country2_per_country1",
        "RER_star": "RER_star_sample_average",
        "valid": "valid_month",
    })
    columns = ["month", "country1_iso3", "country2_iso3",
               "fx1_lcu_per_usd", "fx2_lcu_per_usd", "S_country2_per_country1",
               "cpi1", "cpi2", "RER", "RER_star_sample_average", "real_index", "valid_month"]
    return out[columns]


# ---------------------------------------------------------------------------
# Charts
# ---------------------------------------------------------------------------

def make_chart(window: pd.DataFrame, mode: str, name1: str, name2: str) -> go.Figure:
    x = window.index.to_timestamp()
    nominal_label = f"{name2} currency per 1 unit of {name1} currency"

    real_trace = go.Scatter(
        x=x, y=window["real_index"], mode="lines", name="Real index (sample average = 100)",
        line=dict(color=COLOR_REAL, width=2), connectgaps=False,
        hovertemplate="%{y:.2f}<extra>Real index</extra>",
    )
    reference_trace = go.Scatter(
        x=[x.min(), x.max()], y=[100, 100], mode="lines", name="Sample average = 100",
        line=dict(color=COLOR_REFERENCE, width=1, dash="dot"), hoverinfo="skip",
    )
    nominal_trace = go.Scatter(
        x=x, y=window["S"], mode="lines", name=f"Nominal S ({nominal_label})",
        line=dict(color=COLOR_NOMINAL, width=2), connectgaps=False,
        hovertemplate="%{y:.4f}<extra>Nominal S</extra>",
    )

    if mode == "Both":
        fig = make_subplots(
            rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.10,
            subplot_titles=("Real exchange rate index", "Nominal exchange rate S(t)"),
        )
        fig.add_trace(real_trace, row=1, col=1)
        fig.add_trace(reference_trace, row=1, col=1)
        fig.add_trace(nominal_trace, row=2, col=1)
        fig.update_yaxes(title_text="Index (RER* = 100)", row=1, col=1)
        fig.update_yaxes(title_text=nominal_label, row=2, col=1)
        height = 760
    elif mode == "Real":
        fig = go.Figure([real_trace, reference_trace])
        fig.update_yaxes(title_text="Index (RER* = 100)")
        fig.update_layout(title="Real exchange rate index")
        height = 520
    else:
        fig = go.Figure([nominal_trace])
        fig.update_yaxes(title_text=nominal_label)
        fig.update_layout(title="Nominal exchange rate S(t) - actual currency units")
        height = 520

    fig.update_layout(
        template="plotly_white", height=height, hovermode="x unified",
        legend=dict(orientation="h", yanchor="top", y=-0.08, xanchor="left", x=0),
        margin=dict(l=70, r=30, t=60, b=80),
    )
    fig.update_xaxes(showgrid=True, gridcolor=COLOR_GRID, tickformat="%b %Y")
    fig.update_yaxes(showgrid=True, gridcolor=COLOR_GRID, zeroline=False)
    return fig


# ---------------------------------------------------------------------------
# Streamlit user interface
# ---------------------------------------------------------------------------

def main() -> None:
    st.set_page_config(page_title="Real Exchange Rate App", page_icon="💱", layout="wide")
    st.title("Real exchange rate app (IMF data)")
    st.caption(
        "S(t) = Country 2 currency per 1 unit of Country 1 currency · "
        "RER(t) = S(t) × P1(t) / P2(t) · Real index(t) = 100 × RER(t) / RER*, "
        "where RER* is the average RER over the selected sample."
    )

    # ----- Sidebar: country selection ---------------------------------------
    st.sidebar.header("Countries")
    label1 = st.sidebar.selectbox("Country 1 (its currency is priced)", COUNTRY_LABELS,
                                  index=COUNTRY_LABELS.index("United Kingdom (GBR)"))
    label2 = st.sidebar.selectbox("Country 2 (its currency is the unit of S)", COUNTRY_LABELS,
                                  index=COUNTRY_LABELS.index("United States (USA)"))
    code1, code2 = LABEL_TO_CODE[label1], LABEL_TO_CODE[label2]
    name1, name2 = CODE_TO_NAME[code1], CODE_TO_NAME[code2]
    if code1 == code2:
        st.sidebar.warning("Both countries are the same, so S = 1 and the real index is flat at 100.")

    # ----- Download data -----------------------------------------------------
    api_key = get_api_key()
    with st.spinner("Downloading IMF data…"):
        country1 = load_country(code1, api_key)
        country2 = load_country(code2, api_key)

    errors = country1["errors"] + country2["errors"]
    if errors:
        st.error("Some IMF series could not be downloaded:\n\n" + "\n\n".join(f"- {e}" for e in errors))
        st.info("Live IMF downloads sometimes fail temporarily. Click **Retry download** below, "
                "or try another country pair. If the problem persists, copy the message above.")
        if st.button("Retry download"):
            st.cache_data.clear()
            st.rerun()
        st.stop()

    data = build_dataset(country1, country2)
    valid_months = data.index[data["RER"].notna()]
    if len(valid_months) == 0:
        st.error("The two countries have no overlapping months with both CPI and exchange-rate data.")
        st.stop()

    # ----- Sidebar: sample period and chart type -----------------------------
    st.sidebar.header("Sample period")
    month_labels = [str(p) for p in data.index]
    first_valid, last_valid = str(valid_months.min()), str(valid_months.max())
    start_label = st.sidebar.selectbox("Start month", month_labels, index=month_labels.index(first_valid))
    end_label = st.sidebar.selectbox("End month", month_labels, index=month_labels.index(last_valid))
    start, end = pd.Period(start_label, freq="M"), pd.Period(end_label, freq="M")
    if start > end:
        st.error("The start month must not be after the end month.")
        st.stop()

    st.sidebar.header("Chart")
    mode = st.sidebar.radio("Series to display", ["Real", "Nominal", "Both"], index=2, horizontal=True)
    st.sidebar.caption(f"Complete data for this pair runs from {first_valid} to {last_valid} "
                       "(there may be gaps inside that range). RER* is recalculated whenever "
                       "the sample period changes.")

    # ----- Calculations ------------------------------------------------------
    window, rer_star = apply_sample_window(data, start, end)
    n_valid, n_total = int(window["valid"].sum()), int(len(window))
    if n_valid == 0:
        st.error("No month in the selected period has complete data. Choose a different period.")
        st.stop()
    if n_valid < n_total:
        st.warning(f"{n_total - n_valid} of {n_total} months in the selected period lack CPI or exchange-rate data; "
                   "they are excluded from RER* and shown as gaps.")

    last_valid_row = window[window["valid"]].iloc[-1]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Valid months in sample", f"{n_valid} / {n_total}")
    c2.metric("RER* (sample average)", f"{rer_star:,.4f}")
    c3.metric(f"Latest S ({last_valid_row.name})", f"{last_valid_row['S']:,.4f}")
    c4.metric(f"Latest real index ({last_valid_row.name})", f"{last_valid_row['real_index']:,.2f}")

    st.subheader(f"{name1} vs {name2}: {start_label} to {end_label}")
    st.caption(f"S(t) = {name2} currency per 1 unit of {name1} currency "
               f"= (IMF {code2} units per USD) ÷ (IMF {code1} units per USD). "
               f"Mean of the real index over the {n_valid} valid months = "
               f"{window.loc[window['valid'], 'real_index'].mean():.2f}.")
    st.plotly_chart(make_chart(window, mode, name1, name2))

    # ----- Download ----------------------------------------------------------
    export = export_frame(window, code1, code2)
    st.download_button(
        label="Download CSV (all observations and calculations in the sample period)",
        data=export.to_csv(index=False).encode("utf-8"),
        file_name=f"real_exchange_rate_{code1}_{code2}_{start_label}_{end_label}.csv",
        mime="text/csv",
    )

    # ----- Manual verification helper ---------------------------------------
    with st.expander("Verify one month's calculation by hand"):
        valid_labels = [str(p) for p in window.index[window["valid"]]]
        chosen = st.selectbox("Month", valid_labels, index=len(valid_labels) - 1)
        row = window.loc[pd.Period(chosen, freq="M")]
        st.markdown(
            f"**Inputs for {chosen}** (also in the CSV)\n\n"
            f"- Country 1 ({code1}) currency per USD: `{row['fx1_lcu_per_usd']:.6f}`\n"
            f"- Country 2 ({code2}) currency per USD: `{row['fx2_lcu_per_usd']:.6f}`\n"
            f"- P1 = CPI {code1}: `{row['cpi1']:.4f}`\n"
            f"- P2 = CPI {code2}: `{row['cpi2']:.4f}`\n\n"
            f"**Calculation**\n\n"
            f"- S = {row['fx2_lcu_per_usd']:.6f} ÷ {row['fx1_lcu_per_usd']:.6f} = **{row['S']:.6f}** "
            f"({name2} currency per 1 unit of {name1} currency)\n"
            f"- RER = S × P1 ÷ P2 = {row['S']:.6f} × {row['cpi1']:.4f} ÷ {row['cpi2']:.4f} = **{row['RER']:.6f}**\n"
            f"- RER* = average RER over {n_valid} valid months = **{rer_star:.6f}**\n"
            f"- Real index = 100 × {row['RER']:.6f} ÷ {rer_star:.6f} = **{row['real_index']:.4f}**"
        )

    # ----- Data table --------------------------------------------------------
    with st.expander("Data table for the selected period"):
        st.dataframe(export, hide_index=True)

    # ----- Data sources and status ------------------------------------------
    with st.expander("Data sources and download status"):
        for label, country in ((f"Country 1 - {name1} ({code1})", country1), (f"Country 2 - {name2} ({code2})", country2)):
            st.markdown(f"**{label}**")
            for kind, info in (("CPI", country["cpi_info"]), ("Exchange rate (LCU per USD)", country["fx_info"])):
                if info:
                    st.markdown(f"- {kind}: {info['observations']} monthly observations, "
                                f"{info['first']} to {info['last']}  \n  `{info['url']}`")
            for note in country["notes"]:
                st.markdown(f"- {note}")
        st.markdown(
            f"Source: IMF Data (SDMX 3.0 API), dataflows `{IMF_AGENCY}/{CPI_DATAFLOW}` and `{IMF_AGENCY}/{ER_DATAFLOW}`. "
            f"Keys: `{CPI_KEY_TEMPLATE}` and `{ER_KEY_TEMPLATE}`. Data from {FIRST_MONTH} where available; "
            f"results are cached for {CACHE_TTL_SECONDS // 3600} hours."
        )
        if st.button("Clear cache and re-download"):
            st.cache_data.clear()
            st.rerun()

    # ----- Method notes ------------------------------------------------------
    with st.expander("Method and caveats"):
        st.markdown(
            """
- **Direction of S.** The IMF publishes each currency as *local units per US dollar*.
  Dividing Country 2's rate by Country 1's rate gives Country 2 units per one unit of
  Country 1's currency, the direction required here. With the UK as Country 1 and the
  US as Country 2, S is US dollars per pound.
- **Real exchange rate.** RER(t) = S(t) × P1(t) / P2(t). A rise means Country 1's goods
  became more expensive relative to Country 2's (a real appreciation of Country 1's currency).
- **Index.** CPIs have arbitrary base years, so the level of RER is not meaningful on its own.
  The index divides RER by its average RER* over the selected months, so it averages
  exactly 100 over the valid months of the sample and changes whenever the dates change.
- **Nominal S is never normalised** - it is plotted in actual currency units.
- **Gaps.** Months missing any of the three inputs are excluded from RER* and left blank
  in the chart and CSV. IMF coverage varies by country; some series start after 1976.
- **Euro-area members.** For countries that adopted the euro, the IMF series switch from the
  legacy currency to the euro, which can create a break in S; use "Euro area" (IMF code G163)
  for a consistent euro series from 1999.
"""
        )


if __name__ == "__main__":
    main()
