"""
leakage_calculator.py — Carbon leakage rate calculation.

Session 4, Step 4A.

Applies long-run ARDL price elasticities to a 2030 carbon cost scenario
to estimate the % change in import and export volumes, and the resulting
carbon leakage rate for each commodity.

Methodology (Review Annex Section 3):
──────────────────────────────────────
For each commodity:

  1. Carbon cost per tonne of Australian production:
        ΔC = CARBON_PRICE × EFF_P × EID × SG_COV
     where:
        CARBON_PRICE = A$50/tCO2-e (2030 scenario)
        EFF_P        = 1 - ERC = 0.343  (effective price exposure, no TEBA)
        EID          = emissions intensity (tCO2-e per tonne of product)
        SG_COV       = Safeguard Mechanism coverage fraction

  2. % change in trade volumes (via long-run price elasticity):
        %ΔQ_import = β_import × (ΔC / P_import)   [β < 0 ⟹ fewer imports if P↑,
                                                     but ΔC makes domestic dearer,
                                                     so imports ↑ → use |β|]
        %ΔQ_export = β_export × (ΔC / P_export)   [β < 0 ⟹ exports ↓ when cost↑]

  3. Carbon leakage rate (as % of domestic production volume):
        CLR_import = |β_import| × (ΔC / P_import) × (Q_import / Q_prod)
        CLR_export = |β_export| × (ΔC / P_export) × (Q_export / Q_prod)
        CLR_total  = CLR_import + CLR_export

     where Q_import/Q_prod = IMPORT_PROD_RATIO  (from Review Table 2/3)

Prices used:
  - Import prices: average AUD/tonne from model_dataset.csv (2020Q1–2024Q4)
    (already converted from Comtrade USD via RBA F11 rates)
  - Export prices: average USD/tonne × 1.465 AUD/USD = AUD/tonne

For models with wrong sign or insufficient significance, we flag the result
and optionally substitute the Review's published elasticity for comparison.

Usage:
    python -m src.leakage.leakage_calculator          # all commodities
    python -m src.leakage.leakage_calculator cement   # one commodity
"""

import sys
import logging
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import (
    COMMODITY_HS_CODES,
    DATA_PROCESSED,
    CARBON_PRICE_2030,
    EFF_P_NO_TEBA,
    EMISSIONS_INTENSITY,
    IMPORT_PROD_RATIO,
    EXPORT_PROD_RATIO,
    SG_COVERAGE,
    REVIEW_IMPORT_RESULTS,
    REVIEW_EXPORT_RESULTS,
)

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

ARDL_RESULTS_PATH = PROJECT_ROOT / "outputs" / "tables" / "ardl_results.csv"
MODEL_DATASET_PATH = DATA_PROCESSED / "model_dataset.csv"
LEAKAGE_OUTPUT_PATH = PROJECT_ROOT / "outputs" / "tables" / "leakage_results.csv"

# Average AUD/USD rate 2020Q1–2024Q4 for export price conversion
AUD_PER_USD_RECENT = 1.465


# ---------------------------------------------------------------------------
# Helper: compute average recent price per commodity+flow
# ---------------------------------------------------------------------------

def load_recent_prices(start_period: str = "2020Q1") -> pd.DataFrame:
    """
    Compute average unit-value prices over the recent period from model panels.

    Import prices are already in AUD (from RBA F11 conversion).
    Export prices are in USD and are converted to AUD using AUD_PER_USD_RECENT.

    Returns DataFrame with columns:
        commodity, flow, price_aud_per_tonne, n_quarters
    """
    df = pd.read_csv(MODEL_DATASET_PATH)
    recent = df[df["period_str"] >= start_period].copy()

    rows = []
    for (commodity, flow), grp in recent.groupby(["commodity", "flow"]):
        ln_p_mean = grp["ln_price"].mean()
        price_native = np.exp(ln_p_mean)           # AUD for imports, USD for exports
        currency = grp["price_currency"].iloc[0]

        if flow == "export" and currency == "USD":
            price_aud = price_native * AUD_PER_USD_RECENT
        else:
            price_aud = price_native                # already AUD

        rows.append({
            "commodity":         commodity,
            "flow":              flow,
            "price_native":      round(price_native, 2),
            "currency_native":   currency,
            "price_aud":         round(price_aud, 2),
            "n_quarters":        len(grp),
        })

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Core: compute leakage for one commodity
# ---------------------------------------------------------------------------

def compute_leakage_row(
    commodity: str,
    elasticity_import: float,
    elasticity_export: float,
    price_import_aud: float,
    price_export_aud: float,
    use_review_if_wrong_sign: bool = False,
) -> dict:
    """
    Compute carbon leakage metrics for one commodity.

    Parameters
    ----------
    commodity : str
    elasticity_import : float
        Long-run import price elasticity (should be negative).
    elasticity_export : float
        Long-run export price elasticity (should be negative).
    price_import_aud : float
        Average import unit-value price (AUD per tonne).
    price_export_aud : float
        Average export unit-value price (AUD per tonne).
    use_review_if_wrong_sign : bool
        If True, substitute Review elasticity when our estimate has wrong sign.

    Returns
    -------
    dict with all intermediate and final leakage metrics.
    """
    eid       = EMISSIONS_INTENSITY.get(commodity, 0.0)
    sg_cov    = SG_COVERAGE.get(commodity, 1.0)
    imp_ratio = IMPORT_PROD_RATIO.get(commodity, 0.0)
    exp_ratio = EXPORT_PROD_RATIO.get(commodity, 0.0)

    # 1. Carbon cost per tonne of product
    delta_c = CARBON_PRICE_2030 * EFF_P_NO_TEBA * eid * sg_cov
    # delta_c = A$/tonne  (e.g. cement: 50 × 0.343 × 0.708 × 1.0 = $12.1/tonne)

    # 2. Elasticities — resolve wrong-sign issues
    rev_imp = REVIEW_IMPORT_RESULTS.get(commodity, {})
    rev_exp = REVIEW_EXPORT_RESULTS.get(commodity, {})

    imp_source = "ours"
    exp_source = "ours"

    if use_review_if_wrong_sign:
        if not np.isnan(elasticity_import) and elasticity_import > 0 and rev_imp:
            elasticity_import = rev_imp["elasticity"]
            imp_source = "review (substituted: wrong sign)"
        if not np.isnan(elasticity_export) and elasticity_export > 0 and rev_exp:
            elasticity_export = rev_exp["elasticity"]
            exp_source = "review (substituted: wrong sign)"

    # Use absolute value for leakage magnitude (sign convention: leakage > 0)
    beta_imp = abs(elasticity_import) if not np.isnan(elasticity_import) else np.nan
    beta_exp = abs(elasticity_export) if not np.isnan(elasticity_export) else np.nan

    # 3. % change in trade volumes
    pct_change_imp = beta_imp * (delta_c / price_import_aud) if price_import_aud > 0 else np.nan
    pct_change_exp = beta_exp * (delta_c / price_export_aud) if price_export_aud > 0 else np.nan

    # 4. Carbon leakage rate (as % of domestic production volume)
    clr_import = pct_change_imp * imp_ratio if not np.isnan(pct_change_imp) else np.nan
    clr_export = pct_change_exp * exp_ratio if not np.isnan(pct_change_exp) else np.nan

    clr_total  = (
        (clr_import if not np.isnan(clr_import) else 0.0) +
        (clr_export if not np.isnan(clr_export) else 0.0)
    )

    return {
        "commodity":        commodity,
        "eid":              eid,
        "sg_coverage":      sg_cov,
        "delta_c_aud":      round(delta_c, 2),
        "price_import_aud": round(price_import_aud, 2),
        "price_export_aud": round(price_export_aud, 2),
        "beta_import":      round(elasticity_import, 4) if not np.isnan(elasticity_import) else np.nan,
        "beta_export":      round(elasticity_export, 4) if not np.isnan(elasticity_export) else np.nan,
        "imp_source":       imp_source,
        "exp_source":       exp_source,
        "pct_change_import": round(pct_change_imp * 100, 2) if not np.isnan(pct_change_imp) else np.nan,
        "pct_change_export": round(pct_change_exp * 100, 2) if not np.isnan(pct_change_exp) else np.nan,
        "imp_prod_ratio":   imp_ratio,
        "exp_prod_ratio":   exp_ratio,
        "clr_import_pct":   round(clr_import * 100, 3) if not np.isnan(clr_import) else np.nan,
        "clr_export_pct":   round(clr_export * 100, 3) if not np.isnan(clr_export) else np.nan,
        "clr_total_pct":    round(clr_total * 100, 3),
    }


# ---------------------------------------------------------------------------
# Main: run leakage calculation for all commodities
# ---------------------------------------------------------------------------

def run_leakage_calculation(use_review_if_wrong_sign: bool = False) -> pd.DataFrame:
    """
    Run the full leakage calculation for all commodities.

    Parameters
    ----------
    use_review_if_wrong_sign : bool
        If True, substitute the Review's elasticity for models with wrong sign.
        Default: False (report our estimates as-is, flag wrong signs).

    Returns
    -------
    pd.DataFrame
        One row per commodity with all leakage metrics.
    """
    ardl = pd.read_csv(ARDL_RESULTS_PATH)
    prices = load_recent_prices(start_period="2020Q1")

    rows = []
    for commodity in COMMODITY_HS_CODES:
        # Get our elasticities
        imp_row = ardl[(ardl["commodity"] == commodity) & (ardl["flow"] == "import")]
        exp_row = ardl[(ardl["commodity"] == commodity) & (ardl["flow"] == "export")]

        beta_imp = float(imp_row["lr_elasticity"].values[0]) if len(imp_row) > 0 else np.nan
        beta_exp = float(exp_row["lr_elasticity"].values[0]) if len(exp_row) > 0 else np.nan

        # Get prices
        p_imp_row = prices[(prices["commodity"] == commodity) & (prices["flow"] == "import")]
        p_exp_row = prices[(prices["commodity"] == commodity) & (prices["flow"] == "export")]

        p_imp_aud = float(p_imp_row["price_aud"].values[0]) if len(p_imp_row) > 0 else np.nan
        p_exp_aud = float(p_exp_row["price_aud"].values[0]) if len(p_exp_row) > 0 else np.nan

        row = compute_leakage_row(
            commodity,
            beta_imp, beta_exp,
            p_imp_aud, p_exp_aud,
            use_review_if_wrong_sign=use_review_if_wrong_sign,
        )
        rows.append(row)

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Review comparison: compute leakage using Review elasticities
# ---------------------------------------------------------------------------

def run_review_leakage() -> pd.DataFrame:
    """
    Compute leakage using the Review's published elasticities (for comparison).
    Uses same prices and scenario parameters as run_leakage_calculation().
    """
    prices = load_recent_prices(start_period="2020Q1")

    rows = []
    for commodity in COMMODITY_HS_CODES:
        rev_imp = REVIEW_IMPORT_RESULTS.get(commodity, {})
        rev_exp = REVIEW_EXPORT_RESULTS.get(commodity, {})

        beta_imp = rev_imp.get("elasticity", np.nan)
        beta_exp = rev_exp.get("elasticity", np.nan)

        p_imp_row = prices[(prices["commodity"] == commodity) & (prices["flow"] == "import")]
        p_exp_row = prices[(prices["commodity"] == commodity) & (prices["flow"] == "export")]

        p_imp_aud = float(p_imp_row["price_aud"].values[0]) if len(p_imp_row) > 0 else np.nan
        p_exp_aud = float(p_exp_row["price_aud"].values[0]) if len(p_exp_row) > 0 else np.nan

        row = compute_leakage_row(
            commodity,
            beta_imp if beta_imp else np.nan,
            beta_exp if beta_exp else np.nan,
            p_imp_aud, p_exp_aud,
        )
        row["imp_source"] = "review"
        row["exp_source"] = "review"
        rows.append(row)

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Print comparison table
# ---------------------------------------------------------------------------

def print_comparison_table(ours: pd.DataFrame, review: pd.DataFrame) -> None:
    """
    Print a side-by-side comparison of our leakage estimates vs the Review's
    leakage estimates (recomputed using Review elasticities + our prices).
    """
    w = 100
    print("\n" + "=" * w)
    print("  CARBON LEAKAGE RATE COMPARISON  (2030 scenario: A$50/tCO2-e, no TEBA)")
    print("=" * w)
    print(f"  {'Commodity':<22} {'ΔC':>6}  "
          f"{'— IMPORT —':^26}  {'— EXPORT —':^26}  {'CLR TOTAL':^16}")
    print(f"  {'':22} {'A$/t':>6}  "
          f"{'β_imp':>8} {'%ΔQ':>8} {'CLR%':>8}  "
          f"{'β_exp':>8} {'%ΔQ':>8} {'CLR%':>8}  "
          f"{'Ours':>7} {'Rev':>7}")
    print("-" * w)

    for _, row in ours.iterrows():
        c = row["commodity"]
        rev_row = review[review["commodity"] == c].iloc[0]

        flag = ""
        if not np.isnan(row["beta_import"]) and row["beta_import"] > 0:
            flag += " ⚠import"
        if not np.isnan(row["beta_export"]) and row["beta_export"] > 0:
            flag += " ⚠export"

        beta_imp_str = f"{row['beta_import']:+.3f}" if not np.isnan(row["beta_import"]) else "  n/a "
        beta_exp_str = f"{row['beta_export']:+.3f}" if not np.isnan(row["beta_export"]) else "  n/a "
        pct_imp_str  = f"{row['pct_change_import']:+.1f}%" if not np.isnan(row["pct_change_import"]) else "  n/a"
        pct_exp_str  = f"{row['pct_change_export']:+.1f}%" if not np.isnan(row["pct_change_export"]) else "  n/a"
        clr_imp_str  = f"{row['clr_import_pct']:.2f}%" if not np.isnan(row["clr_import_pct"]) else "  n/a"
        clr_exp_str  = f"{row['clr_export_pct']:.2f}%" if not np.isnan(row["clr_export_pct"]) else "  n/a"
        clr_tot_str  = f"{row['clr_total_pct']:.2f}%"
        rev_tot_str  = f"{rev_row['clr_total_pct']:.2f}%"

        print(
            f"  {c:<22} {row['delta_c_aud']:>6.2f}  "
            f"{beta_imp_str:>8} {pct_imp_str:>8} {clr_imp_str:>8}  "
            f"{beta_exp_str:>8} {pct_exp_str:>8} {clr_exp_str:>8}  "
            f"{clr_tot_str:>7} {rev_tot_str:>7}{flag}"
        )

    print("=" * w)
    print()
    print("  ΔC = carbon cost per tonne of Australian production (A$50/tCO2-e × EFF_P × EID × SG_COV)")
    print("  %ΔQ = % change in trade volume from carbon cost (= |β| × ΔC/P)")
    print("  CLR% = carbon leakage rate as % of domestic production (= %ΔQ × trade/prod ratio)")
    print("  Rev = leakage recomputed with Review elasticities but our prices (not Review's Table 4)")
    print("  ⚠ = wrong-sign elasticity → leakage rate shown but should be treated with caution")
    print()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logger.info("Running carbon leakage calculation...")

    ours   = run_leakage_calculation(use_review_if_wrong_sign=False)
    review = run_review_leakage()

    # Save
    LEAKAGE_OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    ours.to_csv(LEAKAGE_OUTPUT_PATH, index=False)
    logger.info("Saved leakage results → %s", LEAKAGE_OUTPUT_PATH)

    # Print comparison table
    print_comparison_table(ours, review)

    # Also print the "use Review where wrong sign" version
    ours_fixed = run_leakage_calculation(use_review_if_wrong_sign=True)
    n_substituted = (ours_fixed["imp_source"].str.contains("substituted") |
                     ours_fixed["exp_source"].str.contains("substituted")).sum()
    if n_substituted > 0:
        print(f"\n--- Variant: Review elasticity substituted for {n_substituted} wrong-sign models ---")
        print_comparison_table(ours_fixed, review)
