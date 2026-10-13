#!/usr/bin/env python3
# build_breadth_cpi.py
#
# Inflation breadth CPI-U — distribuição de pesos cross-section em 3 bins
# de YoY (12-mo % change) por subitem:
#
#   above_3pct   : Σ w_i onde YoY_i > 3%
#   0_to_3pct    : Σ w_i onde 0 <= YoY_i <= 3%
#   below_0pct   : Σ w_i onde YoY_i < 0%
#
# Universe: ~177 subitem leaves da hierarquia BLS Table 1 (mesmo universe
# usado em build_alt_measures_cpi.py pros customs bottom-up — infra
# compartilhada via cache cpi_cpius_subitem_sa_raw.csv).
#
# Pesos: time-varying da RI subitem (`cpi_cpius_pesos_annual_subitem.csv`,
# RI Dez do ano anterior ao mês). Renormalizado pra 100% em cada mês
# considerando só subitens com YoY valido naquele mês.
#
# Soma dos 3 bins = 100% em cada mês (sanity automatica no output).
#
# Uso:
#   cd pareto_cpius
#   python scripts/build_breadth_cpi.py
#
# Env:
#   BLS_API_KEY (fallback — so se cache nao existir)
#   CORP_PROXY_URL (opcional)
#   FORCE_FETCH=1 (ignora cache, re-baixa BLS)

from __future__ import annotations

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
RAW_CACHE = ROOT / "data" / "cpi_cpius_subitem_sa_raw.csv"
OUT_CSV = ROOT / "data" / "cpi_cpius_breadth.csv"

BLS_URL = "https://api.bls.gov/publicAPI/v2/timeseries/data/"
BLS_KEY = os.environ.get("BLS_API_KEY", "")
BATCH = 50 if BLS_KEY else 25
YEAR_STRIDE = 20
START_YEAR = 2000

# Proxy: respeita HTTP_PROXY/HTTPS_PROXY do ambiente corp (ja setados).
# CORP_PROXY_URL fica como override opcional. Shell-out curl pq urllib tem
# bug conhecido no CONNECT-auth (407) com proxy Basic-auth do Itau.
_PROXY_URL = (
    os.environ.get("CORP_PROXY_URL")
    or os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    or os.environ.get("HTTP_PROXY")  or os.environ.get("http_proxy")
    or None
)


# ----- Fetch helpers (fallback se cache ausente) ----------------------------

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
    """Fetcha SA (CUSR) + fallback NSA (CUUR) pros subitem leaves."""
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
    """STL multiplicativa (log) pros NSA; passthrough pros SA."""
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


# ----- Breadth logic --------------------------------------------------------

def compute_breadth(df_sa: pd.DataFrame, df_wgt: pd.DataFrame) -> pd.DataFrame:
    """3-bin breadth ponderado por peso subitem.

    df_sa: date, item_code, value_index (SA mix pos-STL)
    df_wgt: year, item_code, cpi_u (RI Dez do ano)

    Retorna long df: date, bin, weight_share. bin ∈ {above_3pct, 0_to_3pct, below_0pct}.
    Soma dos 3 bins = 100.0 por date (renormalizada entre items com YoY valido).
    """
    df = df_sa.sort_values(["item_code", "date"]).copy()
    df["yoy"] = df.groupby("item_code")["value_index"].pct_change(12) * 100
    # Peso = RI Dez do ano anterior
    df["year_for_weight"] = df["date"].dt.year - 1
    w = df_wgt.rename(columns={"year": "year_for_weight", "cpi_u": "weight"})[
        ["year_for_weight", "item_code", "weight"]
    ]
    df = df.merge(w, on=["year_for_weight", "item_code"], how="inner")
    df = df.dropna(subset=["yoy"])

    def _bin(y: float) -> str:
        if y > 3.0:
            return "above_3pct"
        if y < 0.0:
            return "below_0pct"
        return "0_to_3pct"
    df["bin"] = df["yoy"].apply(_bin)

    # Soma peso por (date, bin), renormaliza pra 100 por date
    by = df.groupby(["date", "bin"])["weight"].sum().reset_index()
    tot = df.groupby("date")["weight"].sum().rename("total")
    by = by.merge(tot, on="date")
    by["weight_share"] = by["weight"] / by["total"] * 100.0

    # Garante que os 3 bins apareçam em toda data (0 se ausente)
    all_bins = ["above_3pct", "0_to_3pct", "below_0pct"]
    idx = pd.MultiIndex.from_product(
        [by["date"].unique(), all_bins], names=["date", "bin"],
    )
    out = (by.set_index(["date", "bin"])["weight_share"]
             .reindex(idx, fill_value=0.0)
             .reset_index())

    # Sanity: soma = 100 ± epsilon
    sanity = out.groupby("date")["weight_share"].sum()
    bad = sanity[(sanity - 100).abs() > 0.01]
    if not bad.empty:
        print(f"[WARN] {len(bad)} datas com soma ≠ 100 (max desvio: {(sanity-100).abs().max():.4f}pp)")

    return out.sort_values(["date", "bin"]).reset_index(drop=True)


# ----- Main -----------------------------------------------------------------

def main() -> None:
    if not HIER_CSV.exists():
        sys.exit(f"[FAIL] {HIER_CSV} nao existe — rode build_subitem_hierarchy.py primeiro")
    if not PESOS_CSV.exists():
        sys.exit(f"[FAIL] {PESOS_CSV} nao existe — rode parse_historical_ri_subitem.py primeiro")

    hier = pd.read_csv(HIER_CSV)
    pesos = pd.read_csv(PESOS_CSV)

    year_latest = int(hier.year.max())
    leaves = hier[(hier.year == year_latest) & (hier.is_leaf == 1)]
    codes = sorted(leaves.item_code.unique().tolist())
    print(f"[1] Leaves em {year_latest}: {len(codes)}  (soma pesos: {leaves.cpi_u.sum():.3f})")

    # Cache SA/NSA raw (compartilhado com build_alt_measures_cpi.py)
    if RAW_CACHE.exists() and os.environ.get("FORCE_FETCH") != "1":
        print(f"[2] Lendo cache {RAW_CACHE.name} (FORCE_FETCH=1 pra re-baixar)")
        raw = pd.read_csv(RAW_CACHE, parse_dates=["date"])
    else:
        raw = _fetch_leaves(codes)
        RAW_CACHE.parent.mkdir(parents=True, exist_ok=True)
        raw.to_csv(RAW_CACHE, index=False)
        print(f"[2] Salvo em {RAW_CACHE.name}: {len(raw)} rows")

    # Checa que todos os codes do universe estao no cache; se nao, re-fetch
    cached = set(raw["item_code"].unique())
    missing = [c for c in codes if c not in cached]
    if missing:
        print(f"[2b] {len(missing)} codes faltam no cache — fetch adicional")
        extra = _fetch_leaves(missing)
        raw = pd.concat([raw, extra], ignore_index=True)
        raw.to_csv(RAW_CACHE, index=False)

    # Filtra pros leaves atuais apenas
    raw = raw[raw["item_code"].isin(codes)].copy()

    # STL deseasonalize pros NSA
    print(f"[3] STL dessaz NSA fallbacks...")
    raw = _deseasonalize_nsa(raw)
    cov = raw.groupby("item_code")["sa_flag"].first().value_counts().to_dict()
    print(f"    cobertura: {cov}")

    # Breadth
    print(f"[4] Breadth 3-bin (>3%, [0,3], <0%)...")
    breadth = compute_breadth(raw, pesos)
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    breadth.to_csv(OUT_CSV, index=False)
    print(f"[5] Salvo em {OUT_CSV.name}: {len(breadth)} rows")
    print(f"    janela: {breadth.date.min().date()} -> {breadth.date.max().date()}")

    # Preview últimos 6 meses
    print("\n[preview] Ultimos 6 meses:")
    piv = (breadth[breadth.date >= breadth.date.max() - pd.DateOffset(months=5)]
           .pivot(index="date", columns="bin", values="weight_share")
           .round(2))
    print(piv.to_string())
    print(f"\n    sanity: soma dos 3 bins = {piv.sum(axis=1).mean():.4f} (esperado 100.00)")


if __name__ == "__main__":
    main()
