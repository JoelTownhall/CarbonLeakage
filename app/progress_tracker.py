"""
progress_tracker.py — Daily check-in dashboard for the Carbon Leakage
Review replication project.

This Streamlit app gives Joel a quick overview of:
  - What has been built and tested
  - What's currently in progress or blocked
  - Key decisions made by Claude (with rationale)
  - Open questions needing Joel's input

Run: streamlit run app/progress_tracker.py
"""

import streamlit as st
from pathlib import Path
import pandas as pd
from datetime import date

PROJECT_ROOT = Path(__file__).parent.parent

# ──────────────────────────────────────────────────────────────────────────────
# Page config
# ──────────────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Carbon Leakage Replication — Project Dashboard",
    page_icon="🌏",
    layout="wide",
)

st.title("🌏 Carbon Leakage Review Replication — Project Dashboard")
st.caption(f"Last updated: 30 March 2026 | Branch: `phase-1-data-collection`")

# ──────────────────────────────────────────────────────────────────────────────
# Overall Phase Progress
# ──────────────────────────────────────────────────────────────────────────────
st.header("📊 Phase Progress")

phases = {
    "Phase 1: Data Collection": {
        "status": "✅ Complete",
        "pct": 100,
        "note": "All 7 commodities downloaded (2010–2024). ABS + IMF verified."
    },
    "Phase 2: Data Processing": {
        "status": "✅ Complete",
        "pct": 100,
        "note": "Quarterly panels built for all 14 commodity-flow models."
    },
    "Phase 3: ARDL Estimation": {
        "status": "⚪ Not Started",
        "pct": 0,
        "note": "Ready to start — all input data in place"
    },
    "Phase 4: Leakage Calculation": {
        "status": "⚪ Not Started",
        "pct": 0,
        "note": "Depends on Phase 3"
    },
}

cols = st.columns(len(phases))
for col, (phase, info) in zip(cols, phases.items()):
    col.metric(label=phase.split(":")[0], value=info["status"])
    col.progress(info["pct"])
    col.caption(info["note"])

st.divider()

# ──────────────────────────────────────────────────────────────────────────────
# Session Log
# ──────────────────────────────────────────────────────────────────────────────
st.header("📋 Session Log")

tab1, tab2 = st.tabs(["Session 2 (30 Mar 2026)", "Session 1 (22 Mar 2026)"])

with tab1:
    st.markdown("**Session 2 completed: Data Processing pipeline**")
    done2 = [
        ("aggregate_trade.py", "Monthly HS-level Comtrade rows → quarterly commodity totals. Computes unit-value price = Σvalue/Σweight (USD/tonne). 792 quarterly observations across all 7 commodities."),
        ("build_dataset.py", "Merges trade data with ABS demand controls and IMF trade-weighted GDP. Outputs 14 model-ready CSVs (7 commodities × import/export) plus a combined `model_dataset.csv`."),
        ("model_dataset.csv", "792 rows, 0 missing values. Columns: ln_quantity, ln_price, ln_demand, plus audit columns (weight_tonnes, price_usd_per_tonne, n_hs_codes, price_flag)."),
        ("price_flag column", "38 quarters flagged as suspicious (price outlier or sparse volume). Nearly all are 2010Q1, Q3, Q4 — the first year, where only tiny shipments were recorded."),
    ]
    for item, detail in done2:
        st.markdown(f"- **{item}**: {detail}")

with tab2:
    st.markdown("**Session 1 completed: Data Collection pipeline**")
    done1 = [
        ("Project structure", "Full directory tree created: `src/`, `data/`, `outputs/`, `app/`"),
        ("config.py", "All HS codes, model parameters, Review benchmark results, scenario constants"),
        ("comtrade_fetcher.py", "UN Comtrade API wrapper with retry, proxy, and CSV caching"),
        ("abs_fetcher.py", "ABS SDMX API wrapper — verified. 86 quarters of Construction GVA, Final Demand, GDP"),
        ("imf_fetcher.py", "IMF annual GDP + trade-weighted index — verified. 5-country weighted index built"),
        ("Comtrade download", "All 7 commodities × 15 years (2010–2024) downloaded. Total: 24,601 raw monthly rows."),
        ("exchange_rates.py", "Placeholder module; BIS API 404. RBA F11 manual download documented as fallback."),
    ]
    for item, detail in done1:
        st.markdown(f"- **{item}**: {detail}")

st.divider()

# ──────────────────────────────────────────────────────────────────────────────
# Data Quality Alert
# ──────────────────────────────────────────────────────────────────────────────
st.header("⚠️ Data Quality — Action Required Before Modelling")

st.warning("""
**Issue: Sparse quarters in 2010 produce anomalous unit-value prices**

In most commodities, 2010Q1, Q3, Q4 show extremely high unit-value prices
because total quarterly weight was only 100–600 tonnes (vs. normal 100,000–500,000 tonnes).
These represent real but tiny shipments where a few small orders arrived —
not bulk trade — and the "price" is meaningless as a market price signal.

**Example — Clinker imports:**
- 2010Q1: 312 tonnes, $60,806/tonne  ← flagged (price_flag = 1)
- 2010Q2: 498,438 tonnes, $55/tonne  ← normal
- 2011Q1: 449,479 tonnes, $57/tonne  ← normal

**Flagged quarters per model:** 2–5 per commodity-flow (mostly early 2010).

**Options for ARDL estimation (Joel to decide):**
1. **Drop 2010 entirely** — start model from 2011Q1. Loses 4 quarters, gains clean data.
2. **Exclude flagged quarters** — use `price_flag == 0` filter. More surgical.
3. **Keep all and use robust SE** — flagged quarters visible as outliers in plots.

Recommended: Option 1 or 2. The `price_flag` column in `model_dataset.csv` identifies these rows.
""")

st.divider()

# ──────────────────────────────────────────────────────────────────────────────
# Remaining Blockers
# ──────────────────────────────────────────────────────────────────────────────
st.header("🚨 Remaining Blockers")

st.warning("""
**BLOCKER: USD price series (not AUD)**

The Review used AUD prices. Our Comtrade `primaryValue` is in USD.
To convert: AUD_price = USD_price × (AUD/USD rate).

Exchange rate variation matters for the ARDL because it affects relative
prices over time. Without it, we're estimating elasticity w.r.t. USD prices.

**What needs to happen:**
Download RBA Statistical Table F11 (monthly AUD/USD exchange rates):
  https://www.rba.gov.au/statistics/tables/xls-hist/f11hist.xls

Save as: `data/raw/imf/exchange_rate_aud_usd.csv`
Columns: period (YYYY-QN), aud_per_usd (quarterly average)

**Impact:** Moderate. Direction of bias depends on how much AUD/USD
fluctuated during the sample. If you have the RBA F11 file, let Claude know.
""")

st.warning("""
**OUTSTANDING QUESTION: 2003–2009 data gap**

The Review's preferred models start from Q3 2003. Our sample starts Q1 2010
(Comtrade free tier only goes back to 2010).

**Impact:** 28 fewer quarters. Some Review models may be unstable with only
60 quarters. Bounds test critical values are sensitive to sample size.

**Options:**
- Accept 2010–2024 sample (60 quarters — still adequate for ARDL)
- Source 2003–2009 data from ABS 5368.0 (merchandise trade statistics)
  via abs.gov.au manually
- Wait for DCCEEW to share their data?

Recommendation: proceed with 2010–2024 and note the limitation. Report
confidence intervals alongside point estimates to show uncertainty.
""")

st.divider()

# ──────────────────────────────────────────────────────────────────────────────
# Decisions Made
# ──────────────────────────────────────────────────────────────────────────────
st.header("🧠 Decisions Made (with rationale)")

decisions = [
    {
        "decision": "World aggregate trade data (partnerCode=0)",
        "rationale": "Free-tier Comtrade limits. Joel emailed DCCEEW team. Still awaiting response.",
        "confidence": "🟡 Medium",
        "review_note": "Joel: **still awaiting DCCEEW response** — emailed ~22 March 2026",
    },
    {
        "decision": "IMF annual GDP (interpolated to quarterly) for export demand",
        "rationale": "OECD SDMX-JSON API URL format changed; returns unfiltered data. IMF DataMapper works. Annual growth rates distributed uniformly across quarters within each year — introduces smoothing but acceptable for first pass.",
        "confidence": "🟡 Medium",
        "review_note": "If you have OECD quarterly GDP CSVs, place in `data/raw/imf/oecd_gdp_{CHN|JPN|KOR|USA|IND}.csv`",
    },
    {
        "decision": "Unit-value price = Σ(primaryValue) / Σ(netWgt/1000)",
        "rationale": "Quantity-weighted average price across HS codes within a commodity group. This is the correct method for aggregating heterogeneous products — avoids giving equal weight to small high-value shipments. Same approach as Comtrade best practice.",
        "confidence": "🟢 High",
        "review_note": "",
    },
    {
        "decision": "ABS SDMX API for domestic demand variables",
        "rationale": "Tested and verified 3 series: Construction GVA, Final Demand, GDP. All return 86 quarters 2003–2024 at chain volume, seasonally adjusted — matches ABS 5206.0 source used in Review.",
        "confidence": "🟢 High",
        "review_note": "",
    },
    {
        "decision": "price_flag for sparse quarters (not auto-excluded)",
        "rationale": "Rather than silently dropping flagged quarters, we add a `price_flag` column so Joel can see which quarters are suspicious and make an informed call about the sample window.",
        "confidence": "🟢 High",
        "review_note": "Joel: see Data Quality section above — recommend starting from 2011Q1 or dropping price_flag==1 rows.",
    },
]

for i, d in enumerate(decisions):
    with st.expander(f"{d['confidence']} Decision {i+1}: {d['decision']}"):
        st.write(f"**Rationale:** {d['rationale']}")
        if d['review_note']:
            st.info(d['review_note'])

st.divider()

# ──────────────────────────────────────────────────────────────────────────────
# Open Questions for Joel
# ──────────────────────────────────────────────────────────────────────────────
st.header("❓ Open Questions for Joel")

questions = [
    {
        "q": "Handle sparse 2010 quarters: drop year or filter flagged rows?",
        "context": "See Data Quality section above. 2010Q1, Q3, Q4 have anomalous prices for most commodities. The model will still run but results for those quarters will be outliers.",
        "urgency": "🔴 High — affects Session 3 model spec",
        "due": "Before Session 3 begins",
    },
    {
        "q": "Bilateral vs World Aggregate trade data?",
        "context": "Joel emailed DCCEEW team ~22 March 2026. Still awaiting response. Currently using world aggregate (partnerCode=0).",
        "urgency": "🟡 Medium — affects all models but world aggregate is defensible",
        "due": "Any time — confirm when DCCEEW responds",
    },
    {
        "q": "Can you download RBA F11 AUD/USD exchange rates?",
        "context": "Download from rba.gov.au, save as `data/raw/imf/exchange_rate_aud_usd.csv`. Needed to convert USD trade prices to AUD for full Review replication.",
        "urgency": "🟡 Medium — needed before final results",
        "due": "Before Session 4 (leakage calc)",
    },
    {
        "q": "Do you have OECD quarterly GDP CSVs from the Review?",
        "context": "Would improve the trade-weighted GDP series (currently annual IMF data interpolated). Place in `data/raw/imf/oecd_gdp_{country}.csv`.",
        "urgency": "🟡 Medium — IMF fallback is acceptable",
        "due": "Before Session 4",
    },
    {
        "q": "Include scrap steel (HS 7204) in crude steel group?",
        "context": "Joel's mapping includes ferrous waste/scrap in the 'Primary steel' group. Removing it would produce a cleaner price series for crude steel.",
        "urgency": "🟡 Medium — affects crude steel model only",
        "due": "Before Session 3",
    },
]

for q in questions:
    with st.expander(f"{q['urgency']} {q['q']}"):
        st.write(f"**Context:** {q['context']}")
        st.write(f"**Due by:** {q['due']}")

st.divider()

# ──────────────────────────────────────────────────────────────────────────────
# Next Steps
# ──────────────────────────────────────────────────────────────────────────────
st.header("📋 Next Steps (Session 3 — ARDL Estimation)")

next_steps = [
    ("🔴 Before we start", "Joel decides: drop 2010 or filter flagged quarters? (see Data Quality above)"),
    ("🟢 Session 3, Step 1", "Build `src/modelling/ardl_estimator.py` — AIC lag selection, ARDL fit, bounds test"),
    ("🟢 Session 3, Step 2", "Estimate import models for all 7 commodities with ABS demand controls"),
    ("🟢 Session 3, Step 3", "Estimate export models for all 7 commodities with trade-weighted GDP"),
    ("🟢 Session 3, Step 4", "Extract long-run price elasticities (delta method), compare to Review benchmarks"),
    ("🟢 Session 3, Step 5", "Plot impulse response functions and time series for visual inspection"),
    ("🟢 Session 4, Step 1", "Build `src/leakage/leakage_calculator.py` with carbon cost scenarios"),
    ("🟢 Session 4, Step 2", "Produce comparison table: our replication vs Review benchmark results"),
]

for urgency, step in next_steps:
    st.markdown(f"- {urgency} {step}")

st.divider()

# ──────────────────────────────────────────────────────────────────────────────
# Data Files Status
# ──────────────────────────────────────────────────────────────────────────────
st.header("📁 Data Files Status")

data_checks = [
    ("data/raw/abs/construction_gva.csv", "ABS Construction GVA (quarterly, SA)"),
    ("data/raw/abs/final_demand.csv", "ABS Final Demand (quarterly, SA)"),
    ("data/raw/abs/gdp.csv", "ABS GDP (quarterly, SA)"),
    ("data/raw/imf/trade_weighted_gdp.csv", "IMF Trade-weighted GDP (5 countries)"),
    ("data/raw/imf/imf_gdp_annual_CHN.csv", "IMF Annual GDP — China"),
    ("data/raw/imf/imf_gdp_annual_JPN.csv", "IMF Annual GDP — Japan"),
    ("data/raw/imf/imf_gdp_annual_KOR.csv", "IMF Annual GDP — Korea"),
    ("data/raw/imf/imf_gdp_annual_USA.csv", "IMF Annual GDP — USA"),
    ("data/raw/imf/imf_gdp_annual_IND.csv", "IMF Annual GDP — India"),
    ("data/processed/comtrade_quarterly.csv", "Quarterly trade data (all commodities)"),
    ("data/processed/model_dataset.csv", "Model-ready panel (all 14 models)"),
    ("data/processed/clinker_import.csv", "Clinker import model panel"),
    ("data/processed/cement_import.csv", "Cement import model panel"),
    ("data/processed/lime_import.csv", "Lime import model panel"),
    ("data/processed/crude_steel_import.csv", "Crude steel import model panel"),
    ("data/processed/long_steel_import.csv", "Long steel import model panel"),
    ("data/processed/flat_steel_import.csv", "Flat steel import model panel"),
    ("data/processed/treated_flat_steel_import.csv", "Treated flat steel import panel"),
    ("data/raw/comtrade/clinker/", "Raw Comtrade — Clinker"),
    ("data/raw/comtrade/cement/", "Raw Comtrade — Cement"),
    ("data/raw/comtrade/lime/", "Raw Comtrade — Lime"),
    ("data/raw/comtrade/crude_steel/", "Raw Comtrade — Crude Steel"),
    ("data/raw/comtrade/long_steel/", "Raw Comtrade — Long Steel"),
    ("data/raw/comtrade/flat_steel/", "Raw Comtrade — Flat Steel"),
    ("data/raw/comtrade/treated_flat_steel/", "Raw Comtrade — Treated Flat Steel"),
]

rows = []
for path, desc in data_checks:
    full_path = PROJECT_ROOT / path
    exists = full_path.exists()
    if exists and full_path.is_file():
        size = full_path.stat().st_size
        status = f"✅ {size:,} bytes"
    elif exists and full_path.is_dir():
        n_files = len(list(full_path.glob("*.csv")))
        status = f"✅ {n_files} CSV files" if n_files > 0 else "📁 Empty (pending)"
    else:
        status = "❌ Not yet generated"
    rows.append({"File/Path": path, "Description": desc, "Status": status})

st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

# ──────────────────────────────────────────────────────────────────────────────
# Model Dataset Quick View
# ──────────────────────────────────────────────────────────────────────────────
st.subheader("Model Dataset Preview")
model_path = PROJECT_ROOT / "data" / "processed" / "model_dataset.csv"
if model_path.exists():
    df = pd.read_csv(model_path)
    flagged = df[df["price_flag"] == 1][["commodity", "flow", "period_str", "price_usd_per_tonne", "weight_tonnes"]]
    col1, col2, col3 = st.columns(3)
    col1.metric("Total quarters", len(df))
    col2.metric("Flagged quarters", len(flagged))
    col3.metric("Missing values", int(df[["ln_price","ln_demand","ln_quantity"]].isna().sum().sum()))

    if len(flagged) > 0:
        with st.expander(f"Show {len(flagged)} flagged quarters"):
            st.dataframe(
                flagged.rename(columns={"price_usd_per_tonne": "price (USD/t)", "weight_tonnes": "weight (t)"}),
                use_container_width=True, hide_index=True,
            )
else:
    st.info("Model dataset not yet generated. Run `python -m src.data_processing.build_dataset`.")

st.divider()
st.caption(
    "Dashboard auto-generated by Claude Code | "
    "Carbon Leakage Review Replication Project | "
    "DCCEEW methodology reference: Feb 2025 Final Report Annex"
)
