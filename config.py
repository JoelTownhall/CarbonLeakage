"""
config.py — Project-wide constants, HS codes, and file paths.

This file centralises all configuration for the Carbon Leakage Review
replication project. Edit this file to change API keys, data directories,
or model parameters. Never hardcode API keys elsewhere.

Relationship to Review: The HS code mappings below correspond to the
production variable (PV) groupings used in Annex Tables 1 & 2. We use
4-digit HS codes from Comtrade, which is coarser than the 10-digit HTISC
codes used in BLADE. This introduces aggregation bias — see Annex Section 5.
"""

import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).parent
DATA_RAW = PROJECT_ROOT / "data" / "raw"
DATA_PROCESSED = PROJECT_ROOT / "data" / "processed"
DATA_REFERENCE = PROJECT_ROOT / "data" / "reference"
OUTPUTS_TABLES = PROJECT_ROOT / "outputs" / "tables"
OUTPUTS_FIGURES = PROJECT_ROOT / "outputs" / "figures"
OUTPUTS_REPORTS = PROJECT_ROOT / "outputs" / "reports"

# ---------------------------------------------------------------------------
# API Keys (never hardcode — read from environment or .env file)
# ---------------------------------------------------------------------------
COMTRADE_API_KEY: str = os.environ.get("COMTRADE_API_KEY", "")

# ---------------------------------------------------------------------------
# Comtrade query parameters (Annex Section 5)
# ---------------------------------------------------------------------------
AUSTRALIA_REPORTER_CODE = "36"  # Australia's UN Comtrade reporter code
WORLD_PARTNER_CODE = "0"        # Partner code 0 = world aggregate

# Data period: Review used Q3 2003 to Q4 2022; we extend to 2024.
COMTRADE_START_YEAR = 2003
COMTRADE_END_YEAR = 2024

# ASSUMPTION: using world aggregate (partnerCode=0) rather than bilateral
# partner weights. The Review may have used bilateral weights — to be
# confirmed with the DCCEEW team. See project memory for follow-up.
USE_WORLD_AGGREGATE = True

# ---------------------------------------------------------------------------
# HS Code mappings (derived from Joel's HS-to-PV mapping spreadsheet,
# 19 Sept 2024 version with float glass, 4-digit groupings)
#
# These map to Safeguard Mechanism production variables (Schedule 2 of the
# National Greenhouse and Energy Reporting (Safeguard Mechanism) Rule 2015).
# ---------------------------------------------------------------------------

# CEMENT GROUP
# PV: "Cement produced from clinker and SCM" (Schedule 2, Item 25)
CEMENT_HS = ["252321", "252329", "252330", "252390"]

# PV: "Clinker not used by facility to make cement" (Schedule 2, Item 24)
CLINKER_HS = ["252310"]

# PV: "Lime" (Schedule 2, Item 26)
# Includes quicklime, slaked lime, hydraulic lime, dolomite, limestone flux
LIME_HS = ["252210", "252220", "252230", "251810", "251820", "252100"]

# STEEL GROUP
# PV: "Crude steel" — ingots, blooms, billets, slabs (primary forms)
# HS 7206 (non-alloy ingots), 7207 (semi-finished), 7218 (stainless primary),
# 7224 (alloy primary)
CRUDE_STEEL_HS = [
    "720610", "720690",                          # Iron/non-alloy ingots & primary forms
    "720711", "720712", "720719", "720720",      # Semi-finished non-alloy steel
    "721810", "721891", "721899",                # Stainless primary forms
    "722410", "722490",                          # Alloy primary forms
    "720410", "720429", "720449", "720450",      # Scrap (ferrous waste, remelting)
]

# PV: "Long steel products" — bars, rods, angles, shapes, sections
# HS 7213, 7214, 7215, 7216, plus stainless/alloy bars, hollow drill rods
LONG_STEEL_HS = [
    "721310", "721320", "721391", "721399",      # Non-alloy bars/rods (coils)
    "721410", "721420", "721430", "721491", "721499",  # Non-alloy bars/rods
    "721510", "721550", "721590",                # Cold-formed bars/rods
    "721610", "721621", "721622", "721631", "721632", "721633",  # Sections
    "721640", "721650", "721661", "721669", "721691", "721699",
    "722100", "722211", "722219", "722220", "722230", "722240",  # Stainless bars
    "722710", "722720", "722790",                # Alloy bars (coils)
    "722810", "722820", "722830", "722840", "722850", "722860", "722870", "722880",
    "730110", "730120",                          # Sheet piling, welded sections
    "730431", "730439", "730441", "730451",      # Tubes/pipes
]

# PV: "Flat steel products" — hot/cold rolled flat products (not coated)
# HS 7208, 7209, 7211 (non-alloy), 7219 (stainless), 7225-7226 (alloy)
FLAT_STEEL_HS = [
    "720810", "720825", "720826", "720827", "720836", "720837", "720838",
    "720839", "720840", "720851", "720852", "720853", "720854", "720890",  # HS 7208
    "720915", "720916", "720917", "720918", "720925", "720926", "720927",
    "720928", "720990",                          # HS 7209 (cold-rolled)
    "721113", "721114", "721119", "721123", "721129", "721190",  # HS 7211 (<600mm)
    "721931", "721932", "721933", "721934", "721935",  # Stainless flat HS 7219
    "722020",                                    # Stainless flat <600mm HS 7220
    "722550", "722692",                          # Alloy flat HS 7225/7226
]

# PV: "Treated flat steel products" — coated, plated, painted flat products
# HS 7210 (≥600mm coated), 7212 (<600mm coated)
TREATED_FLAT_STEEL_HS = [
    "721011", "721012", "721020", "721030", "721041", "721049",
    "721050", "721061", "721069", "721070", "721090",  # HS 7210 (≥600mm)
    "721210", "721220", "721230", "721240", "721250", "721260",  # HS 7212 (<600mm)
]

# Convenience dict: commodity name → list of HS codes
COMMODITY_HS_CODES: dict = {
    "clinker": CLINKER_HS,
    "cement": CEMENT_HS,
    "lime": LIME_HS,
    "crude_steel": CRUDE_STEEL_HS,
    "long_steel": LONG_STEEL_HS,
    "flat_steel": FLAT_STEEL_HS,
    "treated_flat_steel": TREATED_FLAT_STEEL_HS,
}

# ---------------------------------------------------------------------------
# Model parameters (Annex Section 4)
# ---------------------------------------------------------------------------
MAX_LAG_QUARTERS = 4    # Maximum lag length for ARDL (following Review convention)
ARDL_TREND = "c"        # Default: constant only; some models use "ct" (constant+trend)
HAC_COV_TYPE = "HAC"    # Newey-West HAC standard errors
BOUNDS_TEST_CASE = 3    # Pesaran et al. (2001) Case III: unrestricted intercept, no trend

# ---------------------------------------------------------------------------
# Carbon leakage scenario parameters (Annex Section 3 / Main Report Section 2.3)
#
# Scenario: A$50/tCO2-e carbon price in 2030, NO TEBA for any commodity.
# All commodities face full 4.9% annual baseline decline rate.
# ERC (emissions reduction contribution) in 2029-30 without TEBA = 0.657
# eff_p = 1 - 0.657 = 0.343 (34.3% of BAU emissions exposed to carbon cost)
# ---------------------------------------------------------------------------
CARBON_PRICE_2030 = 50.0    # A$/tCO2-e projected carbon price in 2030
ERC_NO_TEBA = 0.657         # Emissions reduction contribution (no TEBA)
EFF_P_NO_TEBA = 1 - ERC_NO_TEBA  # = 0.343

# Default emissions intensities (tCO2-e per tonne of product).
# These are approximations from publicly available NGER data.
# The Review used more precise facility-level EID data.
# NOTE: These should be updated with latest CER Emissions Intensity Determinations.
EMISSIONS_INTENSITY: dict = {
    "clinker": 0.82,
    "cement": 0.708,
    "lime": 1.20,
    "crude_steel": 1.80,
    "long_steel": 0.50,
    "flat_steel": 0.60,
    "treated_flat_steel": 0.40,
}

# Import/production ratios (from Review main report Table 2)
IMPORT_PROD_RATIO: dict = {
    "clinker": 0.9,
    "cement": 0.1,
    "lime": 0.3,
    "crude_steel": 0.1,
    "long_steel": 0.5,
    "flat_steel": 0.1,
    "treated_flat_steel": 0.3,
}

# Export/production ratios (from Review main report Table 3)
EXPORT_PROD_RATIO: dict = {
    "clinker": 0.1,
    "cement": 0.1,
    "lime": 0.1,
    "crude_steel": 0.1,
    "long_steel": 0.1,
    "flat_steel": 0.1,
    "treated_flat_steel": 0.5,
}

# Safeguard Mechanism coverage percentages (from Review Table 2)
SG_COVERAGE: dict = {
    "clinker": 1.00,
    "cement": 1.00,
    "lime": 0.74,
    "crude_steel": 1.00,
    "long_steel": 0.94,
    "flat_steel": 1.00,
    "treated_flat_steel": 0.59,
}

# ---------------------------------------------------------------------------
# Review benchmark results (Annex Tables 1 & 2)
# For comparison against our replication results.
# Format: {commodity: {"elasticity": float, "se": float, "adj_r2": float,
#                       "bounds_p": float, "trend": bool, "year": int}}
# ---------------------------------------------------------------------------
REVIEW_IMPORT_RESULTS: dict = {
    "cement":             {"elasticity": -2.46, "se": 0.34, "adj_r2": 0.873, "bounds_p": 0.000, "trend": True,  "year": 2019, "control": "Final Demand"},
    "clinker":            {"elasticity": -0.82, "se": 0.34, "adj_r2": 0.921, "bounds_p": 0.000, "trend": True,  "year": 2019, "control": "Construction GVA"},
    "lime":               {"elasticity": -3.00, "se": 0.16, "adj_r2": 0.953, "bounds_p": 0.000, "trend": True,  "year": 2019, "control": "Final Demand"},
    "crude_steel":        {"elasticity": -3.89, "se": 2.15, "adj_r2": 0.749, "bounds_p": 0.000, "trend": False, "year": 2022, "control": "Construction GVA"},
    "long_steel":         {"elasticity": -0.56, "se": 0.32, "adj_r2": 0.467, "bounds_p": 0.000, "trend": True,  "year": 2022, "control": "Construction GVA"},
    "flat_steel":         {"elasticity": -0.53, "se": 0.20, "adj_r2": 0.788, "bounds_p": 0.000, "trend": False, "year": 2019, "control": "Final Demand"},
}

REVIEW_EXPORT_RESULTS: dict = {
    "cement":             {"elasticity": -0.59, "se": 0.50, "adj_r2": 0.655, "bounds_p": 0.001, "trend": False, "year": 2019, "control": "Trade-weighted GDP"},
    "lime":               {"elasticity": -2.60, "se": 0.80, "adj_r2": 0.846, "bounds_p": 0.030, "trend": True,  "year": 2022, "control": "Trade-weighted GDP"},
    "crude_steel":        {"elasticity": -3.60, "se": 0.82, "adj_r2": 0.928, "bounds_p": 0.000, "trend": False, "year": 2022, "control": "Trade-weighted GDP"},
    "long_steel":         {"elasticity": -0.45, "se": 0.08, "adj_r2": 0.519, "bounds_p": 0.000, "trend": True,  "year": 2022, "control": "Trade-weighted GDP"},
    "flat_steel":         {"elasticity": -0.41, "se": 0.77, "adj_r2": 0.619, "bounds_p": 0.010, "trend": False, "year": 2019, "control": "Trade-weighted GDP"},
    "treated_flat_steel": {"elasticity": -3.38, "se": 0.61, "adj_r2": 0.647, "bounds_p": 0.067, "trend": False, "year": 2019, "control": "Trade-weighted GDP"},
}

# ---------------------------------------------------------------------------
# Trade-weighted GDP index weights (Annex Section 4, "Demand variables")
# Source: DFAT export statistics for 2015, as used in the Review.
# ---------------------------------------------------------------------------
TRADE_WEIGHT_GDP: dict = {
    "CHN": 0.477,   # China
    "JPN": 0.252,   # Japan
    "KOR": 0.115,   # Republic of Korea
    "USA": 0.090,   # United States
    "IND": 0.066,   # India
}

# IMF country codes for the DataMapper API (uses ISO3 codes)
IMF_COUNTRY_CODES: dict = {
    "CHN": "CHN",
    "JPN": "JPN",
    "KOR": "KOR",
    "USA": "USA",
    "IND": "IND",
}

# ---------------------------------------------------------------------------
# Bilateral trade partner countries
#
# UN Comtrade uses M49 numeric codes (same as UN country codes).
# These are the major import source countries for each commodity group,
# based on DFAT/ABS trade statistics.
#
# Used for:
#   - Bilateral Comtrade queries (partnerCode) to break down imports by origin
#   - Carbon leakage assessment: identifying high-emission import sources
#   - Comparison against world-aggregate results
# ---------------------------------------------------------------------------

# UN M49 numeric codes for key bilateral trading partners
# Format: {ISO3: M49_code}
COMTRADE_PARTNER_CODES: dict = {
    "CHN": "156",   # China
    "JPN": "392",   # Japan
    "KOR": "410",   # Republic of Korea
    "IND": "356",   # India
    "VNM": "704",   # Vietnam
    "MYS": "458",   # Malaysia
    "THA": "764",   # Thailand
    "IDN": "360",   # Indonesia
    "TWN": "490",   # Taiwan (Other Asia, nes in Comtrade)
    "USA": "840",   # United States
    "DEU": "276",   # Germany
    "GBR": "826",   # United Kingdom
    "UKR": "804",   # Ukraine
    "NZL": "554",   # New Zealand
    "CAN": "124",   # Canada
    "SGP": "702",   # Singapore
    "BEL": "056",   # Belgium
    "NLD": "528",   # Netherlands
}

# Major import source countries by commodity group
# Based on ABS International Trade statistics and Comtrade bilateral data.
# Ordered approximately by import share (largest first).
MAJOR_IMPORT_SOURCES: dict = {
    "clinker": ["CHN", "JPN", "KOR", "VNM", "THA"],
    "cement":  ["CHN", "KOR", "JPN", "THA", "VNM", "IDN"],
    "lime":    ["CHN", "JPN", "KOR", "DEU", "BEL"],
    # Steel groups: China and East Asia dominate Australian imports
    "crude_steel":        ["CHN", "JPN", "KOR", "IND", "UKR", "USA"],
    "long_steel":         ["CHN", "JPN", "KOR", "IND", "VNM", "MYS", "THA"],
    "flat_steel":         ["CHN", "JPN", "KOR", "IND", "TWN", "VNM", "DEU"],
    "treated_flat_steel": ["CHN", "JPN", "KOR", "IND", "TWN", "DEU", "NLD"],
}

# Countries with explicit carbon pricing mechanisms (as of 2025).
# Imports from these countries are less likely to cause carbon leakage
# as their producers already face a carbon cost.
# Sources: World Bank Carbon Pricing Dashboard; ICAP ETS Map.
COUNTRIES_WITH_CARBON_PRICE: list = [
    "GBR",   # UK ETS (2021–)
    "NZL",   # NZ ETS (2008–)
    "CAN",   # Federal Output-Based Pricing System (2019–)
    "KOR",   # Korea ETS (2015–)
    "JPN",   # Tokyo/Saitama ETS + J-Credit; national carbon levy (2012–)
    "SGP",   # Singapore Carbon Tax (2019–)
    "CHE",   # Swiss ETS (2008–, linked to EU ETS 2020–)
    # EU member states — ETS covers steel, cement, lime
    "DEU",   # Germany (EU ETS)
    "FRA",   # France (EU ETS)
    "NLD",   # Netherlands (EU ETS)
    "BEL",   # Belgium (EU ETS)
    "ITA",   # Italy (EU ETS)
    "ESP",   # Spain (EU ETS)
    "POL",   # Poland (EU ETS)
    "SWE",   # Sweden (EU ETS + carbon tax)
    "AUT",   # Austria (EU ETS)
    "FIN",   # Finland (EU ETS + carbon tax)
    "DNK",   # Denmark (EU ETS)
    "IRL",   # Ireland (EU ETS)
    "PRT",   # Portugal (EU ETS)
    "CZE",   # Czech Republic (EU ETS)
    "HUN",   # Hungary (EU ETS)
    "ROU",   # Romania (EU ETS)
    "GRC",   # Greece (EU ETS)
    "SVK",   # Slovakia (EU ETS)
    "BGR",   # Bulgaria (EU ETS)
    "HRV",   # Croatia (EU ETS)
    "SVN",   # Slovenia (EU ETS)
    "EST",   # Estonia (EU ETS)
    "LVA",   # Latvia (EU ETS)
    "LTU",   # Lithuania (EU ETS)
    "LUX",   # Luxembourg (EU ETS)
    "MLT",   # Malta (EU ETS)
    "CYP",   # Cyprus (EU ETS)
    "NOR",   # Norway (EU ETS-linked + carbon tax)
    "ISL",   # Iceland (EU ETS-linked)
    "LIE",   # Liechtenstein (EU ETS-linked)
]
