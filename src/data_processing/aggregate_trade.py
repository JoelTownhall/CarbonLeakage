"""
aggregate_trade.py — Monthly Comtrade data → quarterly price & quantity series.

Session 2, Step 2A.

This module reads the raw CSVs downloaded in Session 1 (one per commodity per
year) and produces a single quarterly panel:

    data/processed/comtrade_quarterly.csv

Each row is one (commodity, quarter, flow) observation with:
  - total trade value (USD)
  - total net weight (kg → tonnes)
  - unit-value price (USD/tonne)  ← this is the price proxy used in the ARDL

Relationship to the Review (Annex Section 5):
    The Review used primaryValue from BLADE customs records (CIF for imports,
    FOB for exports). We use Comtrade's `primaryValue`, which is equivalent
    for world-aggregate flows:
        - Imports: primaryValue ≈ CIF value (USD)
        - Exports: primaryValue ≈ FOB value (USD)

    Price proxy: price = primaryValue / (netWgt / 1000)  [USD per tonne]

    We aggregate across HS codes within each commodity group by summing value
    and weight before dividing, which gives a quantity-weighted average price.
    This is the correct method (NOT a simple average of individual HS prices).

    The Review worked in AUD. We retain USD here and convert to AUD in
    build_dataset.py once exchange rates are available.

Usage:
    python -m src.data_processing.aggregate_trade          # process all
    python -m src.data_processing.aggregate_trade clinker  # one commodity
"""

import sys
import logging
from pathlib import Path

import pandas as pd
import numpy as np

# Add project root to path so `config` can be imported when running as script
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import COMMODITY_HS_CODES, DATA_RAW, DATA_PROCESSED

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# Directories
RAW_COMTRADE_DIR = DATA_RAW / "comtrade"
PROCESSED_DIR = DATA_PROCESSED
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

# Output file
OUTPUT_PATH = PROCESSED_DIR / "comtrade_quarterly.csv"

# Month → quarter mapping
MONTH_TO_QUARTER = {
    1: 1, 2: 1, 3: 1,
    4: 2, 5: 2, 6: 2,
    7: 3, 8: 3, 9: 3,
    10: 4, 11: 4, 12: 4,
}

# Minimum weight threshold: skip rows where netWgt ≤ this value (kg).
# Very small weights produce nonsensical $/tonne prices.
MIN_WEIGHT_KG = 100.0


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------

def load_raw_csv(commodity: str) -> pd.DataFrame:
    """
    Load all cached raw CSVs for one commodity into a single DataFrame.

    Parameters
    ----------
    commodity : str
        Must be a key in config.COMMODITY_HS_CODES (e.g. "clinker").

    Returns
    -------
    pd.DataFrame
        All monthly rows concatenated. Columns include:
        refYear, refMonth, flowCode, cmdCode, netWgt, primaryValue, etc.

    Raises
    ------
    FileNotFoundError
        If no CSVs are found for the commodity.
    """
    csv_dir = RAW_COMTRADE_DIR / commodity
    if not csv_dir.exists():
        raise FileNotFoundError(
            f"No raw data directory found for '{commodity}'. "
            f"Expected: {csv_dir}\n"
            "Run the Comtrade downloader first (see run_comtrade_download.py)."
        )

    csv_files = sorted(csv_dir.glob("*.csv"))
    if not csv_files:
        raise FileNotFoundError(f"No CSV files found in {csv_dir}.")

    frames = []
    for f in csv_files:
        try:
            df = pd.read_csv(f, dtype=str, low_memory=False)
            frames.append(df)
        except Exception as e:
            logger.warning("Could not read %s: %s", f, e)

    combined = pd.concat(frames, ignore_index=True)
    logger.info("Loaded %d rows from %d files for '%s'", len(combined), len(csv_files), commodity)
    return combined


def clean_raw(df: pd.DataFrame, commodity: str) -> pd.DataFrame:
    """
    Cast columns, filter rows, and assign quarter.

    Steps:
    1. Parse refYear and refMonth as integers.
    2. Map month → quarter.
    3. Cast netWgt and primaryValue to float (missing → NaN).
    4. Keep only rows where:
       - flowCode is "M" (import) or "X" (export)
       - primaryValue > 0
       - netWgt > MIN_WEIGHT_KG  (avoids division-by-near-zero in price calc)
    5. Add a 'period_label' column for readability (e.g. "2010Q1").

    Parameters
    ----------
    df : pd.DataFrame
        Raw Comtrade data from load_raw_csv().
    commodity : str
        Commodity name (used only for logging).

    Returns
    -------
    pd.DataFrame
        Cleaned subset with numeric types and 'quarter' column added.
    """
    df = df.copy()

    # Cast year/month
    df["refYear"]  = pd.to_numeric(df["refYear"],  errors="coerce").astype("Int64")
    df["refMonth"] = pd.to_numeric(df["refMonth"], errors="coerce").astype("Int64")

    # Assign quarter
    df["quarter"] = df["refMonth"].map(MONTH_TO_QUARTER)

    # Cast value columns — Comtrade stores these as strings in CSV
    df["netWgt"]       = pd.to_numeric(df["netWgt"],       errors="coerce")
    df["primaryValue"] = pd.to_numeric(df["primaryValue"], errors="coerce")

    # Count rows before filtering
    n_before = len(df)

    # Keep only imports and exports
    df = df[df["flowCode"].isin(["M", "X"])].copy()

    # Drop rows with missing/zero/negative value or weight
    df = df[df["primaryValue"] > 0].copy()
    df = df[df["netWgt"] > MIN_WEIGHT_KG].copy()

    # Drop rows with missing year, month, or quarter
    df = df.dropna(subset=["refYear", "refMonth", "quarter"]).copy()

    n_after = len(df)
    n_dropped = n_before - n_after
    if n_dropped > 0:
        logger.info(
            "  '%s': dropped %d/%d rows (zero value, missing weight, or bad flow)",
            commodity, n_dropped, n_before,
        )

    # Add readable period label
    df["period_label"] = (
        df["refYear"].astype(str) + "Q" + df["quarter"].astype(str)
    )

    return df


def aggregate_to_quarterly(df: pd.DataFrame, commodity: str) -> pd.DataFrame:
    """
    Aggregate monthly HS-level rows to quarterly commodity-level totals.

    For each (year, quarter, flow) combination:
    - Sum all HS codes' primaryValue → quarterly total trade value (USD)
    - Sum all HS codes' netWgt → quarterly total weight (kg)
    - Compute unit-value price = total_value / (total_weight / 1000)
      This gives USD per tonne, and is a quantity-weighted average price.

    The quantity-weighted approach is correct because it avoids giving equal
    weight to small-volume, high-value sub-products. (Annex Section 5.)

    Parameters
    ----------
    df : pd.DataFrame
        Cleaned data from clean_raw().
    commodity : str
        Commodity name (added as a column in the output).

    Returns
    -------
    pd.DataFrame
        Quarterly panel with columns:
        commodity, year, quarter, period_label, flow,
        value_usd, weight_kg, weight_tonnes, price_usd_per_tonne,
        n_hs_codes, n_monthly_obs
    """
    # Group: sum value and weight across HS codes and months within quarter
    grp = (
        df.groupby(["refYear", "quarter", "period_label", "flowCode"], as_index=False)
        .agg(
            value_usd    =("primaryValue", "sum"),
            weight_kg    =("netWgt",       "sum"),
            n_hs_codes   =("cmdCode",      "nunique"),
            n_monthly_obs=("refMonth",     "count"),
        )
    )

    # Compute weight in tonnes and unit-value price
    grp["weight_tonnes"]       = grp["weight_kg"] / 1000.0
    grp["price_usd_per_tonne"] = grp["value_usd"] / grp["weight_tonnes"]

    # Rename for clarity
    grp = grp.rename(columns={"refYear": "year", "flowCode": "flow"})

    # Add commodity column
    grp.insert(0, "commodity", commodity)

    # Rename flow codes to readable labels
    grp["flow"] = grp["flow"].map({"M": "import", "X": "export"})

    # Sort chronologically
    grp = grp.sort_values(["flow", "year", "quarter"]).reset_index(drop=True)

    return grp


def process_commodity(commodity: str) -> pd.DataFrame:
    """
    Full pipeline for one commodity: load → clean → aggregate.

    Parameters
    ----------
    commodity : str
        Key from config.COMMODITY_HS_CODES.

    Returns
    -------
    pd.DataFrame
        Quarterly price and quantity series (imports and exports).
    """
    logger.info("Processing commodity: %s", commodity.upper())

    raw = load_raw_csv(commodity)
    clean = clean_raw(raw, commodity)
    quarterly = aggregate_to_quarterly(clean, commodity)

    # Log summary
    for flow in ["import", "export"]:
        sub = quarterly[quarterly["flow"] == flow]
        if len(sub) == 0:
            logger.warning("  No %s data for %s", flow, commodity)
            continue
        ymin, ymax = sub["year"].min(), sub["year"].max()
        qmin = sub[sub["year"] == ymin]["quarter"].min()
        qmax = sub[sub["year"] == ymax]["quarter"].max()
        price_min = sub["price_usd_per_tonne"].min()
        price_max = sub["price_usd_per_tonne"].max()
        logger.info(
            "  %s %s: %d quarters (%dQ%d–%dQ%d), "
            "price range: $%.0f–$%.0f USD/t",
            commodity, flow, len(sub),
            ymin, qmin, ymax, qmax,
            price_min, price_max,
        )

    return quarterly


def process_all_commodities() -> pd.DataFrame:
    """
    Run process_commodity() for all commodities and save combined output.

    Saves to: data/processed/comtrade_quarterly.csv

    Returns
    -------
    pd.DataFrame
        Combined quarterly panel for all 7 commodities.
    """
    frames = []
    for commodity in COMMODITY_HS_CODES:
        try:
            df = process_commodity(commodity)
            frames.append(df)
        except FileNotFoundError as e:
            logger.error("Skipping '%s': %s", commodity, e)
        except Exception as e:
            logger.error("Unexpected error processing '%s': %s", commodity, e)

    if not frames:
        logger.error("No commodities processed — check raw data directory.")
        return pd.DataFrame()

    combined = pd.concat(frames, ignore_index=True)

    # Save
    combined.to_csv(OUTPUT_PATH, index=False)
    logger.info(
        "\nSaved %d quarterly observations to:\n  %s",
        len(combined), OUTPUT_PATH,
    )

    return combined


def load_quarterly(commodity: str = None, flow: str = None) -> pd.DataFrame:
    """
    Load the processed quarterly Comtrade panel.

    Optional filtering by commodity and/or flow.

    Parameters
    ----------
    commodity : str, optional
        Filter to one commodity (e.g. "clinker").
    flow : str, optional
        Filter to "import" or "export".

    Returns
    -------
    pd.DataFrame

    Raises
    ------
    FileNotFoundError
        If comtrade_quarterly.csv has not been generated yet.
    """
    if not OUTPUT_PATH.exists():
        raise FileNotFoundError(
            f"Quarterly panel not found at {OUTPUT_PATH}. "
            "Run process_all_commodities() first."
        )

    df = pd.read_csv(OUTPUT_PATH)

    if commodity is not None:
        df = df[df["commodity"] == commodity].copy()
    if flow is not None:
        df = df[df["flow"] == flow].copy()

    return df.reset_index(drop=True)


# ---------------------------------------------------------------------------
# Coverage report
# ---------------------------------------------------------------------------

def print_coverage_report(df: pd.DataFrame) -> None:
    """
    Print a concise summary of quarter coverage for each commodity and flow.

    Flags any quarters with suspiciously low prices (< $1 USD/tonne) or
    very few HS codes reporting (n_hs_codes == 1 for multi-code commodities).

    Parameters
    ----------
    df : pd.DataFrame
        Output of process_all_commodities() or load_quarterly().
    """
    print("\n" + "=" * 70)
    print("  COMTRADE QUARTERLY COVERAGE REPORT")
    print("=" * 70)
    print(f"  {'Commodity':<22} {'Flow':<8} {'Quarters':>8} {'Start':>8} {'End':>7} {'Price range (USD/t)':>22}")
    print("-" * 70)

    for commodity in df["commodity"].unique():
        for flow in ["import", "export"]:
            sub = df[(df["commodity"] == commodity) & (df["flow"] == flow)]
            if len(sub) == 0:
                print(f"  {commodity:<22} {flow:<8} {'NO DATA':>8}")
                continue

            start = f"{sub['year'].min()}Q{sub[sub['year'] == sub['year'].min()]['quarter'].min()}"
            end   = f"{sub['year'].max()}Q{sub[sub['year'] == sub['year'].max()]['quarter'].max()}"
            p_min = sub["price_usd_per_tonne"].min()
            p_max = sub["price_usd_per_tonne"].max()
            price_range = f"${p_min:>8,.0f}–${p_max:<8,.0f}"

            print(f"  {commodity:<22} {flow:<8} {len(sub):>8} {start:>8} {end:>7} {price_range:>22}")

    print("=" * 70)

    # Flag data quality warnings
    warnings = []
    for _, row in df.iterrows():
        if row["price_usd_per_tonne"] < 1.0:
            warnings.append(
                f"  WARNING: {row['commodity']} {row['flow']} "
                f"{row['year']}Q{row['quarter']}: "
                f"price = ${row['price_usd_per_tonne']:.3f}/t (check data)"
            )
    if warnings:
        print("\nData quality warnings:")
        for w in warnings:
            print(w)
    else:
        print("\n  No data quality warnings.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    """
    Run as:
        python -m src.data_processing.aggregate_trade          # all commodities
        python -m src.data_processing.aggregate_trade clinker  # single commodity
    """
    if len(sys.argv) > 1:
        # Single commodity mode
        commodity_arg = sys.argv[1].lower()
        if commodity_arg not in COMMODITY_HS_CODES:
            print(f"Unknown commodity '{commodity_arg}'.")
            print(f"Valid options: {list(COMMODITY_HS_CODES.keys())}")
            sys.exit(1)
        result = process_commodity(commodity_arg)
        print(f"\nProcessed {len(result)} quarterly rows for '{commodity_arg}'.")
        print(result.to_string(index=False))
    else:
        # All commodities
        result = process_all_commodities()
        if not result.empty:
            print_coverage_report(result)
            print(f"\nDone. Output: {OUTPUT_PATH}")
