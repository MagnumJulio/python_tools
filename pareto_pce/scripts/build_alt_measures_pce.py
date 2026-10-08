#!/usr/bin/env python3
# build_alt_measures_pce.py
#
# Medidas alternativas de inflacao PCE pra servir no SQL corp.
#
# Series oficiais:
#   - Cleveland Fed Median PCE (CSV publico, full history 1977+, MoM% + YoY%)
#   - Dallas Fed Trimmed Mean PCE (FRED: PCETRIM12M680SFRBDAL 12mo + PCETRIM1M680SFRBDAL 1mo)
#
# Uso:
#   cd pareto_pce
#   python scripts/build_alt_measures_pce.py
#
# Env:
#   CORP_PROXY_URL (opcional)

from __future__ import annotations

import io
import os
import subprocess
import sys
from pathlib import Path
from urllib.request import Request, urlopen

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
CLEV_CSV = ROOT / "data" / "raw" / "cleveland" / "median-pce-full-history.csv"
OUT_CSV = ROOT / "data" / "pce_alt_measures.csv"

_PROXY_URL = os.environ.get("CORP_PROXY_URL") or None


def _curl_get(url: str, timeout: int = 60, retries: int = 3) -> bytes:
    last_err = None
    for attempt in range(1, retries + 1):
        cmd = ["curl", "-sL", "-f", "--max-time", str(timeout),
               "-A", "Mozilla/5.0"]
        if _PROXY_URL: cmd += ["-x", _PROXY_URL]
        cmd.append(url)
        try:
            r = subprocess.run(cmd, capture_output=True, timeout=timeout + 10)
        except subprocess.TimeoutExpired:
            last_err = f"timeout attempt {attempt}"
            continue
        if r.returncode == 0:
            return r.stdout
        last_err = f"rc={r.returncode} attempt {attempt}"
    raise RuntimeError(last_err)


def fetch_fred_csv(fred_id: str) -> pd.Series:
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={fred_id}"
    buf = io.BytesIO(_curl_get(url))
    df = pd.read_csv(buf)
    df.columns = ["date", "value"]
    df["date"] = pd.to_datetime(df["date"])
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    return df.set_index("date")["value"].dropna()


def fetch_cleveland_median_pce() -> pd.DataFrame:
    """CSV Cleveland Fed full history (1977+): Date, MoM%, YoY%."""
    if not CLEV_CSV.exists():
        print("[cleveland] baixando full history CSV...")
        CLEV_CSV.parent.mkdir(parents=True, exist_ok=True)
        url = "https://www.clevelandfed.org/-/media/files/webcharts/medianpce/median-pce-full-history.csv"
        CLEV_CSV.write_bytes(_curl_get(url, timeout=60))
    df = pd.read_csv(CLEV_CSV)
    df.columns = ["date", "ann_1mo_raw", "ann_12mo"]  # 1mo% / 12mo% direto
    df["date"] = pd.to_datetime(df["date"], format="%m/%d/%Y", errors="coerce")
    df = df.dropna(subset=["date"]).copy()
    # 1mo% raw do CSV eh percent change nao-annualized; anualizar
    df["ann_1mo"] = ((1 + pd.to_numeric(df["ann_1mo_raw"], errors="coerce") / 100) ** 12 - 1) * 100
    df["ann_12mo"] = pd.to_numeric(df["ann_12mo"], errors="coerce")
    df["measure"] = "median_pce"
    return df[["date", "measure", "ann_1mo", "ann_12mo"]]


def main() -> None:
    all_rows = []

    # 1. Cleveland Median PCE (CSV publico full history)
    print("[1] Cleveland Fed Median PCE (CSV publico)...")
    try:
        clev = fetch_cleveland_median_pce()
        n = clev.dropna(subset=["ann_12mo"]).shape[0]
        print(f"  median_pce: {n} obs YoY, {clev.date.min().date()} -> {clev.date.max().date()}")
        all_rows.append(clev)
    except Exception as e:
        print(f"  [FAIL] Cleveland: {e}")

    # 2. Dallas Trimmed Mean PCE (FRED)
    print("[2] Dallas Fed Trimmed Mean PCE (FRED)...")
    for mname, fred_id, col in [
        ("trimmed_mean_pce_12mo", "PCETRIM12M680SFRBDAL", "ann_12mo"),
        ("trimmed_mean_pce_1mo", "PCETRIM1M680SFRBDAL", "ann_1mo"),
    ]:
        try:
            s = fetch_fred_csv(fred_id)
            df = s.rename(col).reset_index()
            df["measure"] = mname
            # Preenche outra coluna com NaN pra manter schema uniforme
            other = "ann_1mo" if col == "ann_12mo" else "ann_12mo"
            df[other] = np.nan
            all_rows.append(df[["date", "measure", "ann_1mo", "ann_12mo"]])
            print(f"  {mname}: {len(df)} obs, {df.date.min().date()} -> {df.date.max().date()}")
        except Exception as e:
            print(f"  [FAIL FRED] {mname}: {str(e)[:120]}")

    if not all_rows:
        sys.exit("[FAIL] nenhuma series obtida.")

    out = pd.concat(all_rows, ignore_index=True).sort_values(["measure", "date"]).reset_index(drop=True)
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT_CSV, index=False)
    print(f"\n[OK] {len(out)} rows -> {OUT_CSV.relative_to(ROOT)}")

    s = out.groupby("measure").agg(
        n_1mo=("ann_1mo", lambda x: x.notna().sum()),
        n_12mo=("ann_12mo", lambda x: x.notna().sum()),
        min_date=("date", "min"),
        max_date=("date", "max"),
    )
    print(f"\nSummary:")
    print(s.to_string())


if __name__ == "__main__":
    main()
