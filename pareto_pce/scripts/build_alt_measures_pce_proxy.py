#!/usr/bin/env python3
# build_alt_measures_pce_proxy.py
#
# Reconstrucao bottom-up dos alt measures PCE que o build_alt_measures_pce.py
# pega direto do Cleveland/Dallas. Objetivo: ter os 2 lado-a-lado no SQL pra
# decomposicao e sensibilidade — NAO substitui a fonte oficial.
#
# 2 measures proxy (sufixo `_proxy` no measure/bls_code):
#   - median_pce_proxy          : weighted 50th percentile MoM SAAR
#   - trimmed_mean_pce_proxy    : weighted trim mean 24% low + 31% high
#                                   (asimetrico Dallas, calibrado pra bater
#                                    headline no long run por conta do skew
#                                    do PCE)
#
# Universe: 190 leaves do BEA U20404 (mesmos do breadth/diffusion/altas_dist).
# Peso: nominais BEA U20405 do proprio mes.
# Base MoM SAAR: ((idx[t]/idx[t-1])^12 - 1) * 100 por leaf. U20404 e SA.
# Chain para value_index: idx[t] = idx[t-1] * (1 + mom[t]) com
# mom = (1 + ann_1mo/100)^(1/12) - 1, rebase final Jan/2000=100.
#
# Prerequisitos:
#   1. scripts/fetch_pce.py       -> pce_indices_raw.csv + pce_nominais_raw.csv
#   2. scripts/build_diffusion.py -> leaves_detected.csv
#
# Uso:
#   cd pareto_pce
#   python scripts/build_alt_measures_pce_proxy.py

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
IN_PRICES   = ROOT / "data" / "pce_indices_raw.csv"
IN_NOMINAIS = ROOT / "data" / "pce_nominais_raw.csv"
LEAVES_CSV  = ROOT / "data" / "leaves_detected.csv"
OUT_CSV     = ROOT / "data" / "pce_alt_measures_proxy.csv"

COVERAGE_THRESHOLD_PCT = 70.0

# Dallas Trim Mean PCE: trim 24% baixo + 31% alto (asimetrico).
TRIM_LOW_FRAC  = 0.24
TRIM_HIGH_FRAC = 0.31


def weighted_median(values: np.ndarray, weights: np.ndarray) -> float:
    """Weighted 50th percentile. Ordena por valor, acha o primeiro ponto onde
    o cumulativo de peso cruza 50% do total."""
    s = pd.DataFrame({"v": values, "w": weights}).dropna().sort_values("v")
    if s.empty:
        return np.nan
    cum = s["w"].cumsum().values
    threshold = s["w"].sum() / 2.0
    i = int(np.searchsorted(cum, threshold, side="left"))
    i = min(i, len(s) - 1)
    return float(s["v"].iloc[i])


def weighted_trim_mean(values: np.ndarray, weights: np.ndarray,
                       trim_low: float, trim_high: float) -> float:
    """Weighted trimmed mean, trim ASIMETRICO (trim_low baixo + trim_high alto).
    Items que straddleiam a boundary de corte contribuem com peso efetivo
    proporcional ao overlap — padrao Dallas/Cleveland."""
    s = pd.DataFrame({"v": values, "w": weights}).dropna().sort_values("v")
    if s.empty:
        return np.nan
    wtot = float(s["w"].sum())
    cum = s["w"].cumsum().values
    cum_prev = cum - s["w"].values   # cumulativo ANTES deste item
    lo = trim_low * wtot
    hi = (1.0 - trim_high) * wtot
    eff = np.maximum(0.0, np.minimum(cum, hi) - np.maximum(cum_prev, lo))
    ws = eff.sum()
    if ws <= 0:
        return np.nan
    return float((eff * s["v"].values).sum() / ws)


def _chain_index(ann_1mo: pd.Series, base: float = 100.0) -> pd.Series:
    """Chain universal — mesmo helper do build_alt_measures_pce.py."""
    mom = (1 + ann_1mo / 100) ** (1 / 12) - 1
    factor = (1 + mom.fillna(0)).cumprod()
    return base * factor


def _rebase_jan2000(df: pd.DataFrame) -> pd.DataFrame:
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


def compute_proxy_measures(df_prices: pd.DataFrame, df_nominais: pd.DataFrame,
                            leaves: pd.DataFrame,
                            scope: str = "headline") -> pd.DataFrame:
    """Pra cada data, computa MoM SAAR por leaf, aplica weighted median +
    weighted trim mean 24/31. Retorna long df (date, measure, ann_1mo).

    scope: 'headline' (todos 190 leaves), 'goods' (so Goods, 90 leaves),
           'services' (so Services, 100 leaves). Afeta label do measure
           (`_goods` / `_services` sufixo) e universe de leaves usados.
    """
    assert scope in {"headline", "goods", "services"}, f"scope invalido: {scope}"

    # Filtra leaves pelo scope (headline usa todos)
    if scope == "goods":
        leaves_scope = leaves[leaves["aggregate"] == "Goods"]
    elif scope == "services":
        leaves_scope = leaves[leaves["aggregate"] == "Services"]
    else:
        leaves_scope = leaves
    leaf_lines = set(leaves_scope["line_number"].astype(int))

    px = df_prices[df_prices["line_number"].isin(leaf_lines)].copy()
    nm = df_nominais[df_nominais["line_number"].isin(leaf_lines)].copy()

    px = px.sort_values(["line_number", "date"])
    px["mom_saar"] = (px.groupby("line_number")["value"]
                       .transform(lambda s: ((s / s.shift(1)) ** 12 - 1) * 100))

    nm = nm.rename(columns={"value": "nominal"})

    df = px[["date", "line_number", "mom_saar"]].merge(
        nm[["date", "line_number", "nominal"]],
        on=["date", "line_number"], how="inner",
    )
    df = df.dropna(subset=["mom_saar", "nominal"])

    # Guard de cobertura (release parcial) — relativo ao universe do scope
    total_nominal_per_date = nm.groupby("date")["nominal"].sum().rename("total_nom")
    df = df.merge(total_nominal_per_date, left_on="date", right_index=True)
    df["coverage_pct"] = df.groupby("date")["nominal"].transform("sum") / df["total_nom"] * 100
    low_cov = df[df["coverage_pct"] < COVERAGE_THRESHOLD_PCT]["date"].unique()
    if len(low_cov) > 0:
        for d in sorted(low_cov):
            c = df[df["date"] == d]["coverage_pct"].iloc[0]
            print(f"[WARN] {scope} {pd.Timestamp(d).date()}: cobertura "
                  f"{c:.1f}% < {COVERAGE_THRESHOLD_PCT}% — descartada")
        df = df[~df["date"].isin(low_cov)]

    # Label dos measures depende do scope: headline sem sufixo, G/S com sufixo
    suffix = "" if scope == "headline" else f"_{scope}"
    label_median = f"median_pce{suffix}_proxy"
    label_trim   = f"trimmed_mean_pce{suffix}_proxy"

    out_rows = []
    for d, g in df.groupby("date"):
        v = g["mom_saar"].values
        w = g["nominal"].values
        med = weighted_median(v, w)
        trm = weighted_trim_mean(v, w, TRIM_LOW_FRAC, TRIM_HIGH_FRAC)
        out_rows.append({"date": d, label_median: med, label_trim: trm})
    wide = pd.DataFrame(out_rows)

    # Long format: 1 row por (date, measure) com ann_1mo = valor computado
    long = wide.melt(id_vars=["date"], var_name="measure", value_name="ann_1mo")
    long = long.sort_values(["measure", "date"]).reset_index(drop=True)
    return long


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Reconstrucao bottom-up Median+Trim Mean PCE.",
    )
    ap.add_argument(
        "--skip-benchmark", action="store_true",
        help="Pula comparacao com pce_alt_measures.csv (scraped). Util em "
             "release day quando BEA ja saiu mas Cleveland/Dallas ainda nao, "
             "evitando print de diff grande vs CSV scraped stale.",
    )
    args = ap.parse_args()

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

    print(f"[2] Weighted median + trim mean (24/31 Dallas) por scope...")
    # 3 scopes: headline (190 leaves), goods (90), services (100). Fed oficial
    # publica so headline — G/S aqui e proxy puro, sem oficial pra comparar.
    long = pd.concat(
        [compute_proxy_measures(px, nm, leaves, scope=s)
         for s in ["headline", "goods", "services"]],
        ignore_index=True,
    )
    print(f"  measures gerados: {sorted(long['measure'].unique())}")

    # value_index: chain universal (idem build_alt_measures_pce.py)
    pieces = []
    for measure, g in long.groupby("measure"):
        g = g.sort_values("date").reset_index(drop=True).copy()
        g["value_index"] = _chain_index(g["ann_1mo"]).values
        pieces.append(g)
    out = pd.concat(pieces, ignore_index=True)
    out = _rebase_jan2000(out)
    out["mom_sa"] = ((1 + out["ann_1mo"] / 100) ** (1 / 12) - 1) * 100
    # YoY derivado do index chain
    pieces = []
    for measure, g in out.groupby("measure"):
        g = g.sort_values("date").reset_index(drop=True).copy()
        g["ann_12mo"] = (g["value_index"] / g["value_index"].shift(12) - 1) * 100
        pieces.append(g)
    out = pd.concat(pieces, ignore_index=True)
    out = out.sort_values(["measure", "date"]).reset_index(drop=True)
    out = out[["date", "measure", "value_index", "ann_1mo", "mom_sa", "ann_12mo"]]

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT_CSV, index=False)
    print(f"[3] Salvo em {OUT_CSV.name}: {len(out)} rows")

    # Preview final
    print(f"\n[preview] Summary por measure:")
    s = out.groupby("measure").agg(
        n_idx=("value_index", lambda x: x.notna().sum()),
        n_1mo=("ann_1mo", lambda x: x.notna().sum()),
        min_date=("date", "min"),
        max_date=("date", "max"),
        last_yoy=("ann_12mo", lambda x: round(x.dropna().iloc[-1], 2) if x.notna().any() else None),
        last_idx=("value_index", lambda x: round(x.dropna().iloc[-1], 2) if x.notna().any() else None),
    )
    print(s.to_string())

    # Quick benchmark vs oficial (se csv existir E usuario nao pediu skip).
    # Pulado em release day: BEA sai manha; Cleveland/Dallas publicam horas
    # depois. Se o CSV scraped existir mas estiver stale (release anterior),
    # o print mostra diff grande que NAO reflete problema no proxy — a logica
    # do proxy nao depende do scraped em nada, so le os raws do BEA.
    official = ROOT / "data" / "pce_alt_measures.csv"
    if args.skip_benchmark:
        print(f"\n[benchmark] skipped via --skip-benchmark")
    elif official.exists():
        off = pd.read_csv(official, parse_dates=["date"])
        off_last = off["date"].max()
        new_last = out["date"].max()
        if off_last < new_last:
            print(f"\n[benchmark] AVISO: {official.name} esta stale "
                  f"(last={off_last.date()}, proxy last={new_last.date()}). "
                  f"Isso e esperado em release day — BEA sai antes de "
                  f"Cleveland/Dallas. Diff mostrado abaixo IGNORA o mes mais "
                  f"recente. Use --skip-benchmark pra suprimir.")
        print(f"\n[benchmark] vs {official.name} (ultimo overlap, so headline)")
        # Oficial Fed so publica headline (Dallas/Cleveland nao decompoem
        # Goods/Services), entao G/S proxy nao tem benchmark possivel.
        for proxy_m, off_m in [("median_pce_proxy", "median_pce"),
                                 ("trimmed_mean_pce_proxy", "trimmed_mean_pce")]:
            c = out[out["measure"] == proxy_m][["date", "ann_12mo"]].rename(columns={"ann_12mo": "yoy_proxy"})
            o = off[off["measure"] == off_m][["date", "ann_12mo"]].rename(columns={"ann_12mo": "yoy_official"})
            cmp = c.merge(o, on="date", how="inner").dropna()
            if cmp.empty:
                print(f"  {proxy_m}: no overlap"); continue
            diff = (cmp["yoy_proxy"] - cmp["yoy_official"]).abs()
            last = cmp.iloc[-1]
            print(f"  {proxy_m:28s}  n={len(cmp):4d}  "
                  f"mean|d|={diff.mean():.3f}pp  max|d|={diff.max():.3f}pp  "
                  f"last {last['date'].date()}: proxy={last['yoy_proxy']:.3f}% "
                  f"vs official={last['yoy_official']:.3f}%")


if __name__ == "__main__":
    main()
