"""
imf_fetcher.py — IMF/OECD data fetcher for foreign demand control variable.

Downloads real GDP (seasonally adjusted, quarterly) for Australia's top 5
trading partners, then constructs the trade-weighted GDP index used as the
demand control variable in all export ARDL models.

Relationship to Review (Annex Section 4, "Demand variables"):
    "For export models, the commodity-invariant trade-weighted index of five
    top trading partners' GDPs were used as a foreign demand control.
    GDP data were seasonally adjusted and sourced from the OECD."

    Weights (from DFAT export statistics, 2015 base year):
        China: 47.7%, Japan: 25.2%, Korea: 11.5%, USA: 9.0%, India: 6.6%

    We use the IMF IFS (International Financial Statistics) API as a
    substitute for OECD.Stat. The OECD API can be added later if preferred.

Data source: IMF Data API
    Base URL: https://datahelp.imf.org/knowledgebase/articles/
    API endpoint: https://www.imf.org/external/datamapper/api/v1/
    Dataflow: NGDP_RPCH (Real GDP growth) or IFS quarterly GDP series

DECISION: Using IMF DataMapper API (JSON) as primary source. This provides
real GDP annual growth rates which we convert to index series. If OECD
data is preferred (exact match to Review), the OECD API URL is provided
as a comment below. Joel to advise preferred data source for Session 2.
"""

import logging
import time
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import requests

from config import DATA_RAW, TRADE_WEIGHT_GDP, IMF_COUNTRY_CODES

logger = logging.getLogger(__name__)

RAW_IMF_DIR = DATA_RAW / "imf"
RAW_IMF_DIR.mkdir(parents=True, exist_ok=True)

# -----------------------------------------------------------------------
# IMF DataMapper API (annual data, GDP growth rates)
# -----------------------------------------------------------------------
IMF_DATAMAPPER_BASE = "https://www.imf.org/external/datamapper/api/v1"
IMF_GDP_INDICATOR = "NGDP_RPCH"  # Real GDP, % change (annual)

# -----------------------------------------------------------------------
# OECD Quarterly GDP API (preferred for exact Review replication)
# This is the source the Review used. If accessible, this gives
# seasonally adjusted quarterly real GDP directly.
# OECD.Stat SDMX API:
#   https://stats.oecd.org/SDMX-JSON/data/QNA/{country}.B1_GE.VPVOBARSA.Q/
# -----------------------------------------------------------------------
OECD_API_BASE = "https://stats.oecd.org/SDMX-JSON/data"
OECD_GDP_DATAFLOW = "QNA"
OECD_GDP_KEY_TEMPLATE = "{country}.B1_GE.VPVOBARSA.Q"  # SA real GDP, volume

# Country codes for OECD API
OECD_COUNTRY_CODES = {
    "CHN": "CHN",
    "JPN": "JPN",
    "KOR": "KOR",
    "USA": "USA",
    "IND": "IND",
}


def fetch_oecd_gdp_quarterly(
    country_code: str,
    start_year: int = 2003,
    end_year: int = 2024,
    force_refresh: bool = False,
) -> Optional[pd.DataFrame]:
    """
    Fetch quarterly seasonally-adjusted real GDP from OECD.Stat for one country.

    This is the preferred data source (matches the Review's OECD source).

    Parameters
    ----------
    country_code : str
        ISO3 country code (CHN, JPN, KOR, USA, IND).
    start_year, end_year : int
        Data range.
    force_refresh : bool
        Re-download even if cache exists.

    Returns
    -------
    pd.DataFrame with columns: [period, gdp_index, country]
        period: pandas PeriodIndex (quarterly)
        gdp_index: real GDP index (base = 2015 average = 100)
    """
    cache_path = RAW_IMF_DIR / f"oecd_gdp_{country_code}.csv"

    if cache_path.exists() and not force_refresh:
        logger.info("OECD cache hit: %s", cache_path)
        df = pd.read_csv(cache_path)
        df["period"] = pd.PeriodIndex(df["period"], freq="Q")
        return df

    oecd_code = OECD_COUNTRY_CODES.get(country_code)
    if not oecd_code:
        raise ValueError(f"No OECD code mapping for: {country_code}")

    key = OECD_GDP_KEY_TEMPLATE.format(country=oecd_code)
    url = (
        f"{OECD_API_BASE}/{OECD_GDP_DATAFLOW}/{key}"
        f"?startTime={start_year}-Q1&endTime={end_year}-Q4"
        f"&dimensionAtObservation=TIME_PERIOD&format=jsondata"
    )

    logger.info("Fetching OECD quarterly GDP: %s ...", country_code)
    logger.info("  URL: %s", url)

    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        data = response.json()
        df = _parse_oecd_sdmx(data, country_code)
        df.to_csv(cache_path, index=False)
        logger.info("  Saved %d quarters → %s", len(df), cache_path)
        time.sleep(0.5)  # Be polite to OECD API
        return df
    except requests.exceptions.RequestException as exc:
        logger.warning("OECD API request failed for %s: %s", country_code, exc)
        return None
    except Exception as exc:
        logger.warning("OECD data parsing failed for %s: %s", country_code, exc)
        return None


def _parse_oecd_sdmx(data: dict, country_code: str) -> pd.DataFrame:
    """
    Parse OECD SDMX-JSON response into tidy quarterly GDP DataFrame.

    Parameters
    ----------
    data : dict
        Parsed JSON response from OECD SDMX API.
    country_code : str
        Country identifier for labelling.

    Returns
    -------
    pd.DataFrame with columns: [period, gdp_index, country]
    """
    try:
        dataset = data["dataSets"][0]["series"]
        structure = data["structure"]

        # Time dimension
        time_dim = structure["dimensions"]["observation"][0]["values"]
        time_values = [t["id"] for t in time_dim]

        records = []
        for _key, series_data in dataset.items():
            for obs_idx, obs_vals in series_data["observations"].items():
                period_str = time_values[int(obs_idx)]
                value = obs_vals[0]
                if value is not None:
                    records.append({"period": period_str, "gdp_raw": float(value)})

        df = pd.DataFrame(records)
        df["period"] = pd.PeriodIndex(df["period"], freq="Q")
        df = df.sort_values("period").reset_index(drop=True)
        df["country"] = country_code

        # Normalise to index (2015 average = 100)
        mask_2015 = (df["period"].dt.year == 2015)
        if mask_2015.any():
            base = df.loc[mask_2015, "gdp_raw"].mean()
            df["gdp_index"] = df["gdp_raw"] / base * 100
        else:
            df["gdp_index"] = df["gdp_raw"]

        return df[["period", "gdp_index", "country"]]

    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError(f"Could not parse OECD SDMX-JSON: {exc}") from exc


def fetch_imf_gdp_annual(
    country_code: str,
    force_refresh: bool = False,
) -> Optional[pd.DataFrame]:
    """
    Fetch annual real GDP growth rate from IMF DataMapper API.

    NOTE: OECD quarterly data was attempted but API URL format has changed
    and returns incorrect filtered results. IMF annual data is used as the
    primary GDP source. Growth rates are interpolated to quarterly frequency
    in build_trade_weighted_gdp(). This introduces some smoothing but is
    acceptable for an approximation.

    DECISION MADE: Using IMF annual GDP (interpolated to quarterly) rather
    than OECD quarterly. OECD API URL format needs investigation.
    Flag for Joel: if you have access to OECD quarterly GDP CSVs, place
    them in data/raw/imf/oecd_gdp_{CHN|JPN|KOR|USA|IND}.csv and the
    fetcher will use them instead.

    Parameters
    ----------
    country_code : str
        ISO3 country code (CHN, JPN, KOR, USA, IND).

    Returns
    -------
    pd.DataFrame with columns: [year, gdp_growth_pct, country]
    """
    imf_code = IMF_COUNTRY_CODES.get(country_code, country_code)
    cache_path = RAW_IMF_DIR / f"imf_gdp_annual_{country_code}.csv"

    if cache_path.exists() and not force_refresh:
        logger.info("IMF annual cache hit: %s", cache_path)
        return pd.read_csv(cache_path)

    url = f"{IMF_DATAMAPPER_BASE}/{IMF_GDP_INDICATOR}/{imf_code}"
    logger.info("Fetching IMF annual GDP growth: %s (%s) ...", country_code, imf_code)

    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        data = response.json()

        values = data["values"][IMF_GDP_INDICATOR].get(imf_code, {})
        records = [
            {"year": int(yr), "gdp_growth_pct": float(val), "country": country_code}
            for yr, val in values.items()
            if val is not None
        ]
        df = pd.DataFrame(records).sort_values("year").reset_index(drop=True)
        df.to_csv(cache_path, index=False)
        logger.info("  Saved %d annual observations → %s", len(df), cache_path)
        return df

    except requests.exceptions.RequestException as exc:
        logger.warning("IMF API request failed for %s: %s", country_code, exc)
        return None


def annual_growth_to_quarterly_index(
    annual_df: pd.DataFrame,
    base_year: int = 2015,
) -> pd.DataFrame:
    """
    Convert annual GDP growth rates to a quarterly index by interpolation.

    This is a rough approximation used only when quarterly OECD data is
    unavailable. Annual growth rates are distributed evenly across quarters.

    Parameters
    ----------
    annual_df : pd.DataFrame
        DataFrame with columns [year, gdp_growth_pct, country].
    base_year : int
        Year to set index = 100.

    Returns
    -------
    pd.DataFrame with columns: [period, gdp_index, country]
    """
    country = annual_df["country"].iloc[0]
    records = []

    # Build annual index from growth rates
    annual_df = annual_df.sort_values("year").copy()
    idx = 100.0
    annual_idx = {}

    # Find base year first
    base_row = annual_df[annual_df["year"] == base_year]
    if base_row.empty:
        logger.warning("Base year %d not found for %s; using first year as 100", base_year, country)
        annual_df.loc[annual_df.index[0], "gdp_growth_pct"] = 0

    # Calculate index for each year
    prev_idx = 100.0
    for _, row in annual_df.iterrows():
        if row["year"] == base_year:
            annual_idx[row["year"]] = 100.0
        elif row["year"] > base_year:
            prev_yr = row["year"] - 1
            prev_val = annual_idx.get(prev_yr, 100.0)
            annual_idx[row["year"]] = prev_val * (1 + row["gdp_growth_pct"] / 100)
        else:
            # Before base year: work backwards
            annual_idx[row["year"]] = 100.0  # Will be overwritten properly below

    # Re-do backwards pass
    years_sorted = sorted(annual_df["year"].tolist())
    if base_year in years_sorted:
        base_pos = years_sorted.index(base_year)
        annual_idx[base_year] = 100.0
        # Forward pass
        for yr in years_sorted[base_pos + 1:]:
            g = annual_df.loc[annual_df["year"] == yr, "gdp_growth_pct"].values[0]
            annual_idx[yr] = annual_idx[yr - 1] * (1 + g / 100)
        # Backward pass
        for yr in reversed(years_sorted[:base_pos]):
            g = annual_df.loc[annual_df["year"] == yr + 1, "gdp_growth_pct"].values[0]
            annual_idx[yr] = annual_idx[yr + 1] / (1 + g / 100)

    # Interpolate to quarterly (flat within year — simplest approach)
    for yr, idx_val in annual_idx.items():
        for q in range(1, 5):
            period = pd.Period(f"{yr}Q{q}", freq="Q")
            records.append({"period": period, "gdp_index": idx_val, "country": country})

    df = pd.DataFrame(records).sort_values("period").reset_index(drop=True)
    return df


def build_trade_weighted_gdp(
    start_year: int = 2003,
    end_year: int = 2024,
    force_refresh: bool = False,
) -> pd.DataFrame:
    """
    Construct the trade-weighted GDP index for export models.

    Attempts to fetch OECD quarterly data first; falls back to IMF annual
    data if OECD is unavailable. Combines the five partner countries using
    the weights from config.TRADE_WEIGHT_GDP.

    Relationship to Review (Annex Section 4):
        "The weights were based on DFAT export statistics for 2015
        (China: 47.7%, Japan: 25.2%, Korea: 11.5%, USA: 9.0%, India: 6.6%).
        GDP data were seasonally adjusted and sourced from the OECD."

    Parameters
    ----------
    start_year, end_year : int
        Date range.
    force_refresh : bool
        Re-download all source data.

    Returns
    -------
    pd.DataFrame with columns: [period, ln_trade_weighted_gdp]
        period: pandas PeriodIndex (quarterly)
        ln_trade_weighted_gdp: natural log of weighted GDP index
    """
    cache_path = RAW_IMF_DIR / "trade_weighted_gdp.csv"

    if cache_path.exists() and not force_refresh:
        logger.info("Trade-weighted GDP cache hit: %s", cache_path)
        df = pd.read_csv(cache_path)
        df["period"] = pd.PeriodIndex(df["period"], freq="Q")
        return df

    country_dfs = {}
    for iso3, weight in TRADE_WEIGHT_GDP.items():
        logger.info("Fetching GDP for %s (weight: %.1f%%) ...", iso3, weight * 100)

        # Try OECD quarterly first
        df_q = fetch_oecd_gdp_quarterly(iso3, start_year, end_year, force_refresh)

        if df_q is None or df_q.empty:
            logger.warning(
                "OECD quarterly unavailable for %s, falling back to IMF annual", iso3
            )
            df_a = fetch_imf_gdp_annual(iso3, force_refresh)
            if df_a is not None and not df_a.empty:
                df_q = annual_growth_to_quarterly_index(df_a)
            else:
                logger.error("Could not retrieve GDP for %s from any source.", iso3)
                continue

        country_dfs[iso3] = df_q

    if not country_dfs:
        raise RuntimeError(
            "Could not retrieve GDP data for any partner country. "
            "Check network access to OECD and IMF APIs."
        )

    # Align all series to a common quarterly index
    all_periods = sorted(
        set().union(*[set(df["period"]) for df in country_dfs.values()])
    )
    result = pd.DataFrame({"period": all_periods})

    for iso3, df in country_dfs.items():
        df_indexed = df.set_index("period")[["gdp_index"]].rename(
            columns={"gdp_index": iso3}
        )
        result = result.merge(df_indexed, left_on="period", right_index=True, how="left")

    # Compute weighted sum: weighted_gdp = Σ weight_i * gdp_i
    result["trade_weighted_gdp"] = sum(
        TRADE_WEIGHT_GDP[iso3] * result[iso3]
        for iso3 in TRADE_WEIGHT_GDP
        if iso3 in result.columns
    )

    # Take natural log for ARDL model
    result["ln_trade_weighted_gdp"] = np.log(result["trade_weighted_gdp"])

    # Save to cache
    output = result[["period", "ln_trade_weighted_gdp"]].copy()
    output["period"] = output["period"].astype(str)
    output.to_csv(cache_path, index=False)
    logger.info("Trade-weighted GDP saved: %d quarterly observations", len(output))

    output["period"] = pd.PeriodIndex(output["period"], freq="Q")
    return output


if __name__ == "__main__":
    """
    Test GDP data fetching.
    Run: python -m src.data_collection.imf_fetcher
    """
    print("Testing OECD quarterly GDP fetch (Japan, 2010-2015) ...")
    df = fetch_oecd_gdp_quarterly("JPN", 2010, 2015, force_refresh=True)
    if df is not None and not df.empty:
        print(f"OECD SUCCESS: {len(df)} quarters for Japan")
        print(df.head())
    else:
        print("OECD FAILED — trying IMF annual fallback ...")
        df_a = fetch_imf_gdp_annual("JPN", force_refresh=True)
        if df_a is not None:
            print(f"IMF annual: {len(df_a)} observations")
            print(df_a.head())
        else:
            print("IMF also failed. Both APIs may be blocked by firewall.")
            print("Action: Joel to provide GDP data CSV files or request API access.")
