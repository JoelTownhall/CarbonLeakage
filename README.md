# Carbon Leakage Review Replication

Replication of the ARDL trade-price elasticity analysis from Australia's
**Carbon Leakage Review Final Report** (DCCEEW, February 2025), using
publicly available data (UN Comtrade, ABS, IMF) in place of the restricted
BLADE microdata used in the Review.

Focus commodities: **cement, clinker, lime, crude steel, long steel, flat steel, treated flat steel**.

## Quick Start

```bash
pip install -r requirements.txt

# Run progress dashboard
streamlit run app/progress_tracker.py

# Session 1: Fetch all data (requires Comtrade API access)
python -m src.data_collection.comtrade_fetcher  # test clinker 2010
python -m src.data_collection.abs_fetcher        # test ABS connectivity
python -m src.data_collection.imf_fetcher        # test GDP fetch
```

## Project Structure

```
├── config.py                  # HS codes, model params, Review benchmarks
├── requirements.txt
├── data/
│   ├── raw/                   # API downloads (gitignored — reproduce with fetchers)
│   ├── processed/             # Model-ready quarterly datasets
│   └── reference/             # HS code mappings, Review benchmark values
├── src/
│   ├── data_collection/       # Phase 1: API wrappers
│   ├── data_processing/       # Phase 1-2: Aggregation and merging
│   ├── modelling/             # Phase 2: ARDL estimation
│   ├── leakage/               # Phase 3: Carbon cost and leakage calculation
│   └── visualisation/         # Charts and tables
├── notebooks/                 # Exploratory analysis
├── outputs/                   # Tables, figures, reports
└── app/                       # Streamlit dashboard
    └── progress_tracker.py    # Daily check-in dashboard
```

## Methodology

Follows Annex to the Carbon Leakage Review Final Report (DCCEEW, Feb 2025).
Key modelling choices:
- **ARDL model**: statsmodels.tsa.ardl, max 4 lags, AIC lag selection
- **Bounds test**: Pesaran et al. (2001) Case III
- **Standard errors**: Newey-West HAC, delta method for long-run coefficients
- **Demand controls**: ABS Construction GVA (steel/clinker), Final Demand (cement/lime), GDP (fallback)
- **Foreign demand**: Trade-weighted GDP index (China 47.7%, Japan 25.2%, Korea 11.5%, USA 9.0%, India 6.6%)

## Review Benchmark Results

| Commodity | Import Elasticity | Export Elasticity |
|-----------|-------------------|-------------------|
| Cement    | -2.46***          | -0.59             |
| Clinker   | -0.82*            | N/A (model failed)|
| Lime      | -3.00***          | -2.60**           |
| Crude Steel | -3.89^          | -3.60***          |
| Long Steel | -0.56^           | -0.45***          |
| Flat Steel | -0.53*           | -0.41             |
| Treated Flat Steel | N/A      | -3.38***          |

## API Keys

Set `COMTRADE_API_KEY` environment variable. See `APIs.txt` (gitignored).

## Notes on Data Differences

Our results will differ from the Review because:
1. We use 4–6 digit HS codes vs. 10-digit HTISC → more aggregation bias
2. Comtrade `primaryValue` vs. BLADE customs/FOB values
3. IMF annual GDP (interpolated quarterly) vs. OECD seasonal adjustment
4. Comtrade world aggregate vs. possible bilateral partner weights in BLADE
