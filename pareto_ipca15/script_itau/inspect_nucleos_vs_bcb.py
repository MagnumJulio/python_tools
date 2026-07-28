#!/usr/bin/env python
# inspect_nucleos_vs_bcb.py
# Overlay dos nucleos NT_57 contra BCB SGS, pra diagnosticar onde nossa
# recon diverge das series oficiais.
#
# 8 paineis: MA/MS/DP (estatisticos) + EX-FE/EX1/EX3-Serv/EX3-Ind/Difusao (NT_57).
# SGS: ma=11426, ms=4466, dp=16122, exfe=28751, ex1=16121,
#      ex3_serv=29683, ex3_ind=29684, difusao=21379
#
# Outputs em scripts/outputs/inspection/:
#   nucleos_overlay.png    - 4x2 paineis: nossa vs BCB (variacao mensal)
#   nucleos_diff.png       - 4x2 paineis: ours - bcb (pp), com banda +-0.1pp
#   nucleos_overlay_12m.png- 4x2 paineis: ours vs BCB acumulada 12m
#
# Uso:
#   cd pareto_ipca
#   python script_itau/inspect_nucleos_vs_bcb.py
#   python script_itau/inspect_nucleos_vs_bcb.py --since 2018-01

import argparse
import sys
from pathlib import Path

import pandas as pd
import requests
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parent.parent
VAR_CSV = ROOT / "data" / "ipca15_pareto_recon.csv"
OUT_DIR = ROOT / "scripts" / "outputs" / "inspection"

NUCLEOS = [
    ("nucleo_ma",   11426, "MA — Medias Aparadas (sem suavizacao)"),
    ("nucleo_ms",   4466,  "MS — Medias Aparadas com Suavizacao"),
    ("nucleo_dp",   16122, "DP — Dupla Ponderacao"),
    ("nucleo_exfe", 28751, "EX-FE — exclusao Food & Energy (COICOP)"),
    ("nucleo_ex1",  16121, "EX1 — exclusao alim. volateis + combustiveis"),
    ("ex3_serv",    29683, "EX3 Servicos — subjacente de servicos"),
    ("ex3_ind",     29684, "EX3 Industriais — subjacente de industriais"),
    ("difusao",     21379, "Indice de Difusao (% subitens c/ alta)"),
]


def fetch_sgs(code: int) -> pd.Series:
    url = f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.{code}/dados?formato=json"
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    raw = r.json()
    df = pd.DataFrame(raw)
    df["date"] = pd.to_datetime(df["data"], format="%d/%m/%Y")
    df["value"] = df["valor"].astype(float)
    return df.set_index("date")["value"].sort_index()


def var_12m(s: pd.Series) -> pd.Series:
    return ((1 + s / 100).rolling(12).apply(lambda x: x.prod() - 1, raw=True) * 100)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", type=str, default="2010-01",
                    help="Janela inicial (YYYY-MM). Default: 2010-01.")
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    if not VAR_CSV.exists():
        sys.exit(f"Falta {VAR_CSV}. Rode o pipeline R.")
    long_var = pd.read_csv(VAR_CSV)
    long_var["date"] = pd.to_datetime(long_var["date"])

    # Carrega BCB
    print("[1] Fetch BCB SGS...")
    bcb = {}
    for cat, sgs, _ in NUCLEOS:
        print(f"    SGS {sgs} ({cat})...", end=" ", flush=True)
        bcb[cat] = fetch_sgs(sgs)
        print(f"{len(bcb[cat])} obs ({bcb[cat].index.min().date()} -> {bcb[cat].index.max().date()})")

    # Monta dict de pares (ours, bcb) por categoria
    pairs = {}
    for cat, _, _ in NUCLEOS:
        ours = long_var[long_var.category_code == cat].set_index("date")["value"].sort_index()
        b = bcb[cat]
        if args.since:
            cut = pd.to_datetime(args.since + "-01")
            ours = ours[ours.index >= cut]
            b = b[b.index >= cut]
        pairs[cat] = (ours, b)

    # Stats
    print("\n[2] Stats (ours - BCB):")
    print(f"  {'cat':12s} {'n':>5s} {'mean|d|':>9s} {'bias':>8s} {'RMSE':>7s} {'max|d|':>8s} {'corr':>6s}")
    for cat, _, _ in NUCLEOS:
        ours, b = pairs[cat]
        m = pd.concat([ours.rename("ours"), b.rename("bcb")], axis=1, join="inner").dropna()
        d = m["ours"] - m["bcb"]
        print(f"  {cat:12s} {len(m):5d} {d.abs().mean():9.4f} {d.mean():+8.4f} "
              f"{(d**2).mean()**.5:7.4f} {d.abs().max():8.4f} {m['ours'].corr(m['bcb']):6.3f}")

    # Layout 4x2 pra acomodar 8 nucleos.
    NROWS, NCOLS = 4, 2

    # PNG 1: overlay variacao mensal
    png1 = OUT_DIR / "nucleos_overlay.png"
    fig, axes = plt.subplots(NROWS, NCOLS, figsize=(18, 14), sharex=True)
    axes = axes.flatten()
    for ax, (cat, _, title) in zip(axes, NUCLEOS):
        ours, b = pairs[cat]
        ax.plot(ours.index, ours.values, lw=1.0, color="C0", label="nossa recon")
        ax.plot(b.index, b.values, lw=1.0, color="C3", label="BCB SGS", alpha=0.8)
        ax.set_title(title, fontsize=10)
        ax.axhline(0, color="k", lw=0.5)
        ax.grid(alpha=0.3)
        ax.legend(loc="upper right", fontsize=8)
        ax.set_ylabel("var. mensal (%)", fontsize=9)
    for j in range(len(NUCLEOS), len(axes)):
        axes[j].axis("off")
    fig.suptitle("Nucleos NT_57: nossa recon vs BCB SGS (variacao mensal)", fontsize=13, y=1.0)
    fig.tight_layout()
    fig.savefig(png1, dpi=110, bbox_inches="tight")
    plt.close(fig)
    print(f"\n[3] {png1.relative_to(ROOT)}")

    # PNG 2: diff (ours - bcb) com banda de +-0.1pp
    png2 = OUT_DIR / "nucleos_diff.png"
    fig, axes = plt.subplots(NROWS, NCOLS, figsize=(18, 14), sharex=True)
    axes = axes.flatten()
    for ax, (cat, _, title) in zip(axes, NUCLEOS):
        ours, b = pairs[cat]
        m = pd.concat([ours.rename("ours"), b.rename("bcb")], axis=1, join="inner").dropna()
        d = m["ours"] - m["bcb"]
        ax.bar(d.index, d.values, width=20, color=["C2" if x >= 0 else "C3" for x in d.values])
        ax.axhline(0, color="k", lw=0.5)
        ax.axhspan(-0.1, 0.1, color="gray", alpha=0.2, label="±0.1 pp")
        ax.set_title(f"{title}  (ours - BCB)", fontsize=10)
        ax.set_ylabel("diff (pp)", fontsize=9)
        ax.grid(alpha=0.3)
        ax.legend(loc="upper right", fontsize=8)
    for j in range(len(NUCLEOS), len(axes)):
        axes[j].axis("off")
    fig.suptitle("Diferenca mensal: nossa - BCB SGS", fontsize=13, y=1.0)
    fig.tight_layout()
    fig.savefig(png2, dpi=110, bbox_inches="tight")
    plt.close(fig)
    print(f"[4] {png2.relative_to(ROOT)}")

    # PNG 3: acumulada 12m (mais facil de bater contra RI)
    png3 = OUT_DIR / "nucleos_overlay_12m.png"
    fig, axes = plt.subplots(NROWS, NCOLS, figsize=(18, 14), sharex=True)
    axes = axes.flatten()
    for ax, (cat, _, title) in zip(axes, NUCLEOS):
        ours, b = pairs[cat]
        ax.plot(ours.index, var_12m(ours).values, lw=1.2, color="C0", label="nossa recon")
        ax.plot(b.index,    var_12m(b).values,    lw=1.2, color="C3", label="BCB SGS", alpha=0.8)
        ax.set_title(title, fontsize=10)
        ax.axhline(0, color="k", lw=0.5)
        ax.grid(alpha=0.3)
        ax.legend(loc="upper right", fontsize=8)
        ax.set_ylabel("var. 12m (%)", fontsize=9)
    for j in range(len(NUCLEOS), len(axes)):
        axes[j].axis("off")
    fig.suptitle("Nucleos: nossa recon vs BCB SGS (acumulada 12m)", fontsize=13, y=1.0)
    fig.tight_layout()
    fig.savefig(png3, dpi=110, bbox_inches="tight")
    plt.close(fig)
    print(f"[5] {png3.relative_to(ROOT)}")

    print(f"\n[OK] {OUT_DIR.relative_to(ROOT)}/")


if __name__ == "__main__":
    main()
