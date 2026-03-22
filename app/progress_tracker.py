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
st.caption(f"Last updated: 22 March 2026 | Branch: `phase-1-data-collection`")

# ──────────────────────────────────────────────────────────────────────────────
# Overall Phase Progress
# ──────────────────────────────────────────────────────────────────────────────
st.header("📊 Phase Progress")

phases = {
    "Phase 1: Data Collection": {
        "status": "🟡 In Progress",
        "pct": 60,
        "note": "API wrappers built; Comtrade blocked by firewall (see issues below)"
    },
    "Phase 2: ARDL Model Estimation": {
        "status": "⚪ Not Started",
        "pct": 0,
        "note": "Depends on Phase 1 completion"
    },
    "Phase 3: Leakage Calculation": {
        "status": "⚪ Not Started",
        "pct": 0,
        "note": "Depends on Phase 2"
    },
    "Phase 4: Streamlit Web App": {
        "status": "🟡 Partial",
        "pct": 10,
        "note": "This dashboard is the beginning of Phase 4"
    },
}

cols = st.columns(len(phases))
for col, (phase, info) in zip(cols, phases.items()):
    col.metric(label=phase.split(":")[0], value=info["status"])
    col.progress(info["pct"])
    col.caption(info["note"])

st.divider()

# ──────────────────────────────────────────────────────────────────────────────
# Session 1 Status
# ──────────────────────────────────────────────────────────────────────────────
st.header("✅ What's Been Done (Session 1 — 22 March 2026)")

done = [
    ("Project structure", "Created full directory tree: `src/`, `data/`, `outputs/`, `app/`"),
    ("config.py", "All HS codes, model parameters, Review benchmark results, scenario constants"),
    ("comtrade_fetcher.py", "Full UN Comtrade API wrapper with retry logic and CSV caching — **blocked by firewall** (see issues)"),
    ("abs_fetcher.py", "ABS SDMX API wrapper — **working**. Fetches Construction GVA, Final Demand, GDP"),
    ("imf_fetcher.py", "IMF annual GDP + trade-weighted index builder — **working** (annual → quarterly interpolation)"),
    ("exchange_rates.py", "BIS/IMF AUD/USD exchange rate fetcher — BIS needs firewall access; IMF fallback available"),
    ("ABS data verified", "86 quarters of Construction GVA, Final Demand, and GDP loaded successfully (2003-Q3 to 2024-Q4)"),
    ("IMF GDP verified", "Annual GDP growth rates for CHN, JPN, KOR, USA, IND loaded and trade-weighted index built"),
]

for item, detail in done:
    st.markdown(f"- **{item}**: {detail}")

st.divider()

# ──────────────────────────────────────────────────────────────────────────────
# Current Blockers
# ──────────────────────────────────────────────────────────────────────────────
st.header("🚨 Blockers — Action Required")

st.error("""
**BLOCKER 1: UN Comtrade API — Firewall**

The environment firewall blocks `comtradeapi.un.org:443`.
Without this, we cannot download any trade quantity/price data from Comtrade.

**What needs to happen:**
Request firewall access to `comtradeapi.un.org` (port 443 / HTTPS).
See the system admin instructions in CLAUDE.md under "Network access".

**Impact:** Phase 1 cannot complete until this is resolved.
All ARDL models depend on Comtrade trade data.
""")

st.warning("""
**BLOCKER 2: BIS Exchange Rate API — 404**

The BIS data portal endpoint is returning 404. Exchange rates are needed
to convert USD-invoiced export prices to AUD (Annex Section 5).

**Fallback available:** IMF annual AUD/USD data works but is annual frequency.
For production use, download monthly rates from:
  RBA Statistical Table F11: https://www.rba.gov.au/statistics/historical-data.html
Place as `data/raw/imf/exchange_rate_aud_usd.csv` with columns [period, aud_per_usd].

**Impact:** Moderate. Export price conversion will be approximate until fixed.
""")

st.divider()

# ──────────────────────────────────────────────────────────────────────────────
# Decisions Made
# ──────────────────────────────────────────────────────────────────────────────
st.header("🧠 Decisions Made by Claude (with rationale)")

decisions = [
    {
        "decision": "World aggregate trade data (partnerCode=0)",
        "rationale": "Free-tier Comtrade limits make bilateral data impractical. Joel emailed DCCEEW team to confirm if bilateral was used in the Review.",
        "confidence": "🟡 Medium",
        "review_needed": True,
        "review_note": "**Joel: awaiting DCCEEW response on bilateral vs world aggregate**",
    },
    {
        "decision": "IMF annual GDP (interpolated) instead of OECD quarterly",
        "rationale": "OECD SDMX-JSON API URL format has changed and returns incorrect (unfiltered) data. IMF DataMapper works correctly for all 5 partner countries. Annual data is converted to quarterly by distributing growth uniformly across 4 quarters. This introduces smoothing but is acceptable for a first pass.",
        "confidence": "🟡 Medium",
        "review_needed": True,
        "review_note": "**Joel: if you have OECD quarterly GDP CSVs, place them in `data/raw/imf/oecd_gdp_{country}.csv` and I will use them instead. The Review used OECD data.**",
    },
    {
        "decision": "ABS SDMX API for domestic demand variables",
        "rationale": "Tested and verified 3 series: Construction GVA (ANA_IND_GVA), Final Demand (ANA_EXP), GDP (ANA_AGG). All return 86 quarters 2003-Q3 to 2024-Q4 at chain volume, seasonally adjusted. This matches the Review's ABS 5206.0 source.",
        "confidence": "🟢 High",
        "review_needed": False,
        "review_note": "",
    },
    {
        "decision": "4-digit HS codes from Joel's mapping spreadsheet (19 Sept version)",
        "rationale": "Used the verified HS-to-PV mapping Excel file in Resources/. This gives more granularity than the 4-digit codes in the prompt document. Note the Review used 10-digit HTISC codes in BLADE — aggregation bias is expected and documented in Annex Section 5.",
        "confidence": "🟢 High",
        "review_needed": False,
        "review_note": "",
    },
    {
        "decision": "Cement truncated at 2019 (pre-COVID)",
        "rationale": "Following the Review's preferred specification for cement models. The Review notes COVID disruptions made post-2019 cement data unreliable. Same truncation applied for clinker and lime (cement group).",
        "confidence": "🟢 High",
        "review_needed": False,
        "review_note": "",
    },
]

for i, d in enumerate(decisions):
    with st.expander(f"{d['confidence']} Decision {i+1}: {d['decision']}"):
        st.write(f"**Rationale:** {d['rationale']}")
        if d['review_needed']:
            st.warning(d['review_note'])

st.divider()

# ──────────────────────────────────────────────────────────────────────────────
# Open Questions for Joel
# ──────────────────────────────────────────────────────────────────────────────
st.header("❓ Open Questions for Joel")

questions = [
    {
        "q": "Bilateral vs World Aggregate trade data?",
        "context": "Joel emailed the DCCEEW team to confirm. Currently assuming world aggregate (partnerCode=0).",
        "urgency": "🔴 High — affects all data collection",
        "due": "~24 March 2026",
    },
    {
        "q": "Can firewall access be enabled for comtradeapi.un.org:443?",
        "context": "The entire Comtrade data download is blocked. Without this, no trade data can be fetched.",
        "urgency": "🔴 High — blocks Phase 1 completion",
        "due": "ASAP",
    },
    {
        "q": "Do you have OECD quarterly GDP CSVs from the Review?",
        "context": "The OECD API URL format has changed. If you have the original GDP data files, I can load them directly.",
        "urgency": "🟡 Medium — IMF annual fallback is available",
        "due": "Before Phase 2 modelling",
    },
    {
        "q": "Should we include scrap steel (HS 7204) in crude steel?",
        "context": "Joel's mapping includes ferrous waste/scrap (720410, 720429, 720449, 720450) in the 'Primary steel' group. The Review's production variable is specifically 'crude steel' (ingots/semis). Including scrap changes the price series.",
        "urgency": "🟡 Medium — affects crude steel model specification",
        "due": "Before Phase 2 modelling",
    },
    {
        "q": "Preferred exchange rate source?",
        "context": "BIS portal is returning 404. RBA Statistical Table F11 (monthly AUD/USD) is the best alternative. Alternatively, if you have the exchange rate file from the original Review, that would be ideal.",
        "urgency": "🟡 Medium — needed for export price conversion",
        "due": "Before Phase 1 can complete",
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
st.header("📋 Next Steps (in order)")

next_steps = [
    ("🔴 Immediate", "Request firewall access for `comtradeapi.un.org:443`"),
    ("🔴 Immediate", "Await Joel's confirmation on bilateral vs world aggregate Comtrade query"),
    ("🟡 Session 2", "Build `aggregate_trade.py` — monthly Comtrade data → quarterly, weighted prices"),
    ("🟡 Session 2", "Build `build_dataset.py` — merge Comtrade + ABS + IMF into model-ready DataFrames"),
    ("🟡 Session 2", "Run data quality checks and plot time series for visual inspection (Checkpoint 1)"),
    ("🟢 Session 3", "Build `ardl_estimator.py` and estimate import models for all 7 commodities"),
    ("🟢 Session 3", "Estimate export models; compare to Review benchmark results"),
    ("🟢 Session 4", "Build `leakage_calculator.py` and produce comparison table"),
]

for urgency, step in next_steps:
    st.markdown(f"- {urgency} {step}")

st.divider()

# ──────────────────────────────────────────────────────────────────────────────
# Data Files Status
# ──────────────────────────────────────────────────────────────────────────────
st.header("📁 Data Files Status")

data_checks = [
    ("data/raw/abs/construction_gva.csv", "ABS Construction GVA"),
    ("data/raw/abs/final_demand.csv", "ABS Final Demand"),
    ("data/raw/abs/gdp.csv", "ABS GDP"),
    ("data/raw/imf/trade_weighted_gdp.csv", "IMF Trade-weighted GDP"),
    ("data/raw/imf/imf_gdp_annual_CHN.csv", "IMF Annual GDP — China"),
    ("data/raw/imf/imf_gdp_annual_JPN.csv", "IMF Annual GDP — Japan"),
    ("data/raw/imf/imf_gdp_annual_KOR.csv", "IMF Annual GDP — Korea"),
    ("data/raw/imf/imf_gdp_annual_USA.csv", "IMF Annual GDP — USA"),
    ("data/raw/imf/imf_gdp_annual_IND.csv", "IMF Annual GDP — India"),
    ("data/raw/comtrade/clinker/", "Comtrade — Clinker (blocked)"),
    ("data/raw/comtrade/cement/", "Comtrade — Cement (blocked)"),
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
        status = "❌ Not yet downloaded"
    rows.append({"File/Path": path, "Description": desc, "Status": status})

st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

st.divider()
st.caption(
    "Dashboard auto-generated by Claude Code | "
    "Carbon Leakage Review Replication Project | "
    "DCCEEW methodology reference: Feb 2025 Final Report Annex"
)
