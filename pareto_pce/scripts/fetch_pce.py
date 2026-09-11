#!/usr/bin/env python
# fetch_pce.py
# Baixa U20404 mensal (BEA NIPA Underlying Detail — Price Indexes for PCE by
# Type of Product) e salva em data/pce_indices_raw.csv.
#
# Requer env var BEA_API_KEY. Registro gratis em https://apps.bea.gov/API/signup/
#
# Uso:
#   cd pareto_pce
#   python scripts/fetch_pce.py

import json
import os
import sys
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent

# Proxy corp opcional — mesmo padrao do R (`scripts/proxy_config.R`).
# Se `scripts/proxy_config.py` existe, e' sourceado.
_PROXY_CFG = ROOT / "scripts" / "proxy_config.py"
if _PROXY_CFG.exists():
    exec(_PROXY_CFG.read_text(encoding="utf-8"), {"os": os})

OUT = ROOT / "data" / "pce_indices_raw.csv"
OUT.parent.mkdir(parents=True, exist_ok=True)

KEY = os.environ.get("BEA_API_KEY")
if not KEY:
    sys.exit("[FAIL] env BEA_API_KEY nao setada.")

BASE = "https://apps.bea.gov/api/data/"

# BEA impoe limite de tamanho de resposta; separa em chunks de ~6 anos.
YEAR_CHUNKS = [
    "2000,2001,2002,2003,2004,2005,2006",
    "2007,2008,2009,2010,2011,2012,2013",
    "2014,2015,2016,2017,2018,2019,2020",
    "2021,2022,2023,2024,2025,2026",
]


def fetch(years: str) -> list[dict]:
    params = {
        "UserID": KEY,
        "method": "GetData",
        "datasetname": "NIUnderlyingDetail",
        "TableName": "U20404",
        "Frequency": "M",
        "Year": years,
        "ResultFormat": "json",
    }
    url = f"{BASE}?{urlencode(params)}"
    with urlopen(url, timeout=120) as r:
        j = json.loads(r.read())
    try:
        return j["BEAAPI"]["Results"]["Data"]
    except (KeyError, TypeError):
        err = j.get("BEAAPI", {}).get("Error", j)
        sys.exit(f"[FAIL] BEA API erro: {err}")


all_rows: list[dict] = []
for chunk in YEAR_CHUNKS:
    print(f"[fetch] {chunk}...", flush=True)
    rows = fetch(chunk)
    print(f"        {len(rows)} rows")
    all_rows.extend(rows)

df = pd.DataFrame(all_rows)
df["date"] = pd.to_datetime(df["TimePeriod"], format="%YM%m")
df["value"] = pd.to_numeric(df["DataValue"].astype(str).str.replace(",", ""), errors="coerce")
df["line_number"] = pd.to_numeric(df["LineNumber"], errors="coerce").astype("Int64")
df = (
    df[["date", "line_number", "LineDescription", "SeriesCode", "value"]]
    .rename(columns={"LineDescription": "line_description", "SeriesCode": "series_code"})
    .sort_values(["date", "line_number"])
    .reset_index(drop=True)
)

df.to_csv(OUT, index=False)
print(f"\n[OK] {len(df)} rows -> {OUT.relative_to(ROOT)}")

# Diagnostico: mostra as linhas unicas pra facilitar montagem do leaves_map.
lines = (
    df[["line_number", "line_description", "series_code"]]
    .drop_duplicates()
    .sort_values("line_number")
    .reset_index(drop=True)
)
print(f"\n[diag] {len(lines)} linhas unicas em U20404 (LineNumber, series_code, descricao):")
with pd.option_context("display.max_rows", None, "display.width", 200,
                        "display.max_colwidth", 80):
    print(lines.to_string(index=False))
