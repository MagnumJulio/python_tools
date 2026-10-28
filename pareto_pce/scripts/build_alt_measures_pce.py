#!/usr/bin/env python3
# build_alt_measures_pce.py
#
# Medidas alternativas de inflacao PCE pra servir no SQL corp.
#
# Series oficiais:
#   - Cleveland Fed Median PCE (CSV publico, full history 1977+, MoM% + YoY%)
#   - Dallas Fed Trimmed Mean PCE (FRED 1mo + 12mo, SA)
#
# Sync 2026-10-28: alinhado com padrao CPI alt_measures — produz value_index
# (level, SA, rebase Jan/2000=100) via chain universal de ann_1mo. CSV passa a
# ter coluna `value_index` alem dos rates. SQL loader so sobe o index.
#
# Dallas FRED IDs renomeados em 2026-10 — antigos (`PCETRIM{1M,12M}680SFRBDAL`)
# retornavam 404; novos sao `PCETRIM1M158SFRBDAL` + `PCETRIM12M159SFRBDAL`.
#
# Uso:
#   cd pareto_pce
#   python scripts/build_alt_measures_pce.py
#
# Env:
#   CORP_PROXY_URL ou HTTPS_PROXY (corp)
#   CACHE_TTL_HOURS=24 (xlsx/csv Fed re-fetch window)
#   SKIP_DALLAS=1  (pula Dallas FRED se router corp cair)

from __future__ import annotations

import io
import os
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
CLEV_CSV = ROOT / "data" / "raw" / "cleveland" / "median-pce-full-history.csv"
OUT_CSV = ROOT / "data" / "pce_alt_measures.csv"

# Universo esperado — se vier menos que isso, o guard em main() preserva o CSV
# existente em vez de sobrescrever com dado parcial. `SKIP_DALLAS=1` tira
# Dallas do conjunto esperado (fallback pra corp bloqueado).
EXPECTED_MEASURES = {
    "median_pce",         # Cleveland Fed CSV
    "trimmed_mean_pce",   # Dallas Fed FRED
}

CACHE_TTL_HOURS = int(os.environ.get("CACHE_TTL_HOURS", "24"))

# Proxy: respeita HTTP_PROXY/HTTPS_PROXY do ambiente corp (ja setados).
# CORP_PROXY_URL fica como override opcional.
_PROXY_URL = (
    os.environ.get("CORP_PROXY_URL")
    or os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    or os.environ.get("HTTP_PROXY")  or os.environ.get("http_proxy")
    or None
)
def _mask_proxy(u):
    if not u: return "(none — direct)"
    import re
    return re.sub(r":([^@/]+)@", ":***@", u)
print(f"[proxy] _PROXY_URL = {_mask_proxy(_PROXY_URL)}", flush=True)


def _cache_fresh(path: Path, ttl_hours: int = CACHE_TTL_HOURS) -> bool:
    if not path.exists():
        return False
    age_h = (time.time() - path.stat().st_mtime) / 3600
    return age_h < ttl_hours


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
        last_err = f"rc={r.returncode} attempt {attempt}: {r.stderr.decode()[:200]}"
    raise RuntimeError(last_err)


def fetch_fred_csv(fred_id: str) -> pd.Series:
    """FRED CSV publico via requests (trust_env). Fallback curl se dar pau."""
    import requests
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={fred_id}"
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    buf = io.BytesIO(r.content)
    df = pd.read_csv(buf)
    df.columns = ["date", "value"]
    df["date"] = pd.to_datetime(df["date"])
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    return df.set_index("date")["value"].dropna()


def fetch_cleveland_median_pce() -> pd.DataFrame:
    """CSV Cleveland Fed full history (1977+): Date, MoM%, YoY%."""
    if not _cache_fresh(CLEV_CSV):
        print("[cleveland] cache stale/ausente — baixando full history CSV...")
        CLEV_CSV.parent.mkdir(parents=True, exist_ok=True)
        url = "https://www.clevelandfed.org/-/media/files/webcharts/medianpce/median-pce-full-history.csv"
        CLEV_CSV.write_bytes(_curl_get(url, timeout=60))
    df = pd.read_csv(CLEV_CSV)
    df.columns = ["date", "ann_1mo_raw", "ann_12mo"]  # MoM% / YoY% direto
    df["date"] = pd.to_datetime(df["date"], format="%m/%d/%Y", errors="coerce")
    df = df.dropna(subset=["date"]).copy()
    # 1mo% raw do CSV eh percent change nao-annualized; anualizar
    df["ann_1mo"] = ((1 + pd.to_numeric(df["ann_1mo_raw"], errors="coerce") / 100) ** 12 - 1) * 100
    df["ann_12mo"] = pd.to_numeric(df["ann_12mo"], errors="coerce")
    df["measure"] = "median_pce"
    df["value_index"] = np.nan   # chain centralizado em main()
    return df[["date", "measure", "value_index", "ann_1mo", "ann_12mo"]]


def fetch_dallas_trimmed_mean() -> pd.DataFrame:
    """Dallas Fed Trimmed Mean PCE via FRED (SA):
      - PCETRIM1M158SFRBDAL  = 1-mo annualized %
      - PCETRIM12M159SFRBDAL = 12-mo %
    IDs renomeados em 2026-10 (antigos 680SFRBDAL retornavam 404). Fonte alt:
    xlsx direto em dallasfed.org/-/media/documents/research/pce/pcedata.xlsx
    (nao usado aqui, FRED cobre bem — fallback documentado em TODO.md)."""
    FRED_IDS = {
        "ann_1mo":  "PCETRIM1M158SFRBDAL",
        "ann_12mo": "PCETRIM12M159SFRBDAL",
    }
    frames = []
    for col, fid in FRED_IDS.items():
        s = fetch_fred_csv(fid)
        d = s.rename(col).reset_index()
        frames.append(d)
    # Merge outer: 1mo e 12mo publicados no mesmo mes — tipicamente alinhados.
    merged = frames[0].merge(frames[1], on="date", how="outer").sort_values("date")
    merged["measure"] = "trimmed_mean_pce"
    merged["value_index"] = np.nan
    return merged[["date", "measure", "value_index", "ann_1mo", "ann_12mo"]]


def _chain_index(ann_1mo: pd.Series, base: float = 100.0) -> pd.Series:
    """Chain-from-ann_1mo. idx[0]=base; idx[t]=idx[t-1]*(1+mom[t]) com
    mom = (1+ann_1mo/100)^(1/12)-1. NaN propaga como fator 1."""
    mom = (1 + ann_1mo / 100) ** (1 / 12) - 1
    factor = (1 + mom.fillna(0)).cumprod()
    return base * factor


def _rebase_jan2000(df: pd.DataFrame) -> pd.DataFrame:
    """Rebase value_index pra Jan/2000=100 por measure. Fallback primeira obs."""
    base_dt = pd.Timestamp("2000-01-01")
    out = []
    for measure, g in df.groupby("measure"):
        g = g.sort_values("date").copy()
        notnull = g.dropna(subset=["value_index"])
        if notnull.empty:
            out.append(g); continue
        hit = notnull[notnull["date"] == base_dt]
        base = float(hit["value_index"].iloc[0]) if not hit.empty else float(notnull["value_index"].iloc[0])
        g["value_index"] = g["value_index"] / base * 100.0
        out.append(g)
    return pd.concat(out, ignore_index=True)


def main() -> None:
    all_rows = []

    # 1. Cleveland Median PCE
    print("[1] Cleveland Fed Median PCE (CSV publico)...")
    try:
        clev = fetch_cleveland_median_pce()
        n = clev.dropna(subset=["ann_12mo"]).shape[0]
        print(f"  median_pce: {n} obs YoY, {clev.date.min().date()} -> {clev.date.max().date()}")
        all_rows.append(clev)
    except Exception as e:
        print(f"  [FAIL] Cleveland: {e}")

    # 2. Dallas Trimmed Mean PCE
    if os.environ.get("SKIP_DALLAS") != "1":
        print("[2] Dallas Fed Trimmed Mean PCE (FRED)...")
        try:
            dal = fetch_dallas_trimmed_mean()
            n = dal.dropna(subset=["ann_1mo"]).shape[0]
            print(f"  trimmed_mean_pce: {n} obs 1mo, {dal.date.min().date()} -> {dal.date.max().date()}")
            all_rows.append(dal)
        except Exception as e:
            print(f"  [FAIL FRED Dallas] {str(e)[:200]}")

    if not all_rows:
        sys.exit("[FAIL] nenhuma series obtida — todas as fontes falharam.")

    out = pd.concat(all_rows, ignore_index=True)
    # Consolida (measure, date). Fontes nao se sobrepoem em PCE (1 fonte por
    # measure), mas groupby.max e NaN-safe se um dia houver fallback.
    out = (out.groupby(["measure", "date"], as_index=False)
              .agg({"value_index": "max", "ann_1mo": "max", "ann_12mo": "max"}))
    out["mom_sa"] = ((1 + out["ann_1mo"] / 100) ** (1 / 12) - 1) * 100

    # Chain universal de ann_1mo (Cleveland + Dallas publicam ann_1mo SA).
    pieces = []
    for measure, g in out.groupby("measure"):
        g = g.sort_values("date").reset_index(drop=True).copy()
        if g["value_index"].isna().all():
            g["value_index"] = _chain_index(g["ann_1mo"]).values
        pieces.append(g)
    out = pd.concat(pieces, ignore_index=True)
    out = _rebase_jan2000(out)
    out = out.sort_values(["measure", "date"]).reset_index(drop=True)
    out = out[["date", "measure", "value_index", "ann_1mo", "mom_sa", "ann_12mo"]]

    # Guard contra regressao silenciosa (padrao CPI 2026-10-28). 2 modos:
    #  (A) measure ausente — fonte morreu, sem cache cobrindo.
    #  (B) measure sem ann_1mo — chain-source caiu, value_index vira flat=100.
    expected = EXPECTED_MEASURES.copy()
    if os.environ.get("SKIP_DALLAS") == "1":
        expected.discard("trimmed_mean_pce")
    got = set(out["measure"].unique())
    missing = expected - got
    bad_chain = sorted(
        m for m in (expected & got)
        if out[(out["measure"] == m) & out["ann_1mo"].notna()].empty
    )
    if missing or bad_chain:
        if missing:
            print(f"\n[FAIL] {len(missing)}/{len(expected)} measures ausentes: {sorted(missing)}")
        if bad_chain:
            print(f"\n[FAIL] {len(bad_chain)} measures sem ann_1mo (chain gera "
                  f"value_index flat=100): {bad_chain}")
        partial = OUT_CSV.with_suffix(".partial.csv")
        OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
        out.to_csv(partial, index=False)
        print(f"  {len(out)} rows salvos em {partial.name} (debug). CSV principal "
              f"{OUT_CSV.name} NAO foi sobrescrito.")
        if OUT_CSV.exists():
            try:
                prev_rows = sum(1 for _ in OUT_CSV.open()) - 1
                print(f"  CSV principal preservado com {prev_rows} rows de run anterior.")
            except Exception:
                pass
        print(f"  Checar proxy/rede nas fontes faltantes e re-rodar.")
        sys.exit(2)

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT_CSV, index=False)
    print(f"\n[OK] {len(out)} rows -> {OUT_CSV.relative_to(ROOT)}")

    s = out.groupby("measure").agg(
        n_idx=("value_index", lambda x: x.notna().sum()),
        n_1mo=("ann_1mo", lambda x: x.notna().sum()),
        n_12mo=("ann_12mo", lambda x: x.notna().sum()),
        idx_jan2000=("value_index", lambda x: round(x.iloc[(out.loc[x.index, "date"] - pd.Timestamp("2000-01-01")).abs().argmin()], 2) if x.notna().any() else None),
        min_date=("date", "min"),
        max_date=("date", "max"),
    )
    print(f"\nSummary:")
    print(s.to_string())


if __name__ == "__main__":
    main()
