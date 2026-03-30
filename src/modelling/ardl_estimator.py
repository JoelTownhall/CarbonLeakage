"""
ardl_estimator.py — ARDL estimation for carbon leakage trade elasticities.

Session 3, Step 3A.

This module implements the ARDL model specification from the Carbon Leakage
Review Annex (DCCEEW, February 2025), Section 4 "Trade model estimation".

Specification (Annex equation):
    ln(Q_t) = μ₀ + Σᵢ μ₁ᵢ ln(P_{t−i}) + Σᵢ μ₂ᵢ ln(Q_{t−i})
                 + Σᵢ μ₃ᵢ ln(D_{t−i}) + ε_t

Long-run price elasticity (Annex formula):
    β_LR = Σμ₁ᵢ / (1 − Σμ₂ᵢ)

Standard errors: Delta method with Newey-West HAC covariance matrix.

Bounds test: Pesaran et al. (2001) Case III (unrestricted intercept, no trend).

Lag selection: AIC, maximum 4 lags (following Review convention).

Trend specification: Both constant-only ('c') and constant+trend ('ct') are
estimated; the specification with lower AIC is preferred (Review did this
per commodity).

Usage:
    python -m src.modelling.ardl_estimator                  # all models
    python -m src.modelling.ardl_estimator clinker import   # one model
"""

import sys
import logging
from pathlib import Path

import numpy as np
import pandas as pd
from statsmodels.tsa.ardl import ARDL, UECM, ardl_select_order

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import COMMODITY_HS_CODES, DATA_PROCESSED, REVIEW_IMPORT_RESULTS, REVIEW_EXPORT_RESULTS

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# Model parameters (matching Review Annex Section 4)
MAX_LAG       = 4    # Maximum lag for AIC selection
HAC_MAXLAGS   = 4    # Newey-West HAC bandwidth (following Annex)
DROP_FLAGGED  = True # Drop price_flag==1 quarters before fitting

# Output path for results table
RESULTS_PATH = DATA_PROCESSED.parent.parent / "outputs" / "tables" / "ardl_results.csv"
RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_panel(commodity: str, flow: str, drop_flagged: bool = DROP_FLAGGED) -> pd.DataFrame:
    """
    Load the model-ready panel for one (commodity, flow) pair.

    Parameters
    ----------
    commodity : str
        E.g. "clinker", "cement".
    flow : str
        "import" or "export".
    drop_flagged : bool
        If True (default), drop quarters where price_flag == 1.
        These are sparse quarters with anomalous unit-value prices.

    Returns
    -------
    pd.DataFrame
        Sorted quarterly panel with columns:
        period_str, ln_quantity, ln_price, ln_demand.
    """
    path = DATA_PROCESSED / f"{commodity}_{flow}.csv"
    if not path.exists():
        raise FileNotFoundError(
            f"Panel not found: {path}. Run build_dataset.py first."
        )

    df = pd.read_csv(path)
    df = df.sort_values(["year", "quarter"]).reset_index(drop=True)

    if drop_flagged and "price_flag" in df.columns:
        n_before = len(df)
        df = df[df["price_flag"] == 0].reset_index(drop=True)
        n_dropped = n_before - len(df)
        if n_dropped > 0:
            logger.info(
                "  Dropped %d flagged quarters for %s %s", n_dropped, commodity, flow
            )

    # Check we have enough observations for ARDL(4,4,4)
    min_needed = 4 * 3 + 1 + 10  # 3 variables × 4 lags + const + buffer
    if len(df) < min_needed:
        raise ValueError(
            f"Insufficient observations for {commodity} {flow}: "
            f"{len(df)} rows (need ≥ {min_needed})"
        )

    return df


# ---------------------------------------------------------------------------
# Long-run elasticity via delta method
# ---------------------------------------------------------------------------

def compute_lr_elasticity(res, price_var: str = "ln_price") -> tuple:
    """
    Compute long-run price elasticity and its standard error via delta method.

    From the Annex formula:
        β_LR = Σμ₁ᵢ / (1 − Σμ₂ᵢ)

    where μ₁ᵢ are the price lag coefficients and μ₂ᵢ are the quantity
    (endogenous) lag coefficients.

    The delta method applies a first-order Taylor expansion to propagate
    uncertainty from the individual coefficient estimates to the derived
    long-run elasticity.

    Parameters
    ----------
    res : ARDLResults
        Fitted ARDL model result (with HAC covariance).
    price_var : str
        Name of the price variable in the model (default "ln_price").

    Returns
    -------
    tuple of (lr_elasticity, lr_se, lr_tstat, lr_pvalue)
    """
    params = res.params
    cov    = res.cov_params()

    # Identify price lag parameter names: ln_price.L0, ln_price.L1, ...
    # and quantity lag names: ln_quantity.L1, ln_quantity.L2, ...
    price_params = [p for p in params.index if p.startswith(price_var + ".L")]
    qty_params   = [p for p in params.index if p.startswith("ln_quantity.L")]

    if not price_params:
        raise ValueError(
            f"No price parameters found. Expected names starting with '{price_var}.L'. "
            f"Available params: {list(params.index)}"
        )

    sum_price = params[price_params].sum()
    sum_qty   = params[qty_params].sum() if qty_params else 0.0

    denom = 1.0 - sum_qty
    if abs(denom) < 1e-10:
        logger.warning("Denominator near zero in LR elasticity calc — model may be explosive")
        return np.nan, np.nan, np.nan, np.nan

    lr = sum_price / denom

    # Delta method gradient:
    # ∂β_LR/∂μ₁ᵢ = 1 / denom  (for each price lag)
    # ∂β_LR/∂μ₂ᵢ = sum_price / denom²  (for each quantity lag)
    all_params = list(cov.index)
    grad = np.zeros(len(all_params))

    for p in price_params:
        idx = all_params.index(p)
        grad[idx] = 1.0 / denom

    for p in qty_params:
        idx = all_params.index(p)
        grad[idx] = sum_price / (denom ** 2)

    # SE = sqrt(g' V g)
    cov_arr = cov.values
    var_lr  = grad @ cov_arr @ grad
    se_lr   = np.sqrt(max(var_lr, 0.0))

    tstat = lr / se_lr if se_lr > 0 else np.nan

    # Two-tailed p-value using normal approximation (large sample)
    from scipy import stats
    pvalue = 2 * stats.norm.sf(abs(tstat)) if not np.isnan(tstat) else np.nan

    return lr, se_lr, tstat, pvalue


# ---------------------------------------------------------------------------
# Bounds test
# ---------------------------------------------------------------------------

def run_bounds_test(df: pd.DataFrame, lags: dict, trend: str) -> dict:
    """
    Run the Pesaran et al. (2001) bounds test for cointegration.

    Uses the UECM (Unrestricted ECM) form, which statsmodels requires for
    the bounds test. The UECM is equivalent to the ARDL — only the
    parameterisation differs.

    Parameters
    ----------
    df : pd.DataFrame
        Panel with columns ln_quantity, ln_price, ln_demand.
    lags : dict
        Lag orders from ARDL selection: {'endog': r, 'ln_price': p, 'ln_demand': q}
    trend : str
        Trend specification: 'c' or 'ct'.

    Returns
    -------
    dict with keys: stat, p_values (dict of I(0)/I(1) bounds)
    """
    endog = df["ln_quantity"]
    exog  = df[["ln_price", "ln_demand"]]

    try:
        # UECM requires each exog variable to have at least 1 lag.
        # If AIC selected 0 lags for a variable, bump it to 1 for the bounds test.
        uecm_order = {
            "ln_price":  max(lags["ln_price"], 1),
            "ln_demand": max(lags["ln_demand"], 1),
        }
        uecm = UECM(
            endog,
            lags=max(lags["endog"], 1),
            exog=exog,
            order=uecm_order,
            trend=trend,
        )
        uecm_res = uecm.fit()
        # Case 3: unrestricted intercept, no trend (Pesaran et al. 2001)
        bt = uecm_res.bounds_test(case=3)
        return {
            "stat":     float(bt.stat),
            "p_I0":     float(bt.p_values["lower"]),
            "p_I1":     float(bt.p_values["upper"]),
            "crit_5pct_I0": float(bt.crit_vals.loc[95.0, "lower"]),
            "crit_5pct_I1": float(bt.crit_vals.loc[95.0, "upper"]),
        }
    except Exception as e:
        logger.warning("  Bounds test failed: %s", e)
        return {"stat": np.nan, "p_I0": np.nan, "p_I1": np.nan,
                "crit_1pct_I0": np.nan, "crit_1pct_I1": np.nan,
                "crit_5pct_I0": np.nan, "crit_5pct_I1": np.nan}


# ---------------------------------------------------------------------------
# Core: estimate one ARDL model
# ---------------------------------------------------------------------------

def estimate_ardl(
    commodity: str,
    flow: str,
    trend: str = None,
) -> dict:
    """
    Estimate the ARDL model for one (commodity, flow) pair.

    If trend is None, both 'c' (constant only) and 'ct' (constant + trend)
    are estimated and the specification with lower AIC is returned.

    Steps:
    1. Load and prepare data (drop flagged quarters).
    2. Run ardl_select_order (AIC, max 4 lags) for both trend specs.
    3. Fit selected ARDL with HAC standard errors.
    4. Compute long-run price elasticity via delta method.
    5. Run bounds test on the corresponding UECM.
    6. Return results dict.

    Parameters
    ----------
    commodity : str
        E.g. "clinker", "cement".
    flow : str
        "import" or "export".
    trend : str or None
        'c', 'ct', or None (auto-select by AIC).

    Returns
    -------
    dict
        Results including lr_elasticity, lr_se, aic, bounds_stat, etc.
    """
    logger.info("Estimating ARDL: %s %s ...", commodity, flow)

    # Load data
    df = load_panel(commodity, flow)
    n_obs = len(df)

    endog = df["ln_quantity"]
    exog  = df[["ln_price", "ln_demand"]]

    # Trend specifications to try
    trends_to_try = [trend] if trend is not None else ["c", "ct"]

    best_result = None
    best_aic    = np.inf

    for tr in trends_to_try:
        try:
            # Step 1: AIC lag selection
            sel = ardl_select_order(
                endog,
                maxlag=MAX_LAG,
                exog=exog,
                maxorder=MAX_LAG,
                trend=tr,
                ic="aic",
                glob=False,
            )

            # ardl_order is a flat tuple: (endog_lags, exog1_lags, exog2_lags, ...)
            # However, the tuple can be shorter than expected if AIC drops an exog
            # variable entirely. Use dl_lags and ar_lags from the model directly,
            # which are always populated correctly.
            endog_lags = len(sel.model.ar_lags) if sel.model.ar_lags else 0
            # dl_lags gives the actual lags included: {'ln_price': [0,1], ...}
            # "order" = highest lag index = len(lags) - 1 (since lags are 0-based)
            exog_orders = {}
            for name in exog.columns:
                if name in sel.model.dl_lags and sel.model.dl_lags[name]:
                    exog_orders[name] = max(sel.model.dl_lags[name])
                else:
                    exog_orders[name] = 0  # contemporaneous only

            logger.info(
                "  %s %s trend=%s: ARDL(%d, p=%d, q=%d) [AIC selection]",
                commodity, flow, tr,
                endog_lags,
                exog_orders.get("ln_price", 0),
                exog_orders.get("ln_demand", 0),
            )

            # Step 2: Fit ARDL with HAC standard errors
            # Re-use the already-selected model from sel.model (same order)
            res = sel.model.fit(
                cov_type="HAC",
                cov_kwds={"maxlags": HAC_MAXLAGS},
            )

            aic = res.aic

            if aic < best_aic:
                best_aic = aic
                lags_dict = {
                    "endog":     endog_lags,
                    "ln_price":  exog_orders.get("ln_price", 0),
                    "ln_demand": exog_orders.get("ln_demand", 0),
                }
                best_result = {
                    "res":   res,
                    "lags":  lags_dict,
                    "trend": tr,
                }

        except Exception as e:
            logger.warning(
                "  ARDL fit failed for %s %s trend=%s: %s", commodity, flow, tr, e
            )

    if best_result is None:
        logger.error("  All ARDL specifications failed for %s %s", commodity, flow)
        return _failed_result(commodity, flow)

    res   = best_result["res"]
    lags  = best_result["lags"]
    trend = best_result["trend"]

    # Step 3: Long-run elasticity via delta method
    lr, lr_se, lr_t, lr_p = compute_lr_elasticity(res)

    # Step 4: Bounds test
    bt = run_bounds_test(df, lags, trend)

    # Step 5: Model diagnostics
    # ARDLResults has no rsquared_adj attribute — compute manually
    y_actual = res.model.endog[res.model.hold_back:]
    y_fitted = res.fittedvalues.values
    n_fit    = len(y_actual)
    k_params = len(res.params)
    ss_res   = np.sum((y_actual - y_fitted) ** 2)
    ss_tot   = np.sum((y_actual - y_actual.mean()) ** 2)
    r2       = 1.0 - ss_res / ss_tot if ss_tot > 0 else np.nan
    adj_r2   = 1.0 - (1 - r2) * (n_fit - 1) / (n_fit - k_params - 1) if ss_tot > 0 else np.nan

    # Significance stars for LR elasticity
    if not np.isnan(lr_p):
        if lr_p < 0.001:   sig = "***"
        elif lr_p < 0.01:  sig = "**"
        elif lr_p < 0.05:  sig = "*"
        elif lr_p < 0.10:  sig = "^"
        else:              sig = ""
    else:
        sig = "n/a"

    # Bounds test significance (compare stat to I(1) upper bound at 5%)
    bounds_p = bt.get("p_I1", np.nan)
    if not np.isnan(bounds_p):
        if bounds_p < 0.01:   bt_sig = "***"
        elif bounds_p < 0.05: bt_sig = "**"
        elif bounds_p < 0.10: bt_sig = "*"
        else:                 bt_sig = ""
    else:
        bt_sig = "n/a"

    logger.info(
        "  RESULT: %s %s — LR elasticity = %.3f%s (SE=%.3f, p=%.3f) "
        "| bounds p_I(1)=%.3f%s | AIC=%.1f | trend=%s | n=%d",
        commodity, flow,
        lr if not np.isnan(lr) else 999,
        sig,
        lr_se if not np.isnan(lr_se) else 999,
        lr_p if not np.isnan(lr_p) else 999,
        bounds_p if not np.isnan(bounds_p) else 999,
        bt_sig, best_aic, trend, n_obs,
    )

    return {
        "commodity":     commodity,
        "flow":          flow,
        "n_obs":         n_obs,
        "trend":         trend,
        "lag_endog":     lags["endog"],
        "lag_price":     lags["ln_price"],
        "lag_demand":    lags["ln_demand"],
        "lr_elasticity": round(lr, 4) if not np.isnan(lr) else np.nan,
        "lr_se":         round(lr_se, 4) if not np.isnan(lr_se) else np.nan,
        "lr_tstat":      round(lr_t, 3) if not np.isnan(lr_t) else np.nan,
        "lr_pvalue":     round(lr_p, 4) if not np.isnan(lr_p) else np.nan,
        "sig":           sig,
        "aic":           round(best_aic, 2),
        "adj_r2":        round(adj_r2, 3),
        "bounds_stat":   round(bt["stat"], 3) if not np.isnan(bt["stat"]) else np.nan,
        "bounds_p_I1":   round(bounds_p, 4) if not np.isnan(bounds_p) else np.nan,
        "bounds_sig":    bt_sig,
        "status":        "OK",
    }


def _failed_result(commodity: str, flow: str) -> dict:
    """Return a result dict indicating estimation failure."""
    return {
        "commodity": commodity, "flow": flow, "n_obs": 0, "trend": "n/a",
        "lag_endog": np.nan, "lag_price": np.nan, "lag_demand": np.nan,
        "lr_elasticity": np.nan, "lr_se": np.nan, "lr_tstat": np.nan,
        "lr_pvalue": np.nan, "sig": "FAIL", "aic": np.nan, "adj_r2": np.nan,
        "bounds_stat": np.nan, "bounds_p_I1": np.nan, "bounds_sig": "FAIL",
        "status": "FAILED",
    }


# ---------------------------------------------------------------------------
# Run all models
# ---------------------------------------------------------------------------

def estimate_all(
    target_commodity: str = None,
    target_flow: str = None,
) -> pd.DataFrame:
    """
    Estimate ARDL models for all (or specified) commodity-flow pairs.

    Saves results to: outputs/tables/ardl_results.csv

    Parameters
    ----------
    target_commodity : str, optional
        If set, only run this commodity.
    target_flow : str, optional
        If set, only run "import" or "export".

    Returns
    -------
    pd.DataFrame
        Results table with one row per model.
    """
    commodities = [target_commodity] if target_commodity else list(COMMODITY_HS_CODES.keys())
    flows       = [target_flow] if target_flow else ["import", "export"]

    results = []
    for commodity in commodities:
        for flow in flows:
            result = estimate_ardl(commodity, flow)
            results.append(result)

    df = pd.DataFrame(results)
    df.to_csv(RESULTS_PATH, index=False)
    logger.info("Saved results table → %s", RESULTS_PATH)
    return df


# ---------------------------------------------------------------------------
# Comparison to Review benchmarks
# ---------------------------------------------------------------------------

def print_comparison_table(results: pd.DataFrame) -> None:
    """
    Print side-by-side comparison of our estimates vs Review benchmarks.

    Parameters
    ----------
    results : pd.DataFrame
        Output of estimate_all().
    """
    print("\n" + "=" * 90)
    print("  ARDL RESULTS — OUR ESTIMATES vs REVIEW BENCHMARKS")
    print("=" * 90)

    for flow, review_dict in [("import", REVIEW_IMPORT_RESULTS), ("export", REVIEW_EXPORT_RESULTS)]:
        print(f"\n  {'— ' + flow.upper() + ' MODELS —':^88}")
        print(f"  {'Commodity':<22} {'Ours':>8} {'Sig':>4} {'SE':>7} {'Rev':>8} {'RevSig':>7} "
              f"{'Diff':>8} {'Bounds':>8} {'AdjR2':>7} {'N':>4}")
        print("  " + "-" * 86)

        for commodity in COMMODITY_HS_CODES:
            row = results[(results["commodity"] == commodity) & (results["flow"] == flow)]
            if row.empty:
                continue
            row = row.iloc[0]

            our_e  = row["lr_elasticity"]
            our_se = row["lr_se"]
            our_sig = row["sig"]

            ref = review_dict.get(commodity)
            rev_e   = ref["elasticity"] if ref else np.nan
            rev_sig = _pvalue_to_sig(ref) if ref else "n/a"

            diff = (our_e - rev_e) if (not np.isnan(our_e) and not np.isnan(rev_e)) else np.nan

            bounds_p = row["bounds_p_I1"]
            bounds_str = f"{bounds_p:.3f}{row['bounds_sig']}" if not np.isnan(bounds_p) else "n/a"

            print(
                f"  {commodity:<22} {_fmt(our_e):>8} {our_sig:>4} {_fmt(our_se):>7} "
                f"{_fmt(rev_e):>8} {rev_sig:>7} "
                f"{_fmt(diff):>8} {bounds_str:>8} "
                f"{row['adj_r2']:>7.3f} {int(row['n_obs']):>4}"
            )

    print("\n" + "=" * 90)
    print("  Sig: *** p<0.001, ** p<0.01, * p<0.05, ^ p<0.10")
    print("  Bounds: p-value for I(1) upper bound (Case III)")
    print("  Rev: Review benchmark from Annex Tables 1 & 2")
    print("  Note: Import prices converted USD→AUD via RBA F11 (matching Review). Export prices in USD.")
    print("=" * 90)


def _fmt(x) -> str:
    """Format a float for the comparison table."""
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "n/a"
    return f"{x:+.3f}" if x != 0 else " 0.000"


def _pvalue_to_sig(ref: dict) -> str:
    """Convert Review benchmark p-value to significance string."""
    p = ref.get("bounds_p", 1.0)
    e = ref.get("elasticity", 0)
    # Use standard interpretation from Review table footnotes
    if abs(e) == 0:
        return "n/a"
    # The Review reports elasticity SE — back-calculate approximate p
    se = ref.get("se", 1e9)
    if se == 0:
        return "n/a"
    t = abs(e / se)
    if t > 3.29:   return "***"
    elif t > 2.58: return "**"
    elif t > 1.96: return "*"
    elif t > 1.65: return "^"
    return ""


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    """
    Run as:
        python -m src.modelling.ardl_estimator
        python -m src.modelling.ardl_estimator clinker
        python -m src.modelling.ardl_estimator clinker import
    """
    commodity_arg = sys.argv[1].lower() if len(sys.argv) > 1 else None
    flow_arg      = sys.argv[2].lower() if len(sys.argv) > 2 else None

    if commodity_arg and commodity_arg not in COMMODITY_HS_CODES:
        print(f"Unknown commodity '{commodity_arg}'. Options: {list(COMMODITY_HS_CODES.keys())}")
        sys.exit(1)

    results = estimate_all(commodity_arg, flow_arg)
    print_comparison_table(results)
    print(f"\nFull results saved to: {RESULTS_PATH}")
