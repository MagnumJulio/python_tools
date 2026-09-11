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

import pandas as pd
import urllib3

ROOT = Path(__file__).resolve().parent.parent

# --- Proxy corp (HARDCODED via urllib3 ProxyManager) — ver build_diffusion_cpius.py.
_PROXY_USER = "MJCCHGX"
_PROXY_PASS = "191435"
_PROXY_HOST = "proxynew.itau"

_PROXY_MANAGER = urllib3.ProxyManager(
    proxy_url=f"http://{_PROXY_HOST}:8443",
    proxy_headers=urllib3.make_headers(proxy_basic_auth=f"{_PROXY_USER}:{_PROXY_PASS}"),
    timeout=urllib3.Timeout(connect=30, read=120),
)

os.environ["HTTP_PROXY"]  = f"http://{_PROXY_USER}:{_PROXY_PASS}@{_PROXY_HOST}:8080"
os.environ["HTTPS_PROXY"] = f"http://{_PROXY_USER}:{_PROXY_PASS}@{_PROXY_HOST}:8443"
os.environ["http_proxy"]  = os.environ["HTTP_PROXY"]
os.environ["https_proxy"] = os.environ["HTTPS_PROXY"]

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
    r = _PROXY_MANAGER.request("GET", url)
    if r.status != 200:
        raise RuntimeError(f"HTTP {r.status}: {r.data[:200]!r}")
    j = json.loads(r.data)
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
