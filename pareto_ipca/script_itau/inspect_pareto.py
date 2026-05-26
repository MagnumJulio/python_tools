#!/usr/bin/env python
# inspect_pareto.py
# Gera artefatos pra inspecao visual das 20 series PARETO_IPCA contra
# qualquer referencia externa. Outputs em scripts/outputs/inspection/:
#
#   pareto_wide.xlsx  - 3 abas: variacao, indice, var_12m (date x 20 cols)
#   pareto_grid.png   - 5x4 grid com os 20 indices (escala log opcional)
#   pareto_var_grid.png - 5x4 grid com variacao mensal das 20 series
#
# Uso:
#   cd pareto_ipca
#   python script_itau/inspect_pareto.py
#   python script_itau/inspect_pareto.py --log   # PNG do indice em escala log
#   python script_itau/inspect_pareto.py --only livres,nucleo_ex0  # subset

import argparse
import sys
from pathlib import Path

import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parent.parent
VAR_CSV = ROOT / "data" / "ipca_pareto_recon.csv"
IDX_CSV = ROOT / "data" / "ipca_pareto_indice.csv"
OUT_DIR = ROOT / "scripts" / "outputs" / "inspection"

# Ordem desejada nas saidas (agrupada por familia).
CATEGORY_ORDER = [
    # IPCA controles primarios
    "administrados", "livres", "industriais", "servicos", "alim_domicilio",
    # Decomposicao de servicos
    "servicos_subj", "servicos_exsubj",
    # Decomposicao de industriais
    "duraveis", "semiduraveis", "ndur_industr",
    # Alim. por processamento
    "alim_in_natura", "alim_semi_elab", "alim_industr",
    # Comerc / Ncomerc
    "comerc", "ncomerc",
    # Nucleos
    "nucleo_ex0", "nucleo_ex3", "nucleo_ma", "nucleo_ms", "nucleo_dp",
]

LABELS = {
    "administrados":   "Monitorados",
    "livres":          "Livres",
    "industriais":     "Industriais",
    "servicos":        "Servicos",
    "alim_domicilio":  "Alim. domicilio",
    "nucleo_ex0":      "Nucleo EX0",
    "nucleo_ex3":      "Nucleo EX3",
    "duraveis":        "Duraveis",
    "semiduraveis":    "Semiduraveis",
    "ndur_industr":    "ND-industriais",
    "servicos_subj":   "Servicos subj.",
    "servicos_exsubj": "Servicos ex-subj.",
    "alim_in_natura":  "Alim. in natura",
    "alim_semi_elab":  "Alim. semi-elab.",
    "alim_industr":    "Alim. industr.",
    "comerc":          "Comercializaveis",
    "ncomerc":         "Nao-comerc.",
    "nucleo_ma":       "Nucleo MA",
    "nucleo_ms":       "Nucleo MS",
    "nucleo_dp":       "Nucleo DP",
}


def _load_long(path: Path, value_col: str) -> pd.DataFrame:
    if not path.exists():
        sys.exit(f"CSV nao encontrado: {path}. Rode o pipeline R primeiro.")
    df = pd.read_csv(path)
    df["date"] = pd.to_datetime(df["date"])
    return df.rename(columns={value_col: "value"}) if value_col != "value" else df


def _pivot_wide(df_long: pd.DataFrame, cats: list[str]) -> pd.DataFrame:
    w = df_long.pivot(index="date", columns="category_code", values="value")
    return w[[c for c in cats if c in w.columns]].sort_index()


def _var_12m(wide_var: pd.DataFrame) -> pd.DataFrame:
    # Acumulada 12m: prod(1+v/100)-1 em janela movel de 12.
    r = (1 + wide_var / 100.0)
    out = r.rolling(12).apply(lambda x: x.prod() - 1, raw=True) * 100
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", action="store_true",
                    help="PNG do indice em escala log (default linear).")
    ap.add_argument("--only", type=str, default=None,
                    help="Lista CSV de category_code (default: todas as 20).")
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    var_long = _load_long(VAR_CSV, "value")
    idx_long = _load_long(IDX_CSV, "index")

    only = set(args.only.split(",")) if args.only else None
    cats = [c for c in CATEGORY_ORDER if c in set(var_long.category_code)]
    if only:
        cats = [c for c in cats if c in only]

    wide_var = _pivot_wide(var_long, cats)
    wide_idx = _pivot_wide(idx_long, cats)
    wide_v12 = _var_12m(wide_var)

    # Janela visual: 2010-01 em diante (xlsx mantém histórico completo;
    # crise 2008-09 esmaga escala dos paineis).
    PLOT_SINCE = "2010-01-01"
    wide_var_plot = wide_var.loc[wide_var.index >= PLOT_SINCE]
    wide_idx_plot = wide_idx.loc[wide_idx.index >= PLOT_SINCE]
    wide_v12_plot = wide_v12.loc[wide_v12.index >= PLOT_SINCE]

    n_dates, n_cats = wide_var.shape
    print(f"[1] {n_cats} categorias, {n_dates} meses ({wide_var.index.min().date()} -> {wide_var.index.max().date()})")

    # 1) Excel wide com 3 abas
    xlsx_path = OUT_DIR / "pareto_wide.xlsx"
    print(f"[2] Escrevendo {xlsx_path.relative_to(ROOT)}...")
    with pd.ExcelWriter(xlsx_path, engine="openpyxl") as w:
        wide_var.round(4).to_excel(w, sheet_name="variacao")
        wide_idx.round(4).to_excel(w, sheet_name="indice")
        wide_v12.round(4).to_excel(w, sheet_name="var_12m")

    # 2) PNG grid indice
    png_idx = OUT_DIR / ("pareto_grid_log.png" if args.log else "pareto_grid.png")
    print(f"[3] Plotando {png_idx.relative_to(ROOT)}...")
    nrows, ncols = 5, 4
    fig, axes = plt.subplots(nrows, ncols, figsize=(20, 14), sharex=True)
    axes = axes.flatten()
    for i, c in enumerate(cats):
        ax = axes[i]
        s = wide_idx_plot[c].dropna()
        ax.plot(s.index, s.values, lw=1.0, color="C0")
        ax.set_title(LABELS.get(c, c), fontsize=10)
        if args.log:
            ax.set_yscale("log")
        ax.grid(alpha=0.3)
        ax.tick_params(labelsize=8)
    for j in range(len(cats), len(axes)):
        axes[j].axis("off")
    fig.suptitle(f"PARETO_IPCA — indices ({'log' if args.log else 'linear'}, base dez/2006=100, 2010+)",
                 fontsize=14, y=1.0)
    fig.tight_layout()
    fig.savefig(png_idx, dpi=110, bbox_inches="tight")
    plt.close(fig)

    # 3) PNG grid variacao 12m
    png_v12 = OUT_DIR / "pareto_grid_var12m.png"
    print(f"[4] Plotando {png_v12.relative_to(ROOT)}...")
    fig, axes = plt.subplots(nrows, ncols, figsize=(20, 14), sharex=True)
    axes = axes.flatten()
    for i, c in enumerate(cats):
        ax = axes[i]
        s = wide_v12_plot[c].dropna()
        ax.plot(s.index, s.values, lw=1.0, color="C1")
        ax.axhline(0, color="k", lw=0.5)
        ax.set_title(LABELS.get(c, c), fontsize=10)
        ax.grid(alpha=0.3)
        ax.tick_params(labelsize=8)
    for j in range(len(cats), len(axes)):
        axes[j].axis("off")
    fig.suptitle("PARETO_IPCA — variacao acumulada 12m (%, 2010+)", fontsize=14, y=1.0)
    fig.tight_layout()
    fig.savefig(png_v12, dpi=110, bbox_inches="tight")
    plt.close(fig)

    print(f"\n[OK] {OUT_DIR.relative_to(ROOT)}:")
    for p in sorted(OUT_DIR.iterdir()):
        sz = p.stat().st_size / 1024
        print(f"  {p.name:30s} {sz:7.1f} KB")


if __name__ == "__main__":
    main()
