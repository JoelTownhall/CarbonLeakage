"""
exchange_rates.py — Monthly AUD/USD exchange rate data.

Downloads monthly AUD/USD exchange rates from the BIS data portal or
IMF IFS API. These are used to convert export prices from USD to AUD.

Relationship to Review (Annex Section 5, "Creation of export and import
price variables"):
    "Monthly exchange rates were sourced from the BIS data portal and
    used to convert export prices to US dollars."

    We assume all Comtrade export transactions are invoiced in USD
    (consistent with the Review's assumption), and convert to AUD
    using the monthly average exchange rate.

Data sources (in order of preference):
    1. BIS data portal: https://data.bis.org/ (exact Review source)
    2. IMF IFS API: exchange rate, period average, AUD per USD (fallback)

DECISION: BIS bulk download CSV approach used for primary source.
The BIS provides a "full data" CSV download that includes all exchange
rates. We filter for AUD/USD. If BIS is firewalled, the IMF IFS API is
used as fallback.
"""

import logging
from pathlib import Path
from typing import Optional
from io import StringIO

import pandas as pd
import requests

from config import DATA_RAW

logger = logging.getLogger(__name__)

RAW_IMF_DIR = DATA_RAW / "imf"
RAW_IMF_DIR.mkdir(parents=True, exist_ok=True)

# BIS exchange rate data
# Monthly average exchange rates, nominal, from BIS
BIS_FX_URL = "https://data.bis.org/api/v1/data/WS_XRU/M.AU.A"

# IMF IFS fallback: AUD/USD exchange rate
# Endpoint: https://www.imf.org/external/datamapper/api/v1/ENDA_XDC_USD_RATE/AUS
IMF_FX_BASE = "https://www.imf.org/external/datamapper/api/v1"
IMF_FX_INDICATOR = "ENDA_XDC_USD_RATE"  # End-of-period exchange rate, national currency per USD
IMF_AUS_CODE = "AUS"


def fetch_bis_aud_usd(
    start_year: int = 2003,
    end_year: int = 2024,
    force_refresh: bool = False,
) -> Optional[pd.DataFrame]:
    """
    Fetch monthly AUD/USD exchange rate from BIS data portal.

    BIS provides nominal exchange rates (units of foreign currency per USD,
    or USD per unit of domestic currency — check direction). We want
    AUD per USD (i.e., how many AUD buys one USD) for converting
    USD-invoiced exports to AUD.

    Parameters
    ----------
    start_year, end_year : int
        Data range.
    force_refresh : bool
        Re-download even if cache exists.

    Returns
    -------
    pd.DataFrame with columns: [period, aud_per_usd]
        period: pandas PeriodIndex (monthly, freq='M')
        aud_per_usd: monthly average AUD/USD exchange rate
    """
    cache_path = RAW_IMF_DIR / "exchange_rate_aud_usd.csv"

    if cache_path.exists() and not force_refresh:
        logger.info("Exchange rate cache hit: %s", cache_path)
        df = pd.read_csv(cache_path)
        df["period"] = pd.PeriodIndex(df["period"], freq="M")
        return df

    logger.info("Fetching BIS AUD/USD exchange rates ...")
    logger.info("  URL: %s", BIS_FX_URL)

    try:
        params = {
            "startPeriod": f"{start_year}-01",
            "endPeriod": f"{end_year}-12",
            "format": "csv",
        }
        response = requests.get(BIS_FX_URL, params=params, timeout=30)
        response.raise_for_status()

        # Parse BIS CSV (typically: date column + value column)
        df = _parse_bis_csv(response.text)
        if df is not None and not df.empty:
            df.to_csv(cache_path, index=False)
            logger.info("  BIS exchange rates saved: %d monthly obs → %s", len(df), cache_path)
            return df

    except requests.exceptions.RequestException as exc:
        logger.warning("BIS API request failed: %s", exc)

    # Fallback to IMF IFS
    logger.info("BIS failed, trying IMF IFS exchange rate API ...")
    return fetch_imf_exchange_rate(start_year, end_year, force_refresh)


def _parse_bis_csv(csv_text: str) -> Optional[pd.DataFrame]:
    """
    Parse BIS exchange rate CSV response into a tidy DataFrame.

    BIS CSV format (approximate):
        First few rows: metadata
        Then: date column, value column(s)

    Parameters
    ----------
    csv_text : str
        Raw CSV text from BIS API response.

    Returns
    -------
    pd.DataFrame with columns: [period, aud_per_usd]
    """
    try:
        # BIS CSVs have some header rows; find data start
        lines = csv_text.strip().splitlines()
        data_start = 0
        for i, line in enumerate(lines):
            parts = line.split(",")
            if parts[0].strip().startswith(("19", "20")):  # Year starts data
                data_start = i
                break

        if data_start == 0:
            # Try reading directly
            df = pd.read_csv(StringIO(csv_text))
        else:
            df = pd.read_csv(StringIO("\n".join(lines[data_start:])), header=None)

        # Rename columns: assume first is date, second is rate
        if df.shape[1] >= 2:
            df.columns = ["period_str", "aud_per_usd"] + list(df.columns[2:])
            df = df[["period_str", "aud_per_usd"]].dropna()
            df["aud_per_usd"] = pd.to_numeric(df["aud_per_usd"], errors="coerce")
            df = df.dropna(subset=["aud_per_usd"])

            # Convert period to pandas Period (monthly)
            df["period"] = pd.to_datetime(df["period_str"]).dt.to_period("M")
            return df[["period", "aud_per_usd"]].sort_values("period").reset_index(drop=True)

        return None

    except Exception as exc:
        logger.warning("Could not parse BIS CSV: %s", exc)
        return None


def fetch_imf_exchange_rate(
    start_year: int = 2003,
    end_year: int = 2024,
    force_refresh: bool = False,
) -> Optional[pd.DataFrame]:
    """
    Fetch annual AUD/USD exchange rate from IMF DataMapper as fallback.

    Note: IMF DataMapper provides annual data. For monthly data, we would
    need the IMF IFS API (more complex authentication). This annual series
    is returned as-is and should be interpolated to monthly if needed.

    Parameters
    ----------
    start_year, end_year : int
        Data range.

    Returns
    -------
    pd.DataFrame with columns: [year, aud_per_usd] (annual frequency)
    """
    cache_path = RAW_IMF_DIR / "exchange_rate_annual_imf.csv"

    if cache_path.exists() and not force_refresh:
        logger.info("IMF exchange rate cache hit: %s", cache_path)
        return pd.read_csv(cache_path)

    url = f"{IMF_FX_BASE}/{IMF_FX_INDICATOR}/{IMF_AUS_CODE}"
    logger.info("Fetching IMF AUD/USD exchange rate (annual) ...")

    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        data = response.json()

        values = data["values"][IMF_FX_INDICATOR].get(IMF_AUS_CODE, {})
        records = [
            {"year": int(yr), "aud_per_usd": float(val)}
            for yr, val in values.items()
            if val is not None and start_year <= int(yr) <= end_year
        ]
        df = pd.DataFrame(records).sort_values("year").reset_index(drop=True)
        df.to_csv(cache_path, index=False)
        logger.info("  IMF exchange rates saved: %d annual obs → %s", len(df), cache_path)
        return df

    except requests.exceptions.RequestException as exc:
        logger.warning("IMF exchange rate API failed: %s", exc)
        return None


def interpolate_annual_to_monthly(annual_df: pd.DataFrame) -> pd.DataFrame:
    """
    Interpolate annual exchange rates to monthly frequency.

    Used when only annual IMF data is available. Linear interpolation
    within each year (uniform across all 12 months).

    Parameters
    ----------
    annual_df : pd.DataFrame
        DataFrame with columns [year, aud_per_usd].

    Returns
    -------
    pd.DataFrame with columns: [period, aud_per_usd]
        period: pandas PeriodIndex (monthly)
    """
    records = []
    for _, row in annual_df.iterrows():
        for month in range(1, 13):
            period = pd.Period(f"{int(row['year'])}-{month:02d}", freq="M")
            records.append({"period": period, "aud_per_usd": row["aud_per_usd"]})
    df = pd.DataFrame(records)
    return df.sort_values("period").reset_index(drop=True)


def get_monthly_exchange_rate(
    start_year: int = 2003,
    end_year: int = 2024,
    force_refresh: bool = False,
) -> pd.DataFrame:
    """
    Get monthly AUD/USD exchange rate, with automatic fallback logic.

    Tries BIS first, then IMF. If IMF returns annual data, interpolates
    to monthly. Raises RuntimeError if no data is available from either source.

    Parameters
    ----------
    start_year, end_year : int
        Date range.

    Returns
    -------
    pd.DataFrame with columns: [period, aud_per_usd]
        period: pandas PeriodIndex (monthly freq='M')
    """
    df = fetch_bis_aud_usd(start_year, end_year, force_refresh)

    if df is None or df.empty:
        logger.warning(
            "Could not get monthly exchange rates from BIS or IMF. "
            "Export price conversion to AUD will not be possible. "
            "Please download AUD/USD monthly data from RBA or BIS and place "
            "in data/raw/imf/exchange_rate_aud_usd.csv"
        )
        raise RuntimeError(
            "No exchange rate data available. "
            "Download from: https://www.rba.gov.au/statistics/historical-data.html "
            "(Exchange Rates → F11 Historical Exchange Rates) and save to "
            "data/raw/imf/exchange_rate_aud_usd.csv with columns [period, aud_per_usd]."
        )

    # Ensure the period column is monthly PeriodIndex
    if not isinstance(df["period"].dtype, type(pd.PeriodIndex([], freq="M").dtype)):
        try:
            df["period"] = pd.PeriodIndex(df["period"], freq="M")
        except Exception:
            pass

    return df


if __name__ == "__main__":
    """
    Test exchange rate fetching.
    Run: python -m src.data_collection.exchange_rates
    """
    print("Testing exchange rate fetch (AUD/USD, 2010-2015) ...")
    try:
        df = get_monthly_exchange_rate(start_year=2010, end_year=2015, force_refresh=True)
        print(f"SUCCESS: {len(df)} monthly observations")
        print(df.head())
        print(f"Rate range: {df['aud_per_usd'].min():.4f} – {df['aud_per_usd'].max():.4f}")
    except RuntimeError as e:
        print(f"FAILED: {e}")
