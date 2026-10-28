#!/usr/bin/env python3
# build_altas_distribution_pce.py
#
# Distribuicao de altas PCE — share do peso em 5 bins de MoM SAAR
# por leaf, estilo Dallas Fed (`pcedata.xlsx`):
#
#   0_to_2    : (0%, 2%]
#   2_to_3    : (2%, 3%]
#   3_to_5    : (3%, 5%]
#   5_to_10   : (5%, 10%]
#   gt_10     : > 10%
#
# Headline only (nao decompoe Goods/Services) — Dallas tambem so publica
# a distribuicao Headline.
#
# Universe: 190 leaves do BEA U20404 (mesmo do breadth + diffusion).
# Peso: nominais BEA U20405 (current dollars) do proprio mes.
# MoM SAAR: ((idx[t]/idx[t-1])^12 - 1) * 100 — U20404 ja e SA, confirmado
# pelo pattern mensal uniforme (medias Jan..Dez 2010-2026 entre 0.14% e
# 0.24%, sem spike de dezembro).
#
# Soma dos 5 bins + share(below_0_or_flat_mom_saar) = 100% por data.
# Dallas publica so os 5 positivos; o "complemento" (deflationary) nao
# aparece no `pcedata.xlsx` deles mas sai da soma.
#
# Prerequisitos:
#   1. scripts/fetch_pce.py       -> pce_indices_raw.csv + pce_nominais_raw.csv
#   2. scripts/build_diffusion.py -> leaves_detected.csv
#
# Benchmark: Dallas pcedata.xlsx (data/raw/dallas/) — mesma metrica, mesmas
# bins, universe diferente (Trimmed Mean components). Dessa vez a correlacao
# por bin deve ser alta (diferenca so no universe, nao na metrica).
#
# Uso:
#   cd pareto_pce
#   python scripts/build_altas_distribution_pce.py

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
IN_PRICES   = ROOT / "data" / "pce_indices_raw.csv"
IN_NOMINAIS = ROOT / "data" / "pce_nominais_raw.csv"
LEAVES_CSV  = ROOT / "data" / "leaves_detected.csv"
OUT_CSV     = ROOT / "data" / "pce_altas_distribution.csv"

COVERAGE_THRESHOLD_PCT = 70.0

# 5 bins Dallas-style — tudo em MoM SAAR %.
BIN_EDGES = [
    ("0_to_2",  0.0,  2.0),
    ("2_to_3",  2.0,  3.0),
    ("3_to_5",  3.0,  5.0),
    ("5_to_10", 5.0, 10.0),
    ("gt_10",  10.0, float("inf")),
]
# Bin opcional pra deflationary / flat (nao vai pro SQL, so sai no CSV
# e no sanity check). "zero_or_below" cobre MoM SAAR <= 0.
BIN_BELOW = "zero_or_below"
ALL_BINS = [b[0] for b in BIN_EDGES] + [BIN_BELOW]


def _assign_bin(saar: float) -> str:
    if pd.isna(saar):
        return "nan"
    if saar <= 0.0:
        return BIN_BELOW
    for name, lo, hi in BIN_EDGES:
        if lo < saar <= hi:
            return name
    return "nan"   # defensive


def compute_distribution(df_prices: pd.DataFrame, df_nominais: pd.DataFrame,
                         leaves: pd.DataFrame) -> pd.DataFrame:
    """Distribution ponderada por nominais, 5 bins Dallas + 1 bin complemento."""
    leaf_lines = set(leaves["line_number"].astype(int))
    px = df_prices[df_prices["line_number"].isin(leaf_lines)].copy()
    nm = df_nominais[df_nominais["line_number"].isin(leaf_lines)].copy()

    # MoM SAAR por leaf — U20404 e SA, chain = (idx[t]/idx[t-1])^12 - 1.
    px = px.sort_values(["line_number", "date"])
    px["mom_saar"] = (px.groupby("line_number")["value"]
                       .transform(lambda s: ((s / s.shift(1)) ** 12 - 1) * 100))

    nm = nm.rename(columns={"value": "nominal"})

    df = px[["date", "line_number", "mom_saar"]].merge(
        nm[["date", "line_number", "nominal"]],
        on=["date", "line_number"], how="inner",
    )
    df = df.dropna(subset=["mom_saar", "nominal"])

    # Guard de cobertura (release parcial descartado)
    total_nominal_per_date = nm.groupby("date")["nominal"].sum().rename("total_nom")
    df = df.merge(total_nominal_per_date, left_on="date", right_index=True)
    df["coverage_pct"] = df.groupby("date")["nominal"].transform("sum") / df["total_nom"] * 100
    low_cov = df[df["coverage_pct"] < COVERAGE_THRESHOLD_PCT]["date"].unique()
    if len(low_cov) > 0:
        for d in sorted(low_cov):
            c = df[df["date"] == d]["coverage_pct"].iloc[0]
            print(f"[WARN] {pd.Timestamp(d).date()}: cobertura {c:.1f}% < "
                  f"{COVERAGE_THRESHOLD_PCT}% — descartada")
        df = df[~df["date"].isin(low_cov)]

    df["bin"] = df["mom_saar"].apply(_assign_bin)

    # Soma peso por (date, bin), renormaliza pra 100 por date entre leaves com
    # mom_saar valido. Inclui o bin complemento (zero_or_below) na soma.
    by = df.groupby(["date", "bin"])["nominal"].sum().reset_index()
    tot = df.groupby("date")["nominal"].sum().rename("total")
    by = by.merge(tot, on="date")
    by["weight_share"] = by["nominal"] / by["total"] * 100.0

    idx = pd.MultiIndex.from_product(
        [by["date"].unique(), ALL_BINS], names=["date", "bin"],
    )
    out = (by.set_index(["date", "bin"])["weight_share"]
             .reindex(idx, fill_value=0.0)
             .reset_index())

    sanity = out.groupby("date")["weight_share"].sum()
    bad = sanity[(sanity - 100).abs() > 0.01]
    if not bad.empty:
        print(f"[WARN] {len(bad)} datas com soma ≠ 100 "
              f"(max desvio: {(sanity-100).abs().max():.4f}pp)")

    return out.sort_values(["date", "bin"]).reset_index(drop=True)


def main() -> None:
    for p in (IN_PRICES, IN_NOMINAIS):
        if not p.exists():
            sys.exit(f"[FAIL] {p} nao existe — rode scripts/fetch_pce.py primeiro.")
    if not LEAVES_CSV.exists():
        sys.exit(f"[FAIL] {LEAVES_CSV} nao existe — rode scripts/build_diffusion.py primeiro.")

    px = pd.read_csv(IN_PRICES, parse_dates=["date"])
    nm = pd.read_csv(IN_NOMINAIS, parse_dates=["date"])
    leaves = pd.read_csv(LEAVES_CSV)
    print(f"[1] prices: {len(px)} rows, nominais: {len(nm)} rows, "
          f"leaves: {len(leaves)}")

    print(f"[2] MoM SAAR + 5 bins (0-2, 2-3, 3-5, 5-10, >10) + zero_or_below...")
    dist = compute_distribution(px, nm, leaves)
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    dist.to_csv(OUT_CSV, index=False)
    print(f"[3] Salvo em {OUT_CSV.name}: {len(dist)} rows")
    print(f"    janela: {dist.date.min().date()} -> {dist.date.max().date()}")

    # Preview ultimos 6 meses (soma 5 bins Dallas + bin complemento)
    print("\n[preview] Ultimos 6 meses (todas as bins, soma = 100):")
    piv = (dist[dist.date >= dist.date.max() - pd.DateOffset(months=5)]
           .pivot(index="date", columns="bin", values="weight_share")
           [ALL_BINS]
           .round(2))
    print(piv.to_string())
    print(f"\n    sanity: soma = {piv.sum(axis=1).mean():.4f} (esperado 100.00)")
    print(f"\n[dallas] bins {[b[0] for b in BIN_EDGES]} vao pro SQL; "
          f"'{BIN_BELOW}' fica so no CSV (complemento, nao faz parte do "
          f"pcedata.xlsx Dallas).")


if __name__ == "__main__":
    main()
