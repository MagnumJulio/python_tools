#!/usr/bin/env python3
# build_pce_categorias.py
#
# Monta as categorias "chefe" PCE pro SQL corp — analogo ao `pareto_cpius`
# (fetch_bls_cpiu.R + build_custom_aggregations.R combinados).
#
# Fontes:
#   - U20404 (price indexes SA) ja em data/pce_indices_raw.csv
#   - U20405 (nominais USD) ja em data/pce_nominais_raw.csv
#   - Mapping bea_maps/pce_categorias.csv — 32+ categorias:
#       - method='direct'  -> line_number aponta pra agregacao ja publicada BEA
#       - method='exclude' -> aplica algebra Laspeyres: var_cat = (var_base*w_base
#                             - sum(var_i*w_i)) / (w_base - sum(w_i)) sobre
#                             line_number (base) e recipe (lista de lines, +).
#
# Convencoes alinhadas com pareto_cpius:
#   - value_index SA, rebase Jan/2000=100
#   - Weight = share do nominal mensal (nominal_cat / nominal_all_items * 100)
#   - headline Weight = 100.0 fixo (nao renormalizado)
#
# Outputs:
#   data/pce_categorias_indice.csv  — long: date, cat, value_index
#   data/pce_categorias_pesos.csv   — long: date, cat, weight (%)
#
# Uso:
#   cd pareto_pce
#   python scripts/build_pce_categorias.py

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
IN_PRICES   = ROOT / "data" / "pce_indices_raw.csv"
IN_NOMINAIS = ROOT / "data" / "pce_nominais_raw.csv"
MAP_CSV     = ROOT / "scripts" / "bea_maps" / "pce_categorias.csv"

OUT_IDX   = ROOT / "data" / "pce_categorias_indice.csv"
OUT_PESOS = ROOT / "data" / "pce_categorias_pesos.csv"


def _rebase_jan2000(df: pd.DataFrame, col: str = "value_index") -> pd.DataFrame:
    """Rebase col pra Jan/2000=100 por categoria."""
    base_dt = pd.Timestamp("2000-01-01")
    pieces = []
    for cat, g in df.groupby("cat"):
        g = g.sort_values("date").copy()
        notnull = g.dropna(subset=[col])
        if notnull.empty:
            pieces.append(g); continue
        hit = notnull[notnull["date"] == base_dt]
        base = float(hit[col].iloc[0]) if not hit.empty else float(notnull[col].iloc[0])
        g[col] = g[col] / base * 100.0
        pieces.append(g)
    return pd.concat(pieces, ignore_index=True)


def _chain_from_mom_pct(mom_pct: pd.Series, base: float = 100.0) -> pd.Series:
    """idx[0]=base; idx[t]=idx[t-1]*(1+mom[t]/100). NaN propaga como fator 1."""
    factor = (1 + mom_pct.fillna(0) / 100).cumprod()
    return base * factor


def compute_direct(df_prices: pd.DataFrame, line_number: int) -> pd.DataFrame:
    """Pega value_index e MoM% direto de uma line do U20404 (ja SA)."""
    g = df_prices[df_prices["line_number"] == line_number].sort_values("date").copy()
    g["value_index"] = g["value"]
    g["mom_pct"] = g["value"].pct_change() * 100
    return g[["date", "value_index", "mom_pct"]]


def compute_exclude(
    df_prices: pd.DataFrame,
    df_nominais: pd.DataFrame,
    base_line: int,
    exclude_lines: list[int],
) -> pd.DataFrame:
    """Agregacao custom via algebra Laspeyres:

        var_cat(m) = (var_base*w_base - sum(var_i*w_i)) / (w_base - sum(w_i))

    com peso mensal = nominal do mes. Index derivado via chain de var_cat.
    Peso derivado: w_cat(m) = w_base(m) - sum(w_i(m)).
    """
    all_lines = [base_line] + exclude_lines

    # MoM% por line (U20404 ja SA)
    px = df_prices[df_prices["line_number"].isin(all_lines)].sort_values(["line_number", "date"]).copy()
    px["mom_pct"] = px.groupby("line_number")["value"].pct_change() * 100

    # Pesos nominais do mes
    nm = df_nominais[df_nominais["line_number"].isin(all_lines)][["date", "line_number", "value"]]
    nm = nm.rename(columns={"value": "nominal"})

    # Merge wide: pra cada data, 1 row por line
    long = px[["date", "line_number", "mom_pct"]].merge(nm, on=["date", "line_number"], how="inner")
    long = long.dropna(subset=["mom_pct", "nominal"])

    # Pivot wide: 1 col por line (mom + nominal)
    rows = []
    for d, g in long.groupby("date"):
        g = g.set_index("line_number")
        if base_line not in g.index:
            continue
        if not all(l in g.index for l in exclude_lines):
            continue
        mom_base = g.loc[base_line, "mom_pct"]
        w_base   = g.loc[base_line, "nominal"]
        mom_excl = g.loc[exclude_lines, "mom_pct"]
        w_excl   = g.loc[exclude_lines, "nominal"]
        w_cat = w_base - w_excl.sum()
        if w_cat <= 0:
            continue
        mom_cat = (mom_base * w_base - (mom_excl * w_excl).sum()) / w_cat
        rows.append({"date": d, "mom_pct": mom_cat, "nominal": w_cat})
    out = pd.DataFrame(rows).sort_values("date").reset_index(drop=True)
    # Chain pro value_index (base 100 arbitrario — rebase final cuida)
    out["value_index"] = _chain_from_mom_pct(out["mom_pct"]).values
    return out[["date", "value_index", "mom_pct", "nominal"]]


def main() -> None:
    for p in (IN_PRICES, IN_NOMINAIS, MAP_CSV):
        if not p.exists():
            sys.exit(f"[FAIL] {p} nao existe.")

    px = pd.read_csv(IN_PRICES, parse_dates=["date"])
    nm = pd.read_csv(IN_NOMINAIS, parse_dates=["date"])
    mp = pd.read_csv(MAP_CSV)
    print(f"[1] prices: {len(px)} rows, nominais: {len(nm)} rows, map: {len(mp)} cats")

    # Nominal do headline (line 1) pra calcular weight share
    hl = nm[nm["line_number"] == 1][["date", "value"]].rename(columns={"value": "nominal_all"})

    idx_rows = []
    pesos_rows = []

    for _, row in mp.iterrows():
        slug = row["slug"]
        method = row["method"]
        if method == "direct":
            line = int(row["line_number"])
            df = compute_direct(px, line)
            # Nominal do proprio line pra peso
            nom = nm[nm["line_number"] == line][["date", "value"]].rename(columns={"value": "nominal_cat"})
        elif method == "exclude":
            base = int(row["line_number"])
            excludes = [int(x) for x in row["recipe"].split("+")]
            df = compute_exclude(px, nm, base, excludes)
            # Nominal = w_cat ja computado (sai como 'nominal' no compute_exclude)
            nom = df[["date", "value_index"]].copy()  # placeholder
            # Pra evitar re-computar: compute_exclude ja retorna nominal
            # Vou reconstruir usando resultados do compute_exclude:
            tmp = compute_exclude(px, nm, base, excludes)
            nom = tmp[["date"]].copy()
            nom["nominal_cat"] = tmp["nominal"] if "nominal" in tmp.columns else None
        else:
            print(f"  [SKIP] slug={slug}: method={method} nao suportado")
            continue

        if df.empty:
            print(f"  [SKIP] slug={slug}: sem dados")
            continue

        df["cat"] = slug
        idx_rows.append(df[["date", "cat", "value_index"]])

        # Peso: share do nominal mensal vs headline (all_items weight = 100 forcado)
        if slug == "all_items":
            # headline fixo 100.0
            w = df[["date"]].copy()
            w["cat"] = slug
            w["weight"] = 100.0
        else:
            w = nom.merge(hl, on="date", how="inner")
            w["weight"] = w["nominal_cat"] / w["nominal_all"] * 100.0
            w["cat"] = slug
            w = w[["date", "cat", "weight"]]
        pesos_rows.append(w)

    idx = pd.concat(idx_rows, ignore_index=True)
    pesos = pd.concat(pesos_rows, ignore_index=True)

    # Rebase Jan/2000=100 pros customs tambem (directs ja estao em base BEA; mas
    # vamos padronizar: todas rebase pra Jan/2000=100)
    idx = _rebase_jan2000(idx, "value_index")

    idx = idx.sort_values(["cat", "date"]).reset_index(drop=True)
    pesos = pesos.sort_values(["cat", "date"]).reset_index(drop=True)

    OUT_IDX.parent.mkdir(parents=True, exist_ok=True)
    idx.to_csv(OUT_IDX, index=False)
    pesos.to_csv(OUT_PESOS, index=False)
    print(f"[2] indice -> {OUT_IDX.name}: {len(idx)} rows")
    print(f"    pesos  -> {OUT_PESOS.name}: {len(pesos)} rows")

    # Preview last month: value_index + MoM% derivado + weight
    last = idx["date"].max()
    print(f"\n[preview] {last:%Y-%m}:")
    piv = idx[idx["date"] == last].set_index("cat")["value_index"].round(3)
    mom_rows = []
    for cat, g in idx.groupby("cat"):
        g = g.sort_values("date")
        if len(g) < 2:
            continue
        mom = (g["value_index"].iloc[-1] / g["value_index"].iloc[-2] - 1) * 100
        mom_rows.append({"cat": cat, "mom_pct": mom})
    mom_df = pd.DataFrame(mom_rows).set_index("cat")
    w_last = pesos[pesos["date"] == pesos["date"].max()].set_index("cat")["weight"].round(2)
    merged = pd.concat([w_last, piv, mom_df["mom_pct"].round(3)], axis=1)
    merged.columns = ["weight", "idx", "mom_%"]
    merged = merged.reindex(index=idx["cat"].drop_duplicates().tolist())
    print(merged.to_string())


if __name__ == "__main__":
    main()
