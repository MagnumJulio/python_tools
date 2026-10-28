#!/usr/bin/env python3
# build_breadth_pce.py
#
# Inflation breadth PCE — distribuicao de pesos cross-section em 3 bins de
# YoY (12-mo % change) por leaf PCE:
#
#   above_3pct : Σ w_i onde YoY_i > 3%
#   0_to_3pct  : Σ w_i onde 0 <= YoY_i <= 3%
#   below_0pct : Σ w_i onde YoY_i < 0%
#
# Universe: 190 leaves do BEA U20404 (mesma lista usada em build_diffusion.py).
# Pesos time-varying: nominais BEA U20405 (current dollars) do proprio mes —
# peso implicito = nominal_i(m) / Σ_leaves nominal_j(m), 100% por data.
# Analogo ao build_breadth_cpi.py mas com peso BEA em vez de RI Dez.
#
# Soma dos 3 bins = 100% por mes (sanity automatica).
#
# Prerequisitos (ordem):
#   1. scripts/fetch_pce.py       → pce_indices_raw.csv + pce_nominais_raw.csv
#   2. scripts/build_diffusion.py → leaves_detected.csv
#   3. scripts/build_breadth_pce.py (este)
#
# Benchmark de validacao: Dallas Fed publica a mesma metrica em 5 bins no
# pcedata.xlsx (data/raw/dallas/). Nossos 3 bins agregam os 5 Dallas
# (<0% + 0-2% + 2-3% + 3-5% + 5-10% + >10%).
#
# Uso:
#   cd pareto_pce
#   python scripts/build_breadth_pce.py

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
IN_PRICES   = ROOT / "data" / "pce_indices_raw.csv"
IN_NOMINAIS = ROOT / "data" / "pce_nominais_raw.csv"
LEAVES_CSV  = ROOT / "data" / "leaves_detected.csv"
OUT_CSV     = ROOT / "data" / "pce_breadth.csv"

COVERAGE_THRESHOLD_PCT = 70.0


def compute_breadth(df_prices: pd.DataFrame, df_nominais: pd.DataFrame,
                    leaves: pd.DataFrame) -> pd.DataFrame:
    """3-bin breadth ponderado por nominais BEA U20405.

    df_prices:   date, line_number, value (indice de preco U20404)
    df_nominais: date, line_number, value (nominal em bilhoes US$ U20405)
    leaves:      line_number, aggregate, is_car (190 leaves do build_diffusion.py)

    Retorna long df: date, bin, weight_share. Soma dos 3 bins = 100.0 por date.
    Guard de cobertura: datas com soma de peso < 70% sao descartadas (release
    parcial, mesma heuristica do build_diffusion.py linha 265).
    """
    # Filtra pros leaves apenas (190 lines das ~400 do U20404)
    leaf_lines = set(leaves["line_number"].astype(int))
    px = df_prices[df_prices["line_number"].isin(leaf_lines)].copy()
    nm = df_nominais[df_nominais["line_number"].isin(leaf_lines)].copy()

    # YoY por leaf — mesmo pattern do build_diffusion.py
    px = px.sort_values(["line_number", "date"])
    px["yoy"] = px.groupby("line_number")["value"].pct_change(12) * 100

    # Peso implicito do proprio mes (nominal BEA / soma dos leaves)
    # Difere do CPI breadth (que usa RI Dez do ano anterior) porque PCE nao
    # publica RI em arquivo historico — mas nominais sao disponiveis mensais.
    nm = nm.rename(columns={"value": "nominal"})

    df = px[["date", "line_number", "yoy"]].merge(
        nm[["date", "line_number", "nominal"]],
        on=["date", "line_number"], how="inner",
    )
    df = df.dropna(subset=["yoy", "nominal"])

    # Guard de cobertura: soma peso dos leaves valid por data vs total potencial
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

    # Bins (mesma convencao CPI)
    def _bin(y: float) -> str:
        if y > 3.0:
            return "above_3pct"
        if y < 0.0:
            return "below_0pct"
        return "0_to_3pct"
    df["bin"] = df["yoy"].apply(_bin)

    # Soma peso por (date, bin) e renormaliza pra 100% por date (so leaves valid)
    by = df.groupby(["date", "bin"])["nominal"].sum().reset_index()
    tot = df.groupby("date")["nominal"].sum().rename("total")
    by = by.merge(tot, on="date")
    by["weight_share"] = by["nominal"] / by["total"] * 100.0

    all_bins = ["above_3pct", "0_to_3pct", "below_0pct"]
    idx = pd.MultiIndex.from_product(
        [by["date"].unique(), all_bins], names=["date", "bin"],
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
          f"leaves: {len(leaves)} ({leaves['aggregate'].value_counts().to_dict()})")

    print(f"[2] Breadth 3-bin ponderado por nominais BEA U20405...")
    breadth = compute_breadth(px, nm, leaves)
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    breadth.to_csv(OUT_CSV, index=False)
    print(f"[3] Salvo em {OUT_CSV.name}: {len(breadth)} rows")
    print(f"    janela: {breadth.date.min().date()} -> {breadth.date.max().date()}")

    # Preview ultimos 6 meses
    print("\n[preview] Ultimos 6 meses:")
    piv = (breadth[breadth.date >= breadth.date.max() - pd.DateOffset(months=5)]
           .pivot(index="date", columns="bin", values="weight_share")
           [["below_0pct", "0_to_3pct", "above_3pct"]]
           .round(2))
    print(piv.to_string())
    print(f"\n    sanity: soma dos 3 bins = {piv.sum(axis=1).mean():.4f} (esperado 100.00)")


if __name__ == "__main__":
    main()
