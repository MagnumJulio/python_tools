#!/usr/bin/env python
# fetch_pce.py
# Baixa 2 tabelas BEA NIPA Underlying Detail mensais e salva em data/:
#   - U20404 — Price Indexes for PCE by Type of Product -> pce_indices_raw.csv
#   - U20405 — PCE by Type of Product em current dollars -> pce_nominais_raw.csv
#     (sync 2026-10-28, usada como peso pelo build_breadth_pce.py)
#
# As duas tabelas tem a mesma estrutura de LineNumber — mesmas ~400 linhas,
# os leaves mapeados em build_diffusion.py funcionam identicos pro U20405.
#
# Requer env var BEA_API_KEY. Registro gratis em https://apps.bea.gov/API/signup/
#
# Uso:
#   cd pareto_pce
#   python scripts/fetch_pce.py                # ambos (default)
#   python scripts/fetch_pce.py --skip-nominais  # so U20404 (modo antigo)

import json
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlencode

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent

# --- Proxy corp opcional (env-driven) — ver build_diffusion_cpius.py.
# Respeita HTTP_PROXY/HTTPS_PROXY do ambiente (corp ja seta por default).
_PROXY_URL = (
    os.environ.get("CORP_PROXY_URL")
    or os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    or os.environ.get("HTTP_PROXY")  or os.environ.get("http_proxy")
    or None
)
_PROXY_URL_HTTP = (
    os.environ.get("CORP_PROXY_URL_HTTP")
    or os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy")
    or _PROXY_URL
)
def _mask_proxy(u):
    if not u: return "(none — direct)"
    import re
    return re.sub(r":([^@/]+)@", ":***@", u)
print(f"[proxy] _PROXY_URL = {_mask_proxy(_PROXY_URL)}", flush=True)


def _curl_get(url: str, timeout: int = 120) -> bytes:
    cmd = ["curl"]
    if _PROXY_URL: cmd += ["-x", _PROXY_URL]
    cmd += ["-s", "-f", "--max-time", str(timeout), url]
    r = subprocess.run(cmd, capture_output=True, timeout=timeout + 10)
    if r.returncode != 0:
        raise RuntimeError(
            f"curl fail (rc={r.returncode}): stderr={r.stderr.decode(errors='replace')[:300]}"
        )
    return r.stdout

OUT_PRICES   = ROOT / "data" / "pce_indices_raw.csv"
OUT_NOMINAIS = ROOT / "data" / "pce_nominais_raw.csv"
OUT_PRICES.parent.mkdir(parents=True, exist_ok=True)

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


def fetch(table_name: str, years: str) -> list[dict]:
    params = {
        "UserID": KEY,
        "method": "GetData",
        "datasetname": "NIUnderlyingDetail",
        "TableName": table_name,
        "Frequency": "M",
        "Year": years,
        "ResultFormat": "json",
    }
    url = f"{BASE}?{urlencode(params)}"
    j = json.loads(_curl_get(url))
    try:
        return j["BEAAPI"]["Results"]["Data"]
    except (KeyError, TypeError):
        err = j.get("BEAAPI", {}).get("Error", j)
        sys.exit(f"[FAIL] BEA API erro ({table_name}): {err}")


def fetch_table(table_name: str, out_csv: Path, label: str) -> pd.DataFrame:
    print(f"\n=== Fetching {table_name} ({label}) ===")
    all_rows: list[dict] = []
    for chunk in YEAR_CHUNKS:
        print(f"[fetch] {table_name} {chunk}...", flush=True)
        rows = fetch(table_name, chunk)
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

    df.to_csv(out_csv, index=False)
    print(f"[OK] {table_name}: {len(df)} rows -> {out_csv.relative_to(ROOT)}")
    return df


# -- Parse args pra permitir skip do nominal se o usuario so quer diffusion
skip_nominais = "--skip-nominais" in sys.argv

df_prices = fetch_table("U20404", OUT_PRICES, "Price Indexes")
if not skip_nominais:
    df_nominais = fetch_table("U20405", OUT_NOMINAIS, "Current Dollars (nominais, pra pesos breadth)")

    # Sanity: as 2 tabelas devem ter MESMAS linhas (mesmo esqueleto hierarquico).
    lp = set(df_prices["line_number"].dropna().astype(int))
    ln = set(df_nominais["line_number"].dropna().astype(int))
    only_p = lp - ln
    only_n = ln - lp
    if only_p or only_n:
        print(f"\n[WARN] LineNumbers divergem entre U20404 e U20405:")
        if only_p: print(f"  so em U20404 (prices): {sorted(only_p)[:20]}")
        if only_n: print(f"  so em U20405 (nominais): {sorted(only_n)[:20]}")
    else:
        print(f"\n[sanity] U20404 e U20405 compartilham todos os {len(lp)} LineNumbers.")

# Diagnostico: mostra as linhas unicas de U20404 pra facilitar montagem do leaves_map.
lines = (
    df_prices[["line_number", "line_description", "series_code"]]
    .drop_duplicates()
    .sort_values("line_number")
    .reset_index(drop=True)
)
print(f"\n[diag] {len(lines)} linhas unicas em U20404 (LineNumber, series_code, descricao):")
with pd.option_context("display.max_rows", None, "display.width", 200,
                        "display.max_colwidth", 80):
    print(lines.head(50).to_string(index=False))
if len(lines) > 50:
    print(f"... (+{len(lines)-50} linhas; CSV completo em {OUT_PRICES.relative_to(ROOT)})")
