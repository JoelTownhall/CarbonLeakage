"""
build_dataset.py — Merge all data sources into model-ready ARDL panels.

Session 2, Step 2B (updated Session 3 to add AUD conversion).

This module takes the quarterly Comtrade price/quantity series (from
aggregate_trade.py) and merges in:
  - ABS demand controls (Construction GVA, Final Demand, GDP)
  - IMF trade-weighted GDP index (for export models)
  - RBA F11 AUD/USD exchange rates (for import price conversion)

Output:
    data/processed/model_dataset.csv
    data/processed/{commodity}_{flow}.csv  (one file per model)

Each row is one quarter. Each file contains the log-level variables
needed for ARDL estimation:
    ln_quantity  — log of import/export volume (tonnes)
    ln_price     — log of unit-value price
    ln_demand    — log of demand control (ABS for imports, IMF GDP for exports)

Currency treatment (matching the Review):
    IMPORTS:  Comtrade primaryValue is in USD. The Review used ABS customs
              values which are already in AUD. We convert:
                  price_AUD = price_USD × (AUD per USD)
              using quarterly-average RBA F11 exchange rates.
              Source: data/raw/imf/exchange_rate_aud_usd.csv

    EXPORTS:  The Review converted ABS FOB (AUD) back to USD using BIS FX.
              Our Comtrade primaryValue is already in USD — no conversion needed.

Usage:
    python -m src.data_processing.build_dataset              # all commodities
    python -m src.data_processing.build_dataset clinker      # one commodity
    python -m src.data_processing.build_dataset clinker import  # specific model
"""

import sys
import logging
from pathlib import Path

import pandas as pd
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import (
    COMMODITY_HS_CODES,
    DATA_RAW,
    DATA_PROCESSED,
)
from src.data_collection.abs_fetcher import (
    fetch_abs_sdmx,
    DEMAND_CONTROL_FOR_COMMODITY,
    ABS_SERIES,
)
from src.data_collection.imf_fetcher import build_trade_weighted_gdp

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# Paths
COMTRADE_QUARTERLY = DATA_PROCESSED / "comtrade_quarterly.csv"
MODEL_DATASET_PATH = DATA_PROCESSED / "model_dataset.csv"
DATA_PROCESSED.mkdir(parents=True, exist_ok=True)

# ARDL model start/end.
# Review used Q3 2003 (primary) or Q3 2003–Q4 2019 for COVID/Ukraine-affected
# commodities (cement, clinker, lime, flat steel). We have data from Q1 2010
# (Comtrade free-tier limitation). We start from 2011Q1 to avoid the sparse
# 2010Q1/Q3/Q4 quarters that produce anomalous unit-value prices.
MODEL_START = "2011Q1"
MODEL_END   = "2024Q4"


# ---------------------------------------------------------------------------
# Helper: load ABS demand controls
# ---------------------------------------------------------------------------

def load_abs_series(series_name: str) -> pd.DataFrame:
    """
    Load one ABS quarterly series from cache or API.

    Returns a DataFrame with columns: [period_str, value, ln_value]
    where period_str is "YYYYQN" (e.g. "2010Q1").

    Parameters
    ----------
    series_name : str
        One of "construction_gva", "final_demand", "gdp".

    Returns
    -------
    pd.DataFrame or None
    """
    df = fetch_abs_sdmx(series_name)
    if df is None or df.empty:
        logger.warning("ABS series '%s' not available.", series_name)
        return None

    # Convert Period to string label (e.g. "2010Q1") for merging
    df = df.copy()
    df["period_str"] = df["period"].astype(str)
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df["ln_value"] = np.log(df["value"])

    return df[["period_str", "value", "ln_value"]].rename(
        columns={"value": series_name, "ln_value": f"ln_{series_name}"}
    )


# ---------------------------------------------------------------------------
# Helper: load RBA exchange rates
# ---------------------------------------------------------------------------

def load_exchange_rates() -> pd.DataFrame:
    """
    Load quarterly-average AUD/USD exchange rates from the RBA F11 file.

    Returns DataFrame with columns: [period_str, aud_per_usd]
    where aud_per_usd = how many AUD to buy 1 USD
    (e.g. 0.99 in 2011 when AUD was near parity; 1.55 in 2025 after AUD weakened)
    """
    fx_path = DATA_RAW / "imf" / "exchange_rate_aud_usd.csv"
    if not fx_path.exists():
        return None
    df = pd.read_csv(fx_path)
    return df[["period_str", "aud_per_usd"]]


# ---------------------------------------------------------------------------
# Helper: load trade-weighted GDP
# ---------------------------------------------------------------------------

def load_trade_weighted_gdp() -> pd.DataFrame:
    """
    Load IMF trade-weighted GDP index from cache or API.

    Returns DataFrame with columns: [period_str, ln_trade_weighted_gdp]
    """
    df = build_trade_weighted_gdp()
    if df is None or df.empty:
        logger.warning("Trade-weighted GDP not available.")
        return None

    df = df.copy()
    df["period_str"] = df["period"].astype(str)
    return df[["period_str", "ln_trade_weighted_gdp"]]


# ---------------------------------------------------------------------------
# Core: build one commodity-flow dataset
# ---------------------------------------------------------------------------

def build_model_panel(
    comtrade: pd.DataFrame,
    commodity: str,
    flow: str,
    abs_controls: dict,
    tw_gdp: pd.DataFrame,
    fx_rates: pd.DataFrame = None,
) -> pd.DataFrame:
    """
    Build the model-ready panel for one (commodity, flow) pair.

    Merges trade data with the appropriate demand control and creates
    log-transformed model variables.

    Parameters
    ----------
    comtrade : pd.DataFrame
        Output of aggregate_trade.load_quarterly(), filtered to commodity+flow.
    commodity : str
        Commodity name (e.g. "clinker").
    flow : str
        "import" or "export".
    abs_controls : dict
        Dict of {series_name: DataFrame} for ABS demand controls.
    tw_gdp : pd.DataFrame
        Trade-weighted GDP from IMF.

    Returns
    -------
    pd.DataFrame
        Model-ready quarterly panel with columns:
        period_str, year, quarter, ln_quantity, ln_price, ln_demand,
        plus raw values for audit purposes.
    """
    if comtrade.empty:
        logger.warning("No trade data for %s %s — skipping.", commodity, flow)
        return pd.DataFrame()

    df = comtrade.copy()

    # -- Step 1: Create period string for merging (e.g. "2010Q1") --
    df["period_str"] = df["year"].astype(str) + "Q" + df["quarter"].astype(str)

    # -- Step 2: Compute log variables for trade --
    df["ln_quantity"] = np.log(df["weight_tonnes"].clip(lower=1e-6))

    # Currency conversion for import prices (matching the Review):
    #   Review imports: ABS customs value already in AUD
    #   Our imports:    Comtrade primaryValue in USD → convert to AUD
    #   Review exports: ABS FOB in AUD → converted to USD via BIS FX
    #   Our exports:    Comtrade primaryValue already in USD → no conversion needed
    if flow == "import" and fx_rates is not None and not fx_rates.empty:
        df = df.merge(fx_rates, on="period_str", how="left")
        n_missing_fx = df["aud_per_usd"].isna().sum()
        if n_missing_fx > 0:
            logger.warning(
                "  %s %s: %d quarters missing exchange rate — filling with interpolation",
                commodity, flow, n_missing_fx,
            )
            df["aud_per_usd"] = df["aud_per_usd"].interpolate()
        df["price_aud_per_tonne"] = df["price_usd_per_tonne"] * df["aud_per_usd"]
        df["ln_price"] = np.log(df["price_aud_per_tonne"].clip(lower=1e-6))
        df["price_currency"] = "AUD"
        logger.info("  %s import: converted USD → AUD prices using RBA F11 rates", commodity)
    else:
        df["price_aud_per_tonne"] = np.nan
        df["ln_price"] = np.log(df["price_usd_per_tonne"].clip(lower=1e-6))
        df["price_currency"] = "USD"
        if flow == "import":
            logger.warning(
                "  %s import: exchange rates unavailable — using USD prices (suboptimal)",
                commodity,
            )

    # -- Step 3: Merge demand control --
    if flow == "import":
        # Import models use ABS domestic demand controls
        demand_series = DEMAND_CONTROL_FOR_COMMODITY.get(commodity)
        if demand_series is None:
            logger.warning("No demand control mapping for %s — using GDP fallback.", commodity)
            demand_series = "gdp"

        demand_df = abs_controls.get(demand_series)
        demand_col = f"ln_{demand_series}"
        demand_label = "ln_demand"

        if demand_df is not None and not demand_df.empty:
            df = df.merge(
                demand_df[["period_str", demand_col]],
                on="period_str",
                how="left",
            )
            df = df.rename(columns={demand_col: demand_label})
            df["demand_source"] = demand_series
        else:
            logger.warning("ABS '%s' not available for %s imports.", demand_series, commodity)
            df["ln_demand"] = np.nan
            df["demand_source"] = demand_series + " (MISSING)"

    else:  # export
        # Export models use trade-weighted foreign GDP
        if tw_gdp is not None and not tw_gdp.empty:
            df = df.merge(
                tw_gdp[["period_str", "ln_trade_weighted_gdp"]],
                on="period_str",
                how="left",
            )
            df = df.rename(columns={"ln_trade_weighted_gdp": "ln_demand"})
            df["demand_source"] = "trade_weighted_gdp"
        else:
            logger.warning("Trade-weighted GDP not available for %s exports.", commodity)
            df["ln_demand"] = np.nan
            df["demand_source"] = "trade_weighted_gdp (MISSING)"

    # -- Step 4: Filter to model date range --
    df = df[
        (df["period_str"] >= MODEL_START) &
        (df["period_str"] <= MODEL_END)
    ].copy()

    # -- Step 5: Flag suspicious price observations --
    # A quarterly unit value is flagged if:
    #   (a) it is more than 3× the commodity-flow median ln_price, OR
    #   (b) the quarterly volume (weight_tonnes) is below 1% of the commodity
    #       median — indicating a sparse quarter dominated by tiny shipments.
    #
    # These quarters should be reviewed visually before ARDL estimation.
    # Flagged quarters are NOT removed here; the modelling step can decide
    # whether to exclude them.
    median_ln_price = df["ln_price"].median()
    std_ln_price    = df["ln_price"].std()
    median_weight   = df["weight_tonnes"].median()

    flag_price  = (df["ln_price"] - median_ln_price).abs() > 3 * std_ln_price
    flag_volume = df["weight_tonnes"] < 0.01 * median_weight

    df["price_flag"] = (flag_price | flag_volume).astype(int)

    n_flagged = df["price_flag"].sum()
    if n_flagged > 0:
        flagged_periods = df.loc[df["price_flag"] == 1, "period_str"].tolist()
        logger.warning(
            "  %s %s: %d quarters flagged as suspicious (price outlier or sparse volume): %s",
            commodity, flow, n_flagged, flagged_periods,
        )

    # -- Step 6: Sort and select columns --
    df = df.sort_values(["year", "quarter"]).reset_index(drop=True)

    # Core model columns + audit columns
    cols_core = [
        "commodity", "flow", "period_str", "year", "quarter",
        "ln_quantity", "ln_price", "ln_demand",
        "demand_source", "price_currency", "price_flag",
    ]
    cols_audit = [
        "weight_tonnes", "price_usd_per_tonne", "price_aud_per_tonne", "value_usd",
        "n_hs_codes", "n_monthly_obs",
    ]
    # Only include audit columns that exist
    cols_audit = [c for c in cols_audit if c in df.columns]

    df = df[cols_core + cols_audit]

    # -- Step 7: Log missing data --
    n_total = len(df)
    n_missing_demand = df["ln_demand"].isna().sum()
    n_missing_price  = df["ln_price"].isna().sum()

    if n_missing_demand > 0:
        logger.warning(
            "  %s %s: %d/%d quarters missing demand control",
            commodity, flow, n_missing_demand, n_total,
        )
    if n_missing_price > 0:
        logger.warning(
            "  %s %s: %d/%d quarters missing price",
            commodity, flow, n_missing_price, n_total,
        )

    logger.info(
        "  Built panel: %s %s — %d quarters (%s–%s), "
        "%d missing demand, %d missing price",
        commodity, flow, n_total,
        df["period_str"].min(), df["period_str"].max(),
        n_missing_demand, n_missing_price,
    )

    return df


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def build_all_datasets(
    target_commodity: str = None,
    target_flow: str = None,
) -> pd.DataFrame:
    """
    Build model-ready panels for all (or specified) commodity-flow pairs.

    Saves:
    - data/processed/model_dataset.csv         — combined panel (all)
    - data/processed/{commodity}_{flow}.csv    — individual files per model

    Parameters
    ----------
    target_commodity : str, optional
        If set, only process this commodity.
    target_flow : str, optional
        If set, only process this flow ("import" or "export").

    Returns
    -------
    pd.DataFrame
        Combined model dataset.
    """
    # Load trade data
    if not COMTRADE_QUARTERLY.exists():
        raise FileNotFoundError(
            f"Quarterly trade data not found at {COMTRADE_QUARTERLY}. "
            "Run aggregate_trade.process_all_commodities() first."
        )

    comtrade_all = pd.read_csv(COMTRADE_QUARTERLY)
    logger.info("Loaded %d rows from comtrade_quarterly.csv", len(comtrade_all))

    # Load ABS demand controls (load once, reuse for all commodities)
    logger.info("Loading ABS demand control variables ...")
    abs_controls = {}
    for series_name in ["construction_gva", "final_demand", "gdp"]:
        df = load_abs_series(series_name)
        if df is not None:
            abs_controls[series_name] = df
            logger.info("  Loaded ABS '%s': %d quarters", series_name, len(df))
        else:
            logger.warning("  ABS '%s' unavailable — will be missing in import models.", series_name)

    # Load trade-weighted GDP
    logger.info("Loading IMF trade-weighted GDP ...")
    try:
        tw_gdp = load_trade_weighted_gdp()
        logger.info("  Loaded trade-weighted GDP: %d quarters", len(tw_gdp))
    except Exception as e:
        logger.warning("  Could not load trade-weighted GDP: %s", e)
        tw_gdp = None

    # Load RBA exchange rates (for import price AUD conversion)
    logger.info("Loading RBA F11 AUD/USD exchange rates ...")
    fx_rates = load_exchange_rates()
    if fx_rates is not None:
        logger.info("  Loaded exchange rates: %d quarters", len(fx_rates))
    else:
        logger.warning("  Exchange rates not found — import prices will remain in USD")

    # Determine which commodities and flows to process
    commodities = [target_commodity] if target_commodity else list(COMMODITY_HS_CODES.keys())
    flows = [target_flow] if target_flow else ["import", "export"]

    all_panels = []

    for commodity in commodities:
        logger.info("=" * 60)
        logger.info("Building datasets for: %s", commodity.upper())

        for flow in flows:
            # Filter trade data
            ct_sub = comtrade_all[
                (comtrade_all["commodity"] == commodity) &
                (comtrade_all["flow"] == flow)
            ].copy()

            # Build panel
            panel = build_model_panel(ct_sub, commodity, flow, abs_controls, tw_gdp, fx_rates)

            if panel.empty:
                logger.warning("  Empty panel for %s %s — skipping.", commodity, flow)
                continue

            all_panels.append(panel)

            # Save individual file
            out_path = DATA_PROCESSED / f"{commodity}_{flow}.csv"
            panel.to_csv(out_path, index=False)
            logger.info("  Saved → %s", out_path)

    if not all_panels:
        logger.error("No panels built — check inputs.")
        return pd.DataFrame()

    # Save combined dataset
    combined = pd.concat(all_panels, ignore_index=True)
    combined.to_csv(MODEL_DATASET_PATH, index=False)
    logger.info(
        "\nSaved combined model dataset (%d rows) → %s",
        len(combined), MODEL_DATASET_PATH,
    )

    return combined


def load_model_panel(commodity: str, flow: str) -> pd.DataFrame:
    """
    Load the model-ready panel for one (commodity, flow) pair.

    Parameters
    ----------
    commodity : str
        E.g. "clinker", "cement".
    flow : str
        "import" or "export".

    Returns
    -------
    pd.DataFrame

    Raises
    ------
    FileNotFoundError
        If the individual panel CSV hasn't been generated yet.
    """
    path = DATA_PROCESSED / f"{commodity}_{flow}.csv"
    if not path.exists():
        raise FileNotFoundError(
            f"Model panel not found at {path}. "
            "Run build_all_datasets() first."
        )
    return pd.read_csv(path)


def print_dataset_summary(df: pd.DataFrame) -> None:
    """
    Print a readable summary of the combined model dataset.

    Shows coverage, missing values, and basic price/quantity stats for
    each commodity-flow combination.

    Parameters
    ----------
    df : pd.DataFrame
        Output of build_all_datasets() or pd.read_csv(MODEL_DATASET_PATH).
    """
    print("\n" + "=" * 80)
    print("  MODEL DATASET SUMMARY")
    print("=" * 80)
    print(f"  {'Commodity':<22} {'Flow':<8} {'N':>5} {'Period':<18} "
          f"{'ln_price range':>20} {'Missing':>8}")
    print("-" * 80)

    for commodity in df["commodity"].unique():
        for flow in ["import", "export"]:
            sub = df[(df["commodity"] == commodity) & (df["flow"] == flow)]
            if sub.empty:
                continue

            period_range = f"{sub['period_str'].min()}–{sub['period_str'].max()}"
            p_range = f"{sub['ln_price'].min():.2f}–{sub['ln_price'].max():.2f}"
            n_missing = sub[["ln_price", "ln_demand"]].isna().any(axis=1).sum()

            print(
                f"  {commodity:<22} {flow:<8} {len(sub):>5} {period_range:<18} "
                f"{p_range:>20} {n_missing:>8}"
            )

    print("=" * 80)
    n_missing_total = df[["ln_price", "ln_demand"]].isna().any(axis=1).sum()
    print(f"\n  Total rows: {len(df)}  |  Rows with any missing: {n_missing_total}")
    if n_missing_total > 0:
        print("  NOTE: Missing values will need to be addressed before ARDL estimation.")
        print("        Import models: check ABS API connectivity.")
        print("        Export models: check IMF trade-weighted GDP.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    """
    Run as:
        python -m src.data_processing.build_dataset
        python -m src.data_processing.build_dataset clinker
        python -m src.data_processing.build_dataset clinker import
    """
    commodity_arg = sys.argv[1].lower() if len(sys.argv) > 1 else None
    flow_arg      = sys.argv[2].lower() if len(sys.argv) > 2 else None

    if commodity_arg and commodity_arg not in COMMODITY_HS_CODES:
        print(f"Unknown commodity '{commodity_arg}'.")
        print(f"Valid options: {list(COMMODITY_HS_CODES.keys())}")
        sys.exit(1)

    if flow_arg and flow_arg not in ("import", "export"):
        print(f"Unknown flow '{flow_arg}'. Use 'import' or 'export'.")
        sys.exit(1)

    result = build_all_datasets(commodity_arg, flow_arg)

    if not result.empty:
        print_dataset_summary(result)
        print(f"\nDone. Output: {MODEL_DATASET_PATH}")
