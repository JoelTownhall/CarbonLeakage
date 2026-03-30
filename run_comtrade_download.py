"""
run_comtrade_download.py — Standalone Comtrade downloader.

Run this script on your LOCAL machine (not in the Claude Code sandbox)
to download all trade data. The sandbox firewall blocks comtradeapi.un.org
but your local machine does not have this restriction.

HOW TO RUN (in PowerShell or Command Prompt):
    cd C:\users\joelr\projects\carbonleakage
    pip install comtradeapicall pandas
    python run_comtrade_download.py

The script will:
  - Download monthly import/export data for all 7 commodity groups
  - Save one CSV per commodity per year to data/raw/comtrade/
  - Skip files already downloaded (safe to re-run)
  - Print progress as it goes

When done, commit the CSVs:
    git add data/raw/comtrade/
    git commit -m "data: add raw Comtrade downloads"
    git push
"""

import os
import time
import logging
from pathlib import Path

import pandas as pd
import comtradeapicall

# ── Configuration ─────────────────────────────────────────────────────────────

API_KEY = "ea20fad6663841b58cb4c6b08ae246d0"

START_YEAR = 2003
END_YEAR   = 2024

# Commodity → list of HS codes (from Joel's mapping spreadsheet)
COMMODITY_HS_CODES = {
    "clinker":            ["252310"],
    "cement":             ["252321", "252329", "252330", "252390"],
    "lime":               ["252210", "252220", "252230", "251810", "251820", "252100"],
    "crude_steel":        ["720610", "720690", "720711", "720712", "720719", "720720",
                           "721810", "721891", "721899", "722410", "722490",
                           "720410", "720429", "720449", "720450"],
    "long_steel":         ["721310", "721320", "721391", "721399",
                           "721410", "721420", "721430", "721491", "721499",
                           "721510", "721550", "721590",
                           "721610", "721621", "721622", "721631", "721632", "721633",
                           "721640", "721650", "721661", "721669", "721691", "721699",
                           "722100", "722211", "722219", "722220", "722230", "722240",
                           "722710", "722720", "722790",
                           "722810", "722820", "722830", "722840", "722850", "722860",
                           "722870", "722880", "730110", "730120",
                           "730431", "730439", "730441", "730451"],
    "flat_steel":         ["720810", "720825", "720826", "720827", "720836", "720837",
                           "720838", "720839", "720840", "720851", "720852", "720853",
                           "720854", "720890",
                           "720915", "720916", "720917", "720918", "720925", "720926",
                           "720927", "720928", "720990",
                           "721113", "721114", "721119", "721123", "721129", "721190",
                           "721931", "721932", "721933", "721934", "721935",
                           "722020", "722550", "722692"],
    "treated_flat_steel": ["721011", "721012", "721020", "721030", "721041", "721049",
                           "721050", "721061", "721069", "721070", "721090",
                           "721210", "721220", "721230", "721240", "721250", "721260"],
}

OUTPUT_DIR = Path(__file__).parent / "data" / "raw" / "comtrade"
SLEEP_SECONDS = 1.5   # Be polite to the API
MAX_RETRIES   = 5

# ── Setup ─────────────────────────────────────────────────────────────────────

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger(__name__)


def build_period_string(year: int) -> str:
    months = [f"{year}{m:02d}" for m in range(1, 13)]
    return ",".join(months)


def fetch_one_year(commodity: str, hs_codes: list, year: int) -> pd.DataFrame | None:
    cache_path = OUTPUT_DIR / commodity / f"{year}.csv"
    cache_path.parent.mkdir(parents=True, exist_ok=True)

    if cache_path.exists():
        log.info("  SKIP (cached): %s/%d", commodity, year)
        return pd.read_csv(cache_path, dtype=str)

    hs_str     = ",".join(str(c) for c in hs_codes)
    period_str = build_period_string(year)

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            df = comtradeapicall.previewFinalData(
                typeCode="C",
                freqCode="M",
                clCode="HS",
                period=period_str,
                reporterCode="36",        # Australia
                cmdCode=hs_str,
                flowCode="M,X",           # Imports + Exports
                partnerCode="0",          # World aggregate
                partner2Code=0,
                customsCode=None,
                motCode=None,
                maxRecords=500,
                format_output="JSON",
                aggregateBy=None,
                breakdownMode="classic",
                countOnly=None,
                includeDesc=True,
            )
            if df is not None and not df.empty:
                df.to_csv(cache_path, index=False)
                log.info("  OK: %s/%d — %d rows saved", commodity, year, len(df))
                time.sleep(SLEEP_SECONDS)
                return df
            else:
                log.warning("  Empty response (attempt %d/%d) — retrying ...", attempt, MAX_RETRIES)
                time.sleep(SLEEP_SECONDS * attempt)
        except Exception as e:
            log.warning("  Error (attempt %d/%d): %s", attempt, MAX_RETRIES, e)
            time.sleep(SLEEP_SECONDS * attempt)

    log.error("  FAILED: %s/%d after %d attempts", commodity, year, MAX_RETRIES)
    return None


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    total_commodities = len(COMMODITY_HS_CODES)
    total_years       = END_YEAR - START_YEAR + 1
    total_calls       = total_commodities * total_years

    print(f"\n{'='*60}")
    print(f"  Comtrade Downloader — Carbon Leakage Replication")
    print(f"{'='*60}")
    print(f"  Commodities : {total_commodities}")
    print(f"  Years       : {START_YEAR}–{END_YEAR} ({total_years} years)")
    print(f"  API calls   : up to {total_calls} (skips cached files)")
    print(f"  Output dir  : {OUTPUT_DIR}")
    print(f"{'='*60}\n")

    results = {}
    for commodity, hs_codes in COMMODITY_HS_CODES.items():
        print(f"\n[{commodity.upper()}]")
        frames = []
        for year in range(START_YEAR, END_YEAR + 1):
            df = fetch_one_year(commodity, hs_codes, year)
            if df is not None:
                frames.append(df)
        results[commodity] = len(frames)

    print(f"\n{'='*60}")
    print("  DOWNLOAD COMPLETE")
    print(f"{'='*60}")
    for commodity, n_years in results.items():
        status = "✓" if n_years == total_years else f"⚠ {n_years}/{total_years} years"
        print(f"  {commodity:<20} {status}")

    print(f"\nNext steps:")
    print(f"  git add data/raw/comtrade/")
    print(f"  git commit -m 'data: add raw Comtrade downloads'")
    print(f"  git push")
