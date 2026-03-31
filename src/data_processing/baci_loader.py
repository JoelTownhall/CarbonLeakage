"""
baci_loader.py — Extract and aggregate BACI trade data for Australian commodities.

Session 4, Step 4B.

BACI (Base pour l'Analyse du Commerce International) from CEPII provides
reconciled bilateral trade flows at HS 6-digit level, covering 1995–2024.
Source: https://www.cepii.fr/CEPII/en/bdd_modele/bdd_modele_item.asp?id=37
File:   BACI_HS02_V202601.zip  (HS2002 nomenclature, 2002–2024)

We use BACI to fill the pre-2010 gap in our Comtrade series.

BACI format:
    t   — year
    i   — exporter country code (UN M49, Australia = 36)
    j   — importer country code (UN M49, Australia = 36)
    k   — HS 6-digit product code (integer, no leading zeros)
    v   — trade value (USD thousands)
    q   — net weight (tonnes)

Temporal limitation:
    BACI is ANNUAL. For the ARDL model we need quarterly data.
    We distribute annual totals evenly across 4 quarters (value/4, quantity/4).
    This preserves year-to-year price variation (which drives long-run elasticity)
    but removes within-year dynamics. HAC standard errors (maxlags=4) partially
    correct for the induced quarterly autocorrelation.

HS version note:
    Our commodity HS codes are from HS2007/HS2012 nomenclature (used by Comtrade
    from 2010 onwards). BACI HS02 uses HS2002. For our commodities (cement 252x,
    lime 252x, steel 72xx), the codes are largely identical between HS versions —
    any minor differences are flagged in coverage checks.

Usage:
    python -m src.data_processing.baci_loader          # extract all
    python -m src.data_processing.baci_loader clinker  # one commodity
"""

import sys
import logging
import zipfile
from pathlib import Path

import pandas as pd
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import COMMODITY_HS_CODES, DATA_RAW, DATA_PROCESSED

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

BACI_DIR     = DATA_RAW / "baci"
BACI_ZIP     = BACI_DIR / "BACI_HS02_V202601.zip"
BACI_OUT_DIR = DATA_RAW / "baci" / "extracted"

AUSTRALIA_CODE = 36          # UN M49 country code for Australia
BACI_START_YEAR = 2003       # Match Review's sample start
BACI_END_YEAR   = 2009       # Fill gap before Comtrade (which starts 2010)

MONTH_TO_QUARTER = {1:1, 2:1, 3:1, 4:2, 5:2, 6:2, 7:3, 8:3, 9:3, 10:4, 11:4, 12:4}


# ---------------------------------------------------------------------------
# HS code helpers
# ---------------------------------------------------------------------------

def get_hs_int_codes(commodity: str) -> set[int]:
    """
    Return the HS codes for a commodity as a set of integers.

    BACI stores k (HS code) as an integer (no leading zeros, 6 digits).
    E.g. "252310" → 252310.
    """
    codes = COMMODITY_HS_CODES.get(commodity, [])
    return {int(c) for c in codes}


def all_hs_codes() -> set[int]:
    """All HS codes across all commodities as integers."""
    result = set()
    for codes in COMMODITY_HS_CODES.values():
        result.update(int(c) for c in codes)
    return result


# ---------------------------------------------------------------------------
# Step 1: Extract Australia flows from BACI zip
# ---------------------------------------------------------------------------

def extract_australia_from_zip(years: range = None) -> pd.DataFrame:
    """
    Stream through the BACI zip, reading one year CSV at a time, and
    extract rows where Australia is the importer (j=36) or exporter (i=36)
    for our commodity HS codes.

    Parameters
    ----------
    years : range, optional
        Years to extract. Default: BACI_START_YEAR to BACI_END_YEAR.

    Returns
    -------
    pd.DataFrame with columns: year, flow, hs_code, value_usd, weight_tonnes
        flow: "import" (j=36) or "export" (i=36)
        value_usd: trade value in USD (converted from USD thousands × 1000)
        weight_tonnes: net weight in metric tonnes (directly from BACI q column)
    """
    if not BACI_ZIP.exists():
        raise FileNotFoundError(
            f"BACI zip not found: {BACI_ZIP}\n"
            "Download from: https://www.cepii.fr/DATA_DOWNLOAD/baci/data/BACI_HS02_V202601.zip"
        )

    if years is None:
        years = range(BACI_START_YEAR, BACI_END_YEAR + 1)

    target_codes = all_hs_codes()
    all_frames = []

    with zipfile.ZipFile(BACI_ZIP, "r") as zf:
        # List all CSV files in the zip
        csv_files = [f for f in zf.namelist() if f.endswith(".csv") and "BACI_HS" in f]
        logger.info("BACI zip contains %d CSV files", len(csv_files))

        for year in years:
            # Find the file for this year
            year_files = [f for f in csv_files if f"_Y{year}_" in f]
            if not year_files:
                logger.warning("No BACI file found for year %d", year)
                continue

            fname = year_files[0]
            logger.info("Reading %s ...", fname)

            with zf.open(fname) as f:
                # Read in chunks to manage memory
                chunks = pd.read_csv(
                    f,
                    dtype={"t": int, "i": int, "j": int, "k": int,
                           "v": float, "q": float},
                    chunksize=500_000,
                )

                year_rows = []
                for chunk in chunks:
                    # Filter to our HS codes first (most selective filter)
                    chunk = chunk[chunk["k"].isin(target_codes)]
                    if chunk.empty:
                        continue

                    # Australia as importer (j=36)
                    imp = chunk[chunk["j"] == AUSTRALIA_CODE].copy()
                    if not imp.empty:
                        imp["flow"] = "import"
                        year_rows.append(imp)

                    # Australia as exporter (i=36)
                    exp = chunk[chunk["i"] == AUSTRALIA_CODE].copy()
                    if not exp.empty:
                        exp["flow"] = "export"
                        year_rows.append(exp)

                if year_rows:
                    year_df = pd.concat(year_rows, ignore_index=True)
                    # Convert: value USD thousands → USD
                    year_df["value_usd"]      = year_df["v"] * 1000.0
                    year_df["weight_tonnes"]  = year_df["q"]
                    year_df["year"]           = year_df["t"]
                    year_df["hs_code"]        = year_df["k"]
                    year_df = year_df[["year", "flow", "hs_code", "value_usd", "weight_tonnes"]]
                    all_frames.append(year_df)
                    logger.info("  %d — %d rows (imports+exports)", year, len(year_df))
                else:
                    logger.warning("  %d — no Australia rows found", year)

    if not all_frames:
        logger.error("No data extracted from BACI zip.")
        return pd.DataFrame()

    combined = pd.concat(all_frames, ignore_index=True)
    logger.info("Total BACI rows extracted: %d", len(combined))
    return combined


# ---------------------------------------------------------------------------
# Step 2: Aggregate to commodity-level annual, then expand to quarterly
# ---------------------------------------------------------------------------

def aggregate_to_quarterly(baci_raw: pd.DataFrame) -> pd.DataFrame:
    """
    Aggregate BACI annual rows to commodity-level, then distribute evenly
    across 4 quarters.

    For each (year, flow, commodity):
    - Sum value_usd and weight_tonnes across all HS codes and partners
    - Compute annual unit-value price (USD/tonne)
    - Split evenly into 4 equal quarterly observations

    Returns DataFrame with same columns as comtrade_quarterly.csv:
        commodity, year, quarter, period_label, flow,
        value_usd, weight_kg, weight_tonnes, price_usd_per_tonne,
        n_hs_codes, n_monthly_obs
    """
    # Map each HS code to its commodity
    code_to_commodity = {}
    for commodity, codes in COMMODITY_HS_CODES.items():
        for code in codes:
            code_to_commodity[int(code)] = commodity

    baci_raw = baci_raw.copy()
    baci_raw["commodity"] = baci_raw["hs_code"].map(code_to_commodity)
    baci_raw = baci_raw.dropna(subset=["commodity"])

    # Filter out zero/negative weight rows
    baci_raw = baci_raw[(baci_raw["value_usd"] > 0) & (baci_raw["weight_tonnes"] > 0)]

    # Aggregate to (year, flow, commodity)
    grp = (
        baci_raw
        .groupby(["year", "flow", "commodity"], as_index=False)
        .agg(
            value_usd      =("value_usd",      "sum"),
            weight_tonnes  =("weight_tonnes",  "sum"),
            n_hs_codes     =("hs_code",        "nunique"),
        )
    )

    grp["price_usd_per_tonne"] = grp["value_usd"] / grp["weight_tonnes"]
    grp["weight_kg"]           = grp["weight_tonnes"] * 1000.0

    # Expand each annual row to 4 quarterly rows (uniform distribution)
    # Value and weight split equally; price stays the same (price = value/weight)
    rows = []
    for _, row in grp.iterrows():
        for q in range(1, 5):
            rows.append({
                "commodity":          row["commodity"],
                "year":               int(row["year"]),
                "quarter":            q,
                "period_label":       f"{int(row['year'])}Q{q}",
                "flow":               row["flow"],
                "value_usd":          row["value_usd"]     / 4.0,
                "weight_kg":          row["weight_kg"]      / 4.0,
                "weight_tonnes":      row["weight_tonnes"]  / 4.0,
                "price_usd_per_tonne": row["price_usd_per_tonne"],   # same each quarter
                "n_hs_codes":         int(row["n_hs_codes"]),
                "n_monthly_obs":      3,    # 3 months per quarter (approximate)
                "source":             "baci",
            })

    result = pd.DataFrame(rows)
    result = result.sort_values(["commodity", "flow", "year", "quarter"]).reset_index(drop=True)
    return result


# ---------------------------------------------------------------------------
# Step 3: Splice with Comtrade and save
# ---------------------------------------------------------------------------

def build_combined_panel(baci_quarterly: pd.DataFrame) -> pd.DataFrame:
    """
    Combine BACI (pre-2010) with Comtrade (2010+) into a single quarterly panel.

    BACI rows get source='baci', Comtrade rows get source='comtrade'.
    Saves to: data/processed/comtrade_quarterly_extended.csv
    """
    comtrade_path = DATA_PROCESSED / "comtrade_quarterly.csv"
    if not comtrade_path.exists():
        raise FileNotFoundError(
            f"Comtrade quarterly panel not found: {comtrade_path}\n"
            "Run aggregate_trade.process_all_commodities() first."
        )

    comtrade = pd.read_csv(comtrade_path)
    comtrade["source"] = "comtrade"

    # Remove any Comtrade rows that overlap with BACI years (use BACI for pre-2010)
    baci_years = set(baci_quarterly["year"].unique())
    comtrade_trimmed = comtrade[~comtrade["year"].isin(baci_years)].copy()

    logger.info(
        "BACI: %d rows (%d–%d) | Comtrade: %d rows (after removing %d overlap years)",
        len(baci_quarterly),
        baci_quarterly["year"].min(), baci_quarterly["year"].max(),
        len(comtrade_trimmed),
        len(comtrade) - len(comtrade_trimmed),
    )

    combined = pd.concat([baci_quarterly, comtrade_trimmed], ignore_index=True)
    combined = combined.sort_values(["commodity", "flow", "year", "quarter"]).reset_index(drop=True)

    out_path = DATA_PROCESSED / "comtrade_quarterly_extended.csv"
    combined.to_csv(out_path, index=False)
    logger.info("Saved combined panel (%d rows) → %s", len(combined), out_path)

    return combined


# ---------------------------------------------------------------------------
# Coverage report
# ---------------------------------------------------------------------------

def print_coverage(df: pd.DataFrame) -> None:
    print("\n" + "=" * 72)
    print("  BACI + COMTRADE EXTENDED COVERAGE")
    print("=" * 72)
    print(f"  {'Commodity':<22} {'Flow':<8} {'Qtrs':>5} {'Start':>8} {'End':>8} {'Source split'}")
    print("-" * 72)
    for commodity in sorted(df["commodity"].unique()):
        for flow in ["import", "export"]:
            sub = df[(df["commodity"]==commodity) & (df["flow"]==flow)]
            if sub.empty:
                continue
            n_baci    = (sub["source"]=="baci").sum() if "source" in sub else 0
            n_comtrade= (sub["source"]=="comtrade").sum() if "source" in sub else len(sub)
            start = sub["period_label"].min()
            end   = sub["period_label"].max()
            print(f"  {commodity:<22} {flow:<8} {len(sub):>5} {start:>8} {end:>8} "
                  f"  BACI:{n_baci}q + Comtrade:{n_comtrade}q")
    print("=" * 72)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    commodity_filter = sys.argv[1].lower() if len(sys.argv) > 1 else None

    logger.info("Extracting BACI data for Australia (%d–%d)...", BACI_START_YEAR, BACI_END_YEAR)
    baci_raw = extract_australia_from_zip(years=range(BACI_START_YEAR, BACI_END_YEAR + 1))

    if baci_raw.empty:
        logger.error("No data extracted. Exiting.")
        sys.exit(1)

    logger.info("Aggregating to quarterly commodity panels...")
    baci_quarterly = aggregate_to_quarterly(baci_raw)

    if commodity_filter:
        baci_quarterly = baci_quarterly[baci_quarterly["commodity"] == commodity_filter]

    logger.info("Splicing with Comtrade panel...")
    combined = build_combined_panel(baci_quarterly)

    print_coverage(combined)
    logger.info("Done. Run build_dataset.py next to rebuild model panels.")
