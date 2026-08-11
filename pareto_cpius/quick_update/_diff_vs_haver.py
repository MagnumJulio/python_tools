#!/usr/bin/env python3
"""Diff lean vs Haver (tabelas_cpi_macroitau.xlsx).

Roda o pipeline do update_cpius_lean em memoria pras 47 cats (41 base + 8 custom)
e imprime %yoy NSA (Apr/May/Jun 2026) + %mom SA (Jul/2025 -> Jun/2026) pras
cats-alvo listadas na planilha Haver, junto com o gap absoluto (pp).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from update_cpius_lean import (  # noqa: E402
    CUSTOM_RECIPES,
    ITEM_CODES,
    build_custom_idx,
    build_series_ids,
    compute_weights,
    fetch_bls_batched,
    rebase_jan2000,
)

import os


def _pct_mom(s: pd.Series) -> pd.Series:
    return (s / s.shift(1) - 1) * 100


def _pct_yoy(s: pd.Series) -> pd.Series:
    return (s / s.shift(12) - 1) * 100


HAVER_YOY_NSA = {  # (cat_key, haver_label) -> {date -> value}
    "all_items":                 ("Headline CPI",                       {"2026-04": 3.81, "2026-05": 4.25, "2026-06": 3.53}),
    "core":                      ("CPI ex. Food & energy",              {"2026-04": 2.75, "2026-05": 2.85, "2026-06": 2.59}),
    "core_goods":                ("goods ex food & energy",             {"2026-04": 1.13, "2026-05": 1.06, "2026-06": 0.82}),
    "core_services":             ("services ex food & energy",          {"2026-04": 3.27, "2026-05": 3.42, "2026-06": 3.16}),
    "food":                      ("food",                               {"2026-04": 3.18, "2026-05": 3.08, "2026-06": 3.01}),
    "energy":                    ("energy",                             {"2026-04":17.87, "2026-05":23.54, "2026-06":15.7}),
}

# Ambiguos - vou printar todos os 8 customs e o usuario decide o mapping
HAVER_YOY_NSA_AMBIG = {
    "core services ex-rent of shelter":    {"2026-04": 3.38, "2026-05": 3.66, "2026-06": 3.17},
    "core services ex-shelter plus lodging": {"2026-04": 3.29, "2026-05": 3.58, "2026-06": 3.10},
    "core services ex-shelter":            {"2026-04": 3.22, "2026-05": 3.49, "2026-06": 3.00},
    "core bernanke":                       {"2026-06": 2.36},
}

HAVER_MOM_SA = {  # cat -> {date -> value}
    "all_items": {"2025-07": 0.23, "2025-08": 0.35, "2025-09": 0.30, "2025-10": 0.11,
                  "2025-11": 0.13, "2025-12": 0.30, "2026-01": 0.17, "2026-02": 0.27,
                  "2026-03": 0.87, "2026-04": 0.64, "2026-05": 0.47, "2026-06": -0.42},
    "core":      {"2025-07": 0.31, "2025-08": 0.31, "2025-09": 0.22, "2025-10": 0.09,
                  "2025-11": 0.09, "2025-12": 0.23, "2026-01": 0.30, "2026-02": 0.22,
                  "2026-03": 0.20, "2026-04": 0.38, "2026-05": 0.21, "2026-06": -0.02},
}


def main():
    api_key = os.environ.get("BLS_API_KEY")

    # Fetch tudo: 41 base
    all_base = set(ITEM_CODES.keys())
    ids, id_map = build_series_ids(all_base)
    raw = fetch_bls_batched(ids, start_year=2000, end_year=2026, api_key=api_key)

    # Reagrupa em wide
    idx_wide: dict = {}
    for sid, s in raw.items():
        cat, sa = id_map[sid]
        idx_wide.setdefault(sa, {})[cat] = rebase_jan2000(s)
    idx_nsa = pd.DataFrame(idx_wide["NSA"]).sort_index()
    idx_sa  = pd.DataFrame(idx_wide["SA"]).sort_index()

    # Weights (usa NSA)
    weights = compute_weights(idx_nsa, all_base)
    peso_wide = weights.pivot_table(index="date", columns="cat", values="weight").sort_index()

    # Customs
    for cc, r in CUSTOM_RECIPES.items():
        idx_nsa[cc] = build_custom_idx(r, idx_nsa, peso_wide)
        idx_sa[cc]  = build_custom_idx(r, idx_sa,  peso_wide)

    # ==== TABLE 1: yoy NSA — clear mappings ====
    print("\n" + "=" * 78)
    print("YoY NSA (%): lean vs Haver")
    print("=" * 78)
    print(f"{'cat':<20} {'label Haver':<28} {'date':<8} {'lean':>8} {'haver':>8} {'gap(pp)':>9}")
    for cat, (label, targets) in HAVER_YOY_NSA.items():
        yoy = _pct_yoy(idx_nsa[cat])
        for d, v_haver in targets.items():
            ts = pd.Timestamp(d + "-01")
            v_lean = yoy.get(ts)
            gap = v_lean - v_haver if v_lean is not None and not pd.isna(v_lean) else float("nan")
            flag = "" if abs(gap) < 0.05 else ("**" if abs(gap) > 0.20 else "*")
            print(f"{cat:<20} {label:<28} {d:<8} {v_lean:>8.2f} {v_haver:>8.2f} {gap:>+9.3f} {flag}")

    # ==== TABLE 2: yoy NSA — customs (todos os 8) ====
    print("\n" + "=" * 78)
    print("YoY NSA (%) das 8 customs — comparar com labels ambiguas do Haver:")
    print("=" * 78)
    for label, targets in HAVER_YOY_NSA_AMBIG.items():
        print(f"\n  Haver: '{label}' = {targets}")
    print(f"\n  Lean (todas as 8 customs):")
    print(f"  {'custom':<45} {'2026-04':>9} {'2026-05':>9} {'2026-06':>9}")
    for cc in sorted(CUSTOM_RECIPES.keys()):
        yoy = _pct_yoy(idx_nsa[cc])
        v4 = yoy.get(pd.Timestamp("2026-04-01"))
        v5 = yoy.get(pd.Timestamp("2026-05-01"))
        v6 = yoy.get(pd.Timestamp("2026-06-01"))
        print(f"  {cc:<45} {v4:>9.3f} {v5:>9.3f} {v6:>9.3f}")

    # ==== TABLE 3: mom SA — headline + core ====
    print("\n" + "=" * 78)
    print("MoM SA (%): lean vs Haver")
    print("=" * 78)
    print(f"{'cat':<12} {'date':<10} {'lean':>8} {'haver':>8} {'gap(pp)':>9}")
    for cat, targets in HAVER_MOM_SA.items():
        mom = _pct_mom(idx_sa[cat])
        for d, v_haver in targets.items():
            ts = pd.Timestamp(d + "-01")
            v_lean = mom.get(ts)
            gap = v_lean - v_haver if v_lean is not None and not pd.isna(v_lean) else float("nan")
            flag = "" if abs(gap) < 0.05 else ("**" if abs(gap) > 0.20 else "*")
            print(f"{cat:<12} {d:<10} {v_lean:>8.2f} {v_haver:>8.2f} {gap:>+9.3f} {flag}")

    # ==== TABLE 4: quantile do gap ====
    print("\n" + "=" * 78)
    print("Resumo de gaps (base cats YoY NSA):")
    print("=" * 78)
    gaps = []
    for cat, (label, targets) in HAVER_YOY_NSA.items():
        yoy = _pct_yoy(idx_nsa[cat])
        for d, v_haver in targets.items():
            v_lean = yoy.get(pd.Timestamp(d + "-01"))
            if v_lean is not None and not pd.isna(v_lean):
                gaps.append(abs(v_lean - v_haver))
    if gaps:
        s = pd.Series(gaps)
        print(f"  n={len(s)}  min={s.min():.3f}  median={s.median():.3f}  "
              f"max={s.max():.3f}  mean={s.mean():.3f} (pp)")


if __name__ == "__main__":
    main()
