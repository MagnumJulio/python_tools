#!/usr/bin/env python3
# build_alt_measures_cpi.py
#
# Medidas alternativas de inflacao CPI-U pra servir no SQL corp.
#
# Estrategia primaria: fetch das series OFICIAIS (match 100% com Fed):
#   - Cleveland Fed Median CPI       (FRED: MEDCPIM158SFRBCLE)
#   - Cleveland Fed Trimmed-Mean CPI (FRED: TRMMEANCPIM158SFRBCLE)
#   - Atlanta Fed Sticky-Price CPI family (xlsx oficial, 6 series)
#
# Custom (bottom-up proprio, nao existe oficial):
#   - Trimmed Symmetric 25% CPI (corta 25% top + 25% cauda, mean do miolo 50%)
#
# Infra bottom-up (fetch SA/NSA leaves + STL + weighted median/trimmed)
# fica como RECONSTRUCAO DEFENSIVA — util pra validar FRED e pra servir se
# FRED cair, mas nao e a serie primaria entregue ao gestor.
#
# Uso:
#   cd pareto_cpius
#   python scripts/build_alt_measures_cpi.py
#
# Env vars:
#   BLS_API_KEY (so pra o custom bottom-up)
#   CORP_PROXY_URL (opcional — corp only)
#   SKIP_CUSTOM=1 (so entrega as 8 oficiais, pula Trimmed Sym 25%)

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from datetime import date
from pathlib import Path
from urllib.request import Request, urlopen

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
HIER_CSV = ROOT / "data" / "cpi_cpius_subitem_hierarchy.csv"
PESOS_CSV = ROOT / "data" / "cpi_cpius_pesos_annual_subitem.csv"
RAW_OUT = ROOT / "data" / "cpi_cpius_subitem_sa_raw.csv"
OUT_DIR = ROOT / "data"
ATLANTA_XLSX = ROOT / "data" / "raw" / "atlanta" / "stickyprice.xlsx"
OUT_CSV = OUT_DIR / "cpi_cpius_alt_measures.csv"

BLS_URL = "https://api.bls.gov/publicAPI/v2/timeseries/data/"
BLS_KEY = os.environ.get("BLS_API_KEY", "")
BATCH = 50 if BLS_KEY else 25
YEAR_STRIDE = 20
START_YEAR = 2000

_PROXY_URL = os.environ.get("CORP_PROXY_URL") or None
if _PROXY_URL:
    os.environ.setdefault("HTTPS_PROXY", _PROXY_URL)


def _curl_get(url: str, timeout: int = 60, retries: int = 3) -> bytes:
    """GET com curl (-L follow redirects). Retry em erro de rede. Robusto
    pra FRED que ocasionalmente timeout no urlopen do Python."""
    last_err = None
    for attempt in range(1, retries + 1):
        cmd = ["curl", "-sL", "-f", "--max-time", str(timeout),
               "-A", "Mozilla/5.0"]
        if _PROXY_URL: cmd += ["-x", _PROXY_URL]
        cmd.append(url)
        try:
            r = subprocess.run(cmd, capture_output=True, timeout=timeout + 10)
        except subprocess.TimeoutExpired as e:
            last_err = f"curl subprocess timeout attempt {attempt}"
            continue
        if r.returncode == 0:
            return r.stdout
        last_err = f"curl rc={r.returncode} attempt {attempt}: {r.stderr.decode()[:200]}"
    raise RuntimeError(last_err)


def fetch_fred_csv(fred_id: str) -> pd.Series:
    """FRED CSV publico. Sem key."""
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={fred_id}"
    buf = io.BytesIO(_curl_get(url))
    df = pd.read_csv(buf)
    df.columns = ["date", "value"]
    df["date"] = pd.to_datetime(df["date"])
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    return df.set_index("date")["value"].dropna()


def fetch_atlanta_sticky() -> pd.DataFrame:
    """Parse xlsx oficial Atlanta Fed, retorna long df com as 6 series
    ja em 1-mo annualized percent change (coluna 2 de cada bloco)."""
    # Baixa se nao tiver localmente
    if not ATLANTA_XLSX.exists():
        print(f"[atlanta] baixando xlsx oficial...")
        ATLANTA_XLSX.parent.mkdir(parents=True, exist_ok=True)
        url = ("https://www.atlantafed.org/-/media/Project/Atlanta/FRBA/Documents/"
               "datafiles/research/inflationproject/stickprice/stickyprice.xlsx")
        ATLANTA_XLSX.write_bytes(_curl_get(url, timeout=120))

    # Layout: linha 0 = headers com 6 blocos de 4 colunas cada (index, 1mo ann, 3mo a.r., 12mo).
    # Primeira coluna = date. Linhas 1+ = data.
    df = pd.read_excel(ATLANTA_XLSX, sheet_name="Data", header=None)
    # Nome dos 6 blocos — ordem no xlsx:
    SERIES_NAMES = [
        "flexible_cpi",
        "core_flexible_cpi",
        "sticky_cpi",
        "core_sticky_cpi",
        "sticky_cpi_ex_shelter",
        "core_sticky_cpi_ex_shelter",
    ]
    # Cada bloco tem 4 cols: Index level, 1-mo ann, 3-mo a.r., 12mo. Pegamos 1-mo ann
    # (coluna de offset +1 dentro de cada bloco de 4, começando no indice 1).
    out_rows = []
    for i, name in enumerate(SERIES_NAMES):
        col_1mo = 1 + i * 4 + 1   # Date = col 0; bloco i começa em col 1+i*4
        col_12mo = 1 + i * 4 + 3
        s = df.iloc[1:, [0, col_1mo, col_12mo]].copy()
        s.columns = ["date", "ann_1mo", "ann_12mo"]
        s["date"] = pd.to_datetime(s["date"], errors="coerce")
        s = s.dropna(subset=["date"])
        s["ann_1mo"] = pd.to_numeric(s["ann_1mo"], errors="coerce")
        s["ann_12mo"] = pd.to_numeric(s["ann_12mo"], errors="coerce")
        s["measure"] = name
        out_rows.append(s)
    return pd.concat(out_rows, ignore_index=True)


# ----- Custom Trimmed Sym 25% (bottom-up, nao oficial) ----------------------

def _post_bls(payload: dict, timeout: int = 120) -> dict:
    body = json.dumps(payload)
    if _PROXY_URL:
        cmd = ["curl", "-x", _PROXY_URL, "-H", "Content-Type: application/json",
               "-d", body, "-s", "-f", "--max-time", str(timeout), BLS_URL]
        r = subprocess.run(cmd, capture_output=True, timeout=timeout + 10)
        if r.returncode != 0:
            raise RuntimeError(f"curl rc={r.returncode}: {r.stderr.decode()[:300]}")
        return json.loads(r.stdout)
    req = Request(BLS_URL, data=body.encode(), headers={"Content-Type": "application/json"})
    with urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def _fetch_bls(series_ids: list[str], y0: int, y1: int) -> dict[str, pd.Series]:
    payload = {"seriesid": series_ids, "startyear": str(y0), "endyear": str(y1)}
    if BLS_KEY:
        payload["registrationkey"] = BLS_KEY
    data = _post_bls(payload)
    out: dict[str, pd.Series] = {}
    for s in data.get("Results", {}).get("series", []):
        rows = s["data"]
        if not rows:
            out[s["seriesID"]] = pd.Series(dtype=float)
            continue
        d = pd.DataFrame(rows)
        d["date"] = pd.to_datetime(d["year"] + "-" + d["period"].str.replace("M", ""))
        d["value"] = pd.to_numeric(d["value"], errors="coerce")
        out[s["seriesID"]] = d.dropna(subset=["value"]).sort_values("date").set_index("date")["value"]
    return out


def _fetch_leaves(codes: list[str]) -> pd.DataFrame:
    """Fetch SA (CUSR) + fallback NSA (CUUR) pros subitens leaves/indent-3."""
    end_year = date.today().year
    def _batch(ids):
        out = {s: pd.Series(dtype=float) for s in ids}
        for i in range(0, len(ids), BATCH):
            b = ids[i:i + BATCH]
            for y0 in range(START_YEAR, end_year + 1, YEAR_STRIDE):
                y1 = min(y0 + YEAR_STRIDE - 1, end_year)
                try:
                    chunk = _fetch_bls(b, y0, y1)
                except Exception as e:
                    print(f"  [WARN] batch {i//BATCH+1} {y0}-{y1}: {e}")
                    continue
                for sid, s in chunk.items():
                    if s.empty:
                        continue
                    out[sid] = pd.concat([x for x in [out[sid], s] if not x.empty]).sort_index()
                    out[sid] = out[sid][~out[sid].index.duplicated(keep="last")]
        return out

    sa_ids = [f"CUSR0000{c}" for c in codes]
    print(f"[fetch] SA (CUSR): {len(sa_ids)} series...")
    sa = _batch(sa_ids)
    missing = [c for c in codes if sa[f"CUSR0000{c}"].empty]
    print(f"[fetch] SA cobertura: {len(codes)-len(missing)}/{len(codes)}")
    nsa = {}
    if missing:
        print(f"[fetch] NSA fallback (CUUR): {len(missing)}...")
        nsa = _batch([f"CUUR0000{c}" for c in missing])

    rows = []
    for c in codes:
        s = sa[f"CUSR0000{c}"]
        if not s.empty:
            for d, v in s.items():
                rows.append({"date": d, "item_code": c, "sa_flag": "SA", "value_index": v})
        else:
            s = nsa.get(f"CUUR0000{c}", pd.Series(dtype=float))
            for d, v in s.items():
                rows.append({"date": d, "item_code": c, "sa_flag": "NSA", "value_index": v})
    return pd.DataFrame(rows)


def _deseasonalize_nsa(df_idx: pd.DataFrame) -> pd.DataFrame:
    from statsmodels.tsa.seasonal import STL
    out = []
    for code, g in df_idx.groupby("item_code"):
        g = g.sort_values("date").reset_index(drop=True)
        if g["sa_flag"].iloc[0] == "SA" or len(g) < 36:
            out.append(g); continue
        s = pd.Series(g["value_index"].values, index=pd.to_datetime(g["date"]))
        if (s <= 0).any():
            out.append(g); continue
        try:
            res = STL(np.log(s), period=12, robust=True).fit()
            sa = np.exp(res.observed - res.seasonal)
            g2 = g.copy()
            g2["value_index"] = sa.values
            g2["sa_flag"] = "SA_local"
            out.append(g2)
        except Exception:
            out.append(g)
    return pd.concat(out, ignore_index=True)


def compute_custom_trimmed_sym25(hier_year: int = 2025) -> pd.DataFrame:
    """Trimmed symmetric 25% CPI: corta 25% top + 25% cauda por peso
    cumulativo, weighted mean do miolo 50%. Custom (sem FRED benchmark).
    Universe: indent-3 nodes do BLS hierarchy (~70, approx Cleveland
    structure)."""
    hier = pd.read_csv(HIER_CSV)
    pesos = pd.read_csv(PESOS_CSV)

    uni = hier[(hier.year == hier_year) & (hier.indent == 3)]
    codes = sorted(uni.item_code.unique().tolist())
    print(f"[custom] universe indent-3 em {hier_year}: {len(codes)}")

    if RAW_OUT.exists() and os.environ.get("FORCE_FETCH") != "1":
        print(f"[custom] cache {RAW_OUT.name} (FORCE_FETCH=1 pra re-baixar)")
        raw = pd.read_csv(RAW_OUT, parse_dates=["date"])
    else:
        raw = _fetch_leaves(codes)
        RAW_OUT.parent.mkdir(parents=True, exist_ok=True)
        raw.to_csv(RAW_OUT, index=False)

    raw = _deseasonalize_nsa(raw)

    df = raw.sort_values(["item_code", "date"]).copy()
    df["mom"] = df.groupby("item_code")["value_index"].pct_change() * 100
    df["ann_mom"] = ((1 + df["mom"] / 100) ** 12 - 1) * 100
    df["year_for_weight"] = df["date"].dt.year - 1
    w = pesos.rename(columns={"year": "year_for_weight", "cpi_u": "weight"})[
        ["year_for_weight", "item_code", "weight"]
    ]
    df = df.merge(w, on=["year_for_weight", "item_code"], how="inner")

    def _trim(g):
        g = g.dropna(subset=["ann_mom"]).sort_values("ann_mom").copy()
        if g.empty: return np.nan
        wtot = g["weight"].sum()
        g["cum"] = g["weight"].cumsum()
        lo_w, hi_w = 0.25 * wtot, 0.75 * wtot
        eff = np.zeros(len(g))
        for i, (_, row) in enumerate(g.iterrows()):
            cp = row["cum"] - row["weight"]
            lo = max(cp, lo_w); hi = min(row["cum"], hi_w)
            if hi > lo: eff[i] = hi - lo
        ws = eff.sum()
        return (eff * g["ann_mom"].values).sum() / ws if ws > 0 else np.nan

    out = df.groupby("date", group_keys=False).apply(_trim).rename("ann_1mo").reset_index()
    out["measure"] = "trimmed_sym_25_cpi_custom"
    out["ann_12mo"] = np.nan
    return out[["date", "measure", "ann_1mo", "ann_12mo"]]


def fetch_cleveland_cpi_chartdata() -> pd.DataFrame:
    """Cleveland Fed Median CPI + Trimmed Mean CPI direto do CSV publico
    (chartdata, YoY, ~10 anos). Fonte primaria quando FRED esta indisponivel."""
    csv_path = ROOT / "data" / "raw" / "cleveland" / "cpi_mediancpi_chartdata.csv"
    if not csv_path.exists():
        url = "https://www.clevelandfed.org/-/media/files/webcharts/mediancpi/mediancpi_chartdata.csv"
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        csv_path.write_bytes(_curl_get(url, timeout=60))
    df = pd.read_csv(csv_path, parse_dates=["date"])
    # cols: date, mediancpi, trimmedmeancpi, cpi, corecpi — valores em % YoY
    out_rows = []
    for col, measure in [("mediancpi", "median_cpi"),
                         ("trimmedmeancpi", "trimmed_mean_16_cpi")]:
        s = df[["date", col]].rename(columns={col: "ann_12mo"}).copy()
        s["measure"] = measure
        s["ann_1mo"] = np.nan   # Cleveland chartdata nao expoe 1-mo ann
        out_rows.append(s[["date", "measure", "ann_1mo", "ann_12mo"]])
    return pd.concat(out_rows, ignore_index=True)


def main() -> None:
    all_rows = []

    # 1a. FRED (primary quando acessivel) — Cleveland Median + Trimmed 16%,
    #     1-mo annualized full history (1983+).
    print("[1a] FRED Cleveland Median + Trimmed (1-mo annualized)...")
    fred_ok = {}
    for mname, fred_id in [("median_cpi", "MEDCPIM158SFRBCLE"),
                           ("trimmed_mean_16_cpi", "TRMMEANCPIM158SFRBCLE")]:
        try:
            s = fetch_fred_csv(fred_id)
            df = s.rename("ann_1mo").reset_index()
            df["measure"] = mname
            df["ann_12mo"] = np.nan
            all_rows.append(df[["date", "measure", "ann_1mo", "ann_12mo"]])
            fred_ok[mname] = True
            print(f"  {mname}: {len(df)} obs, {df.date.min().date()} -> {df.date.max().date()}")
        except Exception as e:
            print(f"  [FAIL FRED] {mname}: {str(e)[:120]}")

    # 1b. Fallback Cleveland chartdata (YoY, 10yr) pros que FRED falhou.
    if len(fred_ok) < 2:
        print("[1b] Cleveland chartdata fallback (YoY, ~10 anos)...")
        try:
            cle = fetch_cleveland_cpi_chartdata()
            for m in cle["measure"].unique():
                if m in fred_ok:
                    continue
                sub = cle[cle["measure"] == m]
                all_rows.append(sub)
                print(f"  {m}: {len(sub)} obs YoY, {sub.date.min().date()} -> {sub.date.max().date()}")
        except Exception as e:
            print(f"  [FAIL Cleveland] {e}")

    # 2. Atlanta Fed xlsx — 6 series Sticky/Flexible (ann_1mo + ann_12mo)
    print("[2] Atlanta Fed Sticky/Flexible (xlsx oficial)...")
    try:
        at = fetch_atlanta_sticky()
        for name in at["measure"].unique():
            sub = at[at["measure"] == name][["date", "measure", "ann_1mo", "ann_12mo"]].copy()
            all_rows.append(sub)
            n = len(sub.dropna(subset=["ann_1mo"]))
            print(f"  {name}: {n} obs, {sub.date.min().date()} -> {sub.date.max().date()}")
    except Exception as e:
        print(f"  [FAIL] Atlanta: {e}")

    # 3. Custom bottom-up — Trimmed Sym 25%
    if os.environ.get("SKIP_CUSTOM") != "1":
        print("[3] Custom Trimmed Sym 25% (bottom-up)...")
        try:
            tsm25 = compute_custom_trimmed_sym25()
            all_rows.append(tsm25)
            print(f"  trimmed_sym_25_cpi_custom: {len(tsm25)} obs")
        except Exception as e:
            print(f"  [FAIL] custom: {e}")

    # 4. Consolida + salva
    out = pd.concat(all_rows, ignore_index=True)
    out = out.sort_values(["measure", "date"]).reset_index(drop=True)
    out.to_csv(OUT_CSV, index=False)
    print(f"\n[OK] {len(out)} rows -> {OUT_CSV.relative_to(ROOT)}")
    print(f"\nSummary por measure:")
    s = out.groupby("measure").agg(
        n_1mo=("ann_1mo", lambda x: x.notna().sum()),
        n_12mo=("ann_12mo", lambda x: x.notna().sum()),
        min_date=("date", "min"),
        max_date=("date", "max"),
    )
    print(s.to_string())


if __name__ == "__main__":
    main()
