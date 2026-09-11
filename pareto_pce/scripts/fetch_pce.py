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
import urllib.request
from pathlib import Path
from urllib.parse import urlencode, urlparse
from urllib.request import urlopen

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent

# --- Proxy corp --- (ver comentario em pareto_cpius/scripts/build_diffusion_cpius.py)
_PROXY_CFG = ROOT / "scripts" / "proxy_config.py"
if _PROXY_CFG.exists():
    exec(_PROXY_CFG.read_text(encoding="utf-8"),
         {"os": os, "__file__": str(_PROXY_CFG)})


def _install_proxy_handler():
    https_url = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    http_url  = os.environ.get("HTTP_PROXY")  or os.environ.get("http_proxy")
    if not (https_url or http_url):
        return

    def _parse(u):
        if not u:
            return None
        p = urlparse(u)
        return f"{p.scheme}://{p.hostname}:{p.port}", p.username, p.password

    proxies = {}
    creds = []
    for scheme, u in [("https", https_url), ("http", http_url)]:
        parsed = _parse(u)
        if parsed:
            bare, user, pw = parsed
            proxies[scheme] = bare
            if user and pw:
                creds.append((bare, user, pw))

    handlers = [urllib.request.ProxyHandler(proxies)]
    if creds:
        pwmgr = urllib.request.HTTPPasswordMgrWithDefaultRealm()
        for bare, user, pw in creds:
            pwmgr.add_password(None, bare, user, pw)
        handlers.append(urllib.request.ProxyBasicAuthHandler(pwmgr))

    opener = urllib.request.build_opener(*handlers)
    urllib.request.install_opener(opener)
    print(f"[PROXY] handler explicito instalado: {list(proxies.keys())} "
          f"({len(creds)} com auth)")


_install_proxy_handler()

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
