# Real exchange rate app

A Streamlit web app that downloads monthly consumer price indices (CPI) and
exchange rates from the IMF and plots the bilateral **real exchange rate index**
and the **nominal exchange rate** for any two IMF economies (plus the Euro area).

## What the app does

1. You pick **Country 1** and **Country 2** from the IMF's member countries and the Euro area.
2. The app downloads four monthly series from the IMF SDMX 3.0 API (from January 1976 where available):
   the CPI of each country and each country's exchange rate against the US dollar.
3. You choose a **start month** and **end month**. The app calculates, for every month `t` in that sample:

   | Symbol | Meaning |
   |---|---|
   | `S(t)` | units of **Country 2** currency per **one** unit of **Country 1** currency |
   | `P1(t)`, `P2(t)` | monthly CPI of Country 1 and Country 2 |
   | `RER(t) = S(t) × P1(t) / P2(t)` | bilateral real exchange rate |
   | `RER*` | average of `RER(t)` over the valid months of the selected sample |
   | `Real index(t) = 100 × RER(t) / RER*` | real exchange rate index (averages 100 over the sample) |

   `RER*` is recalculated every time the dates change. The nominal rate `S(t)` is plotted in actual
   currency units and is never normalised.
4. You choose **Real**, **Nominal** or **Both** (two panels with separate axes, sharing the date axis),
   and you can **download a CSV** with every observation and calculation in the selected period.
5. An expander shows one month's calculation step by step so you can verify it by hand.

## Data source and conventions

* API: `https://api.imf.org/external/sdmx/3.0` (IMF Data, SDMX 3.0, no API key needed for these requests).
* Monthly CPI key: `{ISO3}.CPI._T.IX.M` in dataflow `IMF.STA/CPI`.
* Monthly exchange-rate key: `{ISO3}.XDC_USD.PA_RT.M` in dataflow `IMF.STA/ER`
  (local-currency units per US dollar, period average).
* The Euro area uses the IMF code `G163`.
* The IMF quotes every currency as *local units per US dollar*, so the app converts to the required
  direction: `S(t) = (Country 2 units per USD) ÷ (Country 1 units per USD)`.
  Example: UK as Country 1 and US as Country 2 gives **US dollars per pound** (around 1.2–1.4).
* The US dollar rate is 1 USD per USD by definition, so no exchange-rate series is downloaded for the United States.
* Months missing any of the three inputs are excluded from `RER*` and left blank in the chart and CSV.
* IMF coverage varies by country; some series start after 1976 and some countries have none.
  Kosovo (no official ISO3 code) is not in the list. To add or rename a country, edit the `COUNTRIES`
  dictionary at the top of `app.py`.

## CSV columns

`month, country1_iso3, country2_iso3, fx1_lcu_per_usd, fx2_lcu_per_usd, S_country2_per_country1,
cpi1, cpi2, RER, RER_star_sample_average, real_index, valid_month`

To check one row by hand: `S = fx2_lcu_per_usd ÷ fx1_lcu_per_usd`, `RER = S × cpi1 ÷ cpi2`,
`real_index = 100 × RER ÷ RER_star_sample_average`. The average of `real_index` over the valid rows is 100.

## Files

* `app.py` – the Streamlit application
* `requirements.txt` – Python packages (Python 3.12)
* `README.md` – this file

## Deploying on Streamlit Community Cloud

1. Put the three files at the top level of a public GitHub repository.
2. Sign in at <https://share.streamlit.io> with GitHub, choose **Create app**, select the repository,
   branch `main` and main file `app.py`.
3. In **Advanced settings** choose Python 3.12 and leave Secrets empty.
4. Click **Deploy**.

If the IMF ever starts refusing anonymous requests, request a key from the IMF data portal and add
`IMF_API_KEY = "your-key"` in the app's Secrets; the app picks it up automatically.

## Running locally (optional)

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Troubleshooting

* **"Some IMF series could not be downloaded"** – the IMF API is occasionally slow or unavailable.
  Click **Retry download**, or wait a minute and reload. The message shows the exact URL that failed;
  opening it in a browser shows whether the IMF is responding.
* **No overlapping months** – the chosen countries have no month with both CPIs and both exchange
  rates. Try another pair.
* Data is cached for six hours; use **Clear cache and re-download** in the "Data sources" expander
  to force a fresh download.
