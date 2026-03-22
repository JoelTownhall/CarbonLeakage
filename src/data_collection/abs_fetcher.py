"""
abs_fetcher.py — ABS data downloader for domestic demand control variables.

Downloads Australian National Accounts data from the ABS API (abs.gov.au).
We need three series (Annex Section 4, "Demand variables"):
    1. Construction GVA — used for clinker and steel import models
    2. Final Demand      — used for cement, lime, flat steel import models
    3. GDP (Chain Vol.)  — fallback demand control

The Review sourced these from ABS Cat. 5206.0 (Australian National Accounts:
National Income, Expenditure and Product), Table 6, seasonally adjusted.

ABS API endpoint: https://api.data.abs.gov.au/
Documentation: https://api.data.abs.gov.au/rest/

DECISION MADE: Using the ABS SDMX-JSON API (v1) rather than the `readabs`
R package (not available in Python). If Joel obtains better ABS access later,
this module can be swapped out without changing downstream code.

NOTE: ABS series IDs can change between catalogue releases. The IDs below
were valid as of late 2024. If you get a 404 or empty response, the series
IDs may need updating from abs.gov.au/statistics/economy/national-accounts.
"""

import logging
import time
from pathlib import Path
from typing import Optional

import pandas as pd
import requests

from config import DATA_RAW

logger = logging.getLogger(__name__)

RAW_ABS_DIR = DATA_RAW / "abs"
RAW_ABS_DIR.mkdir(parents=True, exist_ok=True)

# ABS SDMX-JSON API base URL
ABS_API_BASE = "https://api.data.abs.gov.au/data"
ABS_API_HEADERS = {"Accept": "application/vnd.sdmx.data+json;version=1.0"}

# -----------------------------------------------------------------------
# Series keys for key demand variables — verified against ABS SDMX API
# (tested 2026-03-22, data available 2003-Q3 to 2024-Q4)
#
# Construction GVA: ABS ANA_IND_GVA dataflow
#   Key: VCH.GPM.SSS.20.E.AUS.Q
#   = Chain volume measures, GDP contribution, All sectors,
#     Seasonally Adjusted, Construction (E), Australia, Quarterly
#
# Final Demand: ABS ANA_EXP dataflow
#   Key: VCH.DFD.SSS.20.AUS.Q
#   = Chain volume measures, Domestic final demand, All sectors,
#     Seasonally Adjusted, Australia, Quarterly
#
# GDP: ABS ANA_AGG dataflow
#   Key: M1.GPM.20.AUS.Q
#   = Chain volume measures, Gross domestic product,
#     Seasonally Adjusted, Australia, Quarterly
# -----------------------------------------------------------------------

ABS_SERIES = {
    "construction_gva": {
        "dataflow": "ABS,ANA_IND_GVA,1.0.0",
        "key": "VCH.GPM.SSS.20.E.AUS.Q",
        "description": "Construction GVA (chain vol, seasonally adjusted)",
        "used_for": "Clinker and steel import models (Annex Section 4)",
    },
    "final_demand": {
        "dataflow": "ABS,ANA_EXP,1.0.0",
        "key": "VCH.DFD.SSS.20.AUS.Q",
        "description": "Domestic Final Demand (chain vol, seasonally adjusted)",
        "used_for": "Cement, lime, flat steel import models",
    },
    "gdp": {
        "dataflow": "ABS,ANA_AGG,1.0.0",
        "key": "M1.GPM.20.AUS.Q",
        "description": "GDP (chain vol, seasonally adjusted)",
        "used_for": "Fallback demand control for remaining commodities",
    },
}

# Mapping from ABS series name to which commodities use it as control variable
# (from Review Annex Section 4 Table)
DEMAND_CONTROL_FOR_COMMODITY = {
    "clinker":            "construction_gva",
    "cement":             "final_demand",
    "lime":               "final_demand",
    "crude_steel":        "construction_gva",
    "long_steel":         "construction_gva",
    "flat_steel":         "final_demand",
    "treated_flat_steel": "final_demand",
}


def fetch_abs_sdmx(
    series_name: str,
    start_period: str = "2003-Q3",
    end_period: str = "2024-Q4",
    force_refresh: bool = False,
) -> Optional[pd.DataFrame]:
    """
    Attempt to fetch ABS data via the SDMX-JSON API.

    Saves result to data/raw/abs/{series_name}.csv.
    Returns None if the API is unreachable or the series ID is incorrect.

    Parameters
    ----------
    series_name : str
        One of "construction_gva", "final_demand", "gdp".
    start_period : str
        Start period in YYYY-QN format (e.g. "2003-Q3").
    end_period : str
        End period in YYYY-QN format (e.g. "2024-Q4").
    force_refresh : bool
        Re-download even if cache exists.

    Returns
    -------
    pd.DataFrame with columns: [period, value, series_name]
        period is a pandas Period with freq='Q'.
    """
    cache_path = RAW_ABS_DIR / f"{series_name}.csv"

    if cache_path.exists() and not force_refresh:
        logger.info("ABS cache hit: %s", cache_path)
        df = pd.read_csv(cache_path)
        df["period"] = pd.PeriodIndex(df["period"], freq="Q")
        return df

    if series_name not in ABS_SERIES:
        raise ValueError(f"Unknown ABS series: {series_name}. Options: {list(ABS_SERIES.keys())}")

    config = ABS_SERIES[series_name]
    url = (
        f"{ABS_API_BASE}/{config['dataflow']}/{config['key']}"
        f"?startPeriod={start_period}&endPeriod={end_period}"
    )

    logger.info("Fetching ABS series '%s' from API ...", series_name)
    logger.info("  URL: %s", url)

    try:
        response = requests.get(url, headers=ABS_API_HEADERS, timeout=30)
        response.raise_for_status()
        data = response.json()
        df = _parse_sdmx_json(data, series_name)
        df.to_csv(cache_path, index=False)
        logger.info("  Saved %d observations → %s", len(df), cache_path)
        return df
    except requests.exceptions.RequestException as exc:
        logger.warning("ABS API request failed: %s", exc)
        logger.warning("  Try downloading CSV manually from abs.gov.au (Cat. 5206.0 Table 6)")
        return None
    except Exception as exc:
        logger.warning("ABS data parsing failed: %s", exc)
        return None


def _parse_sdmx_json(data: dict, series_name: str) -> pd.DataFrame:
    """
    Parse ABS SDMX-JSON response into a tidy DataFrame.

    Parameters
    ----------
    data : dict
        Parsed JSON response from ABS SDMX API.
    series_name : str
        Name to assign to the value column.

    Returns
    -------
    pd.DataFrame with columns: [period, value, series_name]
    """
    try:
        # ABS SDMX-JSON structure: data → dataSets → [0] → series → {key} → observations
        dataset = data["data"]["dataSets"][0]["series"]
        structure = data["data"]["structure"]

        # Extract time dimension values (in the observation dimension)
        time_dim = structure["dimensions"]["observation"][0]["values"]
        time_values = [t["id"] for t in time_dim]

        records = []
        for _series_key, series_data in dataset.items():
            for obs_idx, obs_vals in series_data["observations"].items():
                period_str = time_values[int(obs_idx)]
                value = obs_vals[0]
                records.append({"period": period_str, "value": value})

        df = pd.DataFrame(records)
        df["series_name"] = series_name
        # Convert ABS period format (e.g. "2010-Q1") to pandas Period
        df["period"] = pd.PeriodIndex(df["period"], freq="Q")
        df = df.sort_values("period").reset_index(drop=True)
        return df

    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError(f"Could not parse SDMX-JSON response: {exc}") from exc


def load_abs_csv_manual(series_name: str, csv_path: Path) -> pd.DataFrame:
    """
    Load an ABS series from a manually downloaded CSV file.

    Use this as a fallback when the API is unavailable (e.g., firewall blocks
    abs.gov.au). Download the relevant CSV from:
        https://www.abs.gov.au/statistics/economy/national-accounts/
        australian-national-accounts-national-income-expenditure-and-product/
        latest-release

    The CSV should have a "Period" column and a value column. This function
    handles the standard ABS CSV format (with metadata rows at top).

    Parameters
    ----------
    series_name : str
        Name to assign (e.g. "construction_gva").
    csv_path : Path
        Path to the downloaded ABS CSV file.

    Returns
    -------
    pd.DataFrame with columns: [period, value, series_name]
    """
    # ABS CSVs typically have ~9 metadata rows before data starts
    # Try to auto-detect by finding the row with "Series ID" or a date column
    try:
        # Read raw to detect structure
        raw = pd.read_csv(csv_path, header=None, nrows=15)
        # Find the row index where dates start (look for row starting with a year)
        data_start = None
        for i, row in raw.iterrows():
            val = str(row.iloc[0])
            if val[:4].isdigit() and len(val) >= 7:
                data_start = i
                break

        if data_start is None:
            raise ValueError("Could not auto-detect data start row in ABS CSV.")

        df_raw = pd.read_csv(csv_path, skiprows=data_start, header=0)
        logger.info("ABS CSV loaded from %s (%d rows)", csv_path, len(df_raw))

        # This is a generic loader — caller may need to select the right column
        logger.warning(
            "Manual CSV load: columns are %s. "
            "You may need to specify which column contains the '%s' series.",
            list(df_raw.columns), series_name,
        )
        return df_raw

    except Exception as exc:
        raise ValueError(f"Failed to load ABS CSV from {csv_path}: {exc}") from exc


def get_demand_control(
    commodity: str,
    start_period: str = "2003-Q3",
    end_period: str = "2024-Q4",
) -> pd.DataFrame:
    """
    Get the appropriate demand control variable for a given commodity.

    Looks up which ABS series to use (from DEMAND_CONTROL_FOR_COMMODITY),
    attempts to fetch from API, returns a DataFrame ready for model assembly.

    Parameters
    ----------
    commodity : str
        Commodity name (e.g. "clinker", "cement").
    start_period, end_period : str
        Date range for the series.

    Returns
    -------
    pd.DataFrame with columns: [period, ln_demand]
        period: pandas PeriodIndex (quarterly)
        ln_demand: natural log of the demand index (for ARDL model)
    """
    import numpy as np

    if commodity not in DEMAND_CONTROL_FOR_COMMODITY:
        raise ValueError(f"No demand control mapping for commodity: {commodity}")

    series_name = DEMAND_CONTROL_FOR_COMMODITY[commodity]
    logger.info(
        "Demand control for %s: %s (%s)",
        commodity, series_name, ABS_SERIES[series_name]["description"],
    )

    df = fetch_abs_sdmx(series_name, start_period, end_period)

    if df is None or df.empty:
        raise RuntimeError(
            f"Could not retrieve ABS series '{series_name}' for commodity '{commodity}'. "
            "Please download the CSV manually from abs.gov.au and use load_abs_csv_manual()."
        )

    # Take natural log for ARDL model (Annex Section 4)
    df = df.copy()
    df["ln_demand"] = np.log(df["value"].astype(float))
    return df[["period", "ln_demand"]].rename(columns={"ln_demand": f"ln_demand_{series_name}"})


if __name__ == "__main__":
    """
    Test ABS API connectivity.
    Run: python -m src.data_collection.abs_fetcher
    """
    print("Testing ABS API connectivity ...")
    print("Attempting to fetch Construction GVA ...")
    df = fetch_abs_sdmx("construction_gva", start_period="2010-Q1", end_period="2015-Q4")

    if df is not None and not df.empty:
        print(f"SUCCESS: {len(df)} quarterly observations")
        print(df.head())
    else:
        print("FAILED or API blocked by firewall.")
        print("Action required: Download ABS Cat. 5206.0 Table 6 CSV manually")
        print("from https://www.abs.gov.au and place in data/raw/abs/")
        print("Then use load_abs_csv_manual() to load the data.")
