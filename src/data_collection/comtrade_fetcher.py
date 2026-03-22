"""
comtrade_fetcher.py — UN Comtrade API wrapper for Australian trade data.

Downloads monthly import and export data for cement and steel commodity
groups from the UN Comtrade API (free tier, previewFinalData endpoint).
Results are cached to CSV to avoid redundant API calls.

Relationship to Review (Annex Section 5):
    The Review used 10-digit HTISC codes matched to specific Safeguard
    production variables within BLADE microdata. We use 6-digit HS codes
    from Comtrade, aggregated to the commodity groups in config.COMMODITY_HS_CODES.
    This introduces aggregation bias — see Annex Section 5 "Sources of bias".

    Price construction: price = primaryValue / netWgt ($/tonne).
    This is equivalent to the Review's customs value / weight for imports.
    For exports, the Review used FOB value; Comtrade's primaryValue is
    approximately FOB for exports.

    ASSUMPTION: Using world aggregate (partnerCode=0). The Review may have
    used bilateral partner weights — awaiting confirmation from DCCEEW team.
    See project memory note dated 2026-03-22.
"""

import time
import logging
from pathlib import Path
from typing import Optional

import pandas as pd
import comtradeapicall

from config import (
    COMTRADE_API_KEY,
    AUSTRALIA_REPORTER_CODE,
    WORLD_PARTNER_CODE,
    COMTRADE_START_YEAR,
    COMTRADE_END_YEAR,
    COMMODITY_HS_CODES,
    DATA_RAW,
)

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# Output directory for raw Comtrade CSVs
RAW_COMTRADE_DIR = DATA_RAW / "comtrade"
RAW_COMTRADE_DIR.mkdir(parents=True, exist_ok=True)

# Free-tier rate limiting: 1 second between calls, retry on empty response.
API_SLEEP_SECONDS = 1.5
MAX_RETRIES = 5


def _build_year_month_string(year: int) -> str:
    """
    Build a comma-separated period string for a full calendar year.

    e.g. 2010 → "201001,201002,...,201012"

    The Comtrade API accepts period strings in YYYYMM format. We query
    one year at a time (12 months per call) to stay well under the
    500-record free-tier limit when using world aggregate (partnerCode=0).
    """
    months = [f"{year}{m:02d}" for m in range(1, 13)]
    return ",".join(months)


def _query_comtrade_single(
    period: str,
    hs_code_str: str,
    api_key: str,
) -> Optional[pd.DataFrame]:
    """
    Execute a single Comtrade API call and return results as a DataFrame.

    Uses previewFinalData (free tier). Returns None on failure or empty
    response. Caller is responsible for retry logic.

    Parameters
    ----------
    period : str
        Comma-separated YYYYMM period string (e.g. "202001,202002,...").
    hs_code_str : str
        Comma-separated HS codes string (e.g. "252310,252321").
    api_key : str
        UN Comtrade subscription key.

    Returns
    -------
    pd.DataFrame or None
    """
    try:
        result = comtradeapicall.previewFinalData(
            typeCode="C",           # Commodities
            freqCode="M",           # Monthly
            clCode="HS",            # HS classification
            period=period,
            reporterCode=AUSTRALIA_REPORTER_CODE,
            cmdCode=hs_code_str,
            flowCode="M,X",         # M = imports, X = exports
            partnerCode=WORLD_PARTNER_CODE,  # World aggregate
            partner2Code=0,
            customsCode=None,
            motCode=None,
            maxRecords=500,
            format_output="JSON",
            aggregateBy=None,       # Do NOT aggregate — keep HS-level detail
            breakdownMode="classic",
            countOnly=None,
            includeDesc=True,
            subscription_key=api_key,
        )
        if result is None or (isinstance(result, pd.DataFrame) and result.empty):
            return None
        return result
    except Exception as exc:
        logger.warning("Comtrade API call failed: %s", exc)
        return None


def fetch_commodity_year(
    commodity: str,
    year: int,
    api_key: str = COMTRADE_API_KEY,
    force_refresh: bool = False,
) -> Optional[pd.DataFrame]:
    """
    Fetch one year of monthly Comtrade data for a commodity group.

    Results are cached to CSV at:
        data/raw/comtrade/{commodity}/{year}.csv

    If the file already exists and force_refresh=False, the cached CSV
    is returned immediately without an API call.

    Parameters
    ----------
    commodity : str
        Commodity name key from config.COMMODITY_HS_CODES
        (e.g. "clinker", "cement", "long_steel").
    year : int
        Calendar year to fetch (e.g. 2010).
    api_key : str
        UN Comtrade subscription key. Defaults to env variable.
    force_refresh : bool
        If True, re-download even if cache exists.

    Returns
    -------
    pd.DataFrame or None
        Monthly trade data with columns including:
        period, cmdCode, cmdDesc, flowCode, netWgt, primaryValue, etc.
    """
    if commodity not in COMMODITY_HS_CODES:
        raise ValueError(
            f"Unknown commodity '{commodity}'. "
            f"Valid options: {list(COMMODITY_HS_CODES.keys())}"
        )

    hs_codes = COMMODITY_HS_CODES[commodity]
    hs_code_str = ",".join(str(c) for c in hs_codes)
    period_str = _build_year_month_string(year)

    cache_dir = RAW_COMTRADE_DIR / commodity
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"{year}.csv"

    # Return cached result if available
    if cache_path.exists() and not force_refresh:
        logger.info("Cache hit: %s", cache_path)
        return pd.read_csv(cache_path, dtype=str)

    logger.info("Fetching Comtrade: commodity=%s, year=%d ...", commodity, year)

    # Retry loop — free tier sometimes returns empty on first call
    for attempt in range(1, MAX_RETRIES + 1):
        df = _query_comtrade_single(period_str, hs_code_str, api_key)
        if df is not None and not df.empty:
            df.to_csv(cache_path, index=False)
            logger.info("  Saved %d rows → %s", len(df), cache_path)
            time.sleep(API_SLEEP_SECONDS)
            return df
        else:
            logger.warning(
                "  Empty response (attempt %d/%d). Retrying in %ds ...",
                attempt, MAX_RETRIES, API_SLEEP_SECONDS * attempt,
            )
            time.sleep(API_SLEEP_SECONDS * attempt)

    logger.error("  Failed after %d attempts: commodity=%s year=%d", MAX_RETRIES, commodity, year)
    return None


def fetch_all_years(
    commodity: str,
    start_year: int = COMTRADE_START_YEAR,
    end_year: int = COMTRADE_END_YEAR,
    api_key: str = COMTRADE_API_KEY,
    force_refresh: bool = False,
) -> pd.DataFrame:
    """
    Fetch all years for a commodity and return a single concatenated DataFrame.

    Iterates year by year (one API call per year) with rate-limiting sleep
    between calls. Already-cached years are skipped.

    Parameters
    ----------
    commodity : str
        Commodity key from config.COMMODITY_HS_CODES.
    start_year : int
        First year to fetch (default: 2003, matching Review sample start Q3 2003).
    end_year : int
        Last year to fetch (default: 2024).
    api_key : str
        UN Comtrade subscription key.
    force_refresh : bool
        Re-download even if cache exists.

    Returns
    -------
    pd.DataFrame
        All monthly observations concatenated. Empty DataFrame if all calls fail.
    """
    frames = []
    years = list(range(start_year, end_year + 1))
    logger.info(
        "Starting full fetch: commodity=%s, years=%d–%d (%d API calls)",
        commodity, start_year, end_year, len(years),
    )

    for year in years:
        df = fetch_commodity_year(commodity, year, api_key, force_refresh)
        if df is not None and not df.empty:
            frames.append(df)
        else:
            logger.warning("  No data returned for %s %d", commodity, year)

    if not frames:
        logger.error("No data retrieved for commodity: %s", commodity)
        return pd.DataFrame()

    combined = pd.concat(frames, ignore_index=True)
    logger.info(
        "Completed fetch for %s: %d total rows, %d years",
        commodity, len(combined), len(frames),
    )
    return combined


def fetch_all_commodities(
    start_year: int = COMTRADE_START_YEAR,
    end_year: int = COMTRADE_END_YEAR,
    api_key: str = COMTRADE_API_KEY,
    force_refresh: bool = False,
) -> dict[str, pd.DataFrame]:
    """
    Fetch raw Comtrade data for all target commodities.

    Saves one CSV per commodity per year to data/raw/comtrade/{commodity}/.
    Returns a dict of {commodity: DataFrame}.

    This is the main entry point for data collection (Session 1, Step 1A).
    Run this once; subsequent runs will use cached CSVs.

    Parameters
    ----------
    start_year, end_year : int
        Data range to fetch.
    api_key : str
        UN Comtrade subscription key.
    force_refresh : bool
        If True, re-download all data ignoring cache.

    Returns
    -------
    dict[str, pd.DataFrame]
    """
    results = {}
    for commodity in COMMODITY_HS_CODES:
        logger.info("=" * 60)
        logger.info("Fetching commodity: %s", commodity.upper())
        logger.info("=" * 60)
        df = fetch_all_years(commodity, start_year, end_year, api_key, force_refresh)
        results[commodity] = df
    return results


def load_raw_comtrade(commodity: str) -> pd.DataFrame:
    """
    Load all cached raw CSVs for a commodity into a single DataFrame.

    Use this to reload previously downloaded data without hitting the API.

    Parameters
    ----------
    commodity : str
        Commodity key from config.COMMODITY_HS_CODES.

    Returns
    -------
    pd.DataFrame
        Combined raw trade data for all available years.
    """
    cache_dir = RAW_COMTRADE_DIR / commodity
    if not cache_dir.exists():
        raise FileNotFoundError(
            f"No cached data found for '{commodity}' at {cache_dir}. "
            "Run fetch_all_years() first."
        )

    csv_files = sorted(cache_dir.glob("*.csv"))
    if not csv_files:
        raise FileNotFoundError(f"No CSV files found in {cache_dir}.")

    frames = [pd.read_csv(f, dtype=str) for f in csv_files]
    combined = pd.concat(frames, ignore_index=True)
    logger.info("Loaded %d rows from %d files for %s", len(combined), len(csv_files), commodity)
    return combined


if __name__ == "__main__":
    """
    Quick test: fetch one year of clinker data (smallest commodity, single HS code).
    Run: python -m src.data_collection.comtrade_fetcher
    """
    import sys
    import os

    # Load API key from APIs.txt if not in environment
    if not COMTRADE_API_KEY:
        apis_file = Path(__file__).parent.parent.parent / "APIs.txt"
        if apis_file.exists():
            lines = apis_file.read_text().strip().splitlines()
            key = lines[1].strip() if len(lines) > 1 else ""
            os.environ["COMTRADE_API_KEY"] = key
            # Re-import after setting env
            from config import COMTRADE_API_KEY as api_key
        else:
            print("ERROR: COMTRADE_API_KEY not set and APIs.txt not found.")
            sys.exit(1)
    else:
        api_key = COMTRADE_API_KEY

    print("Testing Comtrade fetch: clinker, 2010 ...")
    df = fetch_commodity_year("clinker", 2010, api_key=api_key, force_refresh=True)

    if df is not None and not df.empty:
        print(f"SUCCESS: {len(df)} rows returned")
        print(df[["period", "cmdCode", "flowCode", "netWgt", "primaryValue"]].head(10))
    else:
        print("FAILED: No data returned. Check API key and network access.")
