#!/usr/bin/env python3
# Dashboard markdown last-12m de alt measures (Atlanta/Cleveland/custom),
# inflation breadth (3-bin) e diffusion CPI (4 aggregates x 2 metrics).
# Fonte: data/cpi_cpius_alt_measures.csv + cpi_cpius_breadth.csv + cpiu_diffusion.csv.

from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "outputs" / "dashboard_cpius_extras_last_12m.md"

ALT_LABELS = {
    "median_cpi":                 "Median (Cleveland)",
    "trimmed_mean_16_cpi":        "Trimmed Mean 16% (Cleveland)",
    "trimmed_sym_25_cpi_custom":  "Trimmed Sym 25% (custom)",
    "sticky_cpi":                 "Sticky-Price (Atlanta)",
    "core_sticky_cpi":            "Core Sticky-Price (Atlanta)",
    "sticky_cpi_ex_shelter":      "Sticky-Price ex Shelter (Atlanta)",
    "core_sticky_cpi_ex_shelter": "Core Sticky-Price ex Shelter (Atlanta)",
    "flexible_cpi":               "Flexible-Price (Atlanta)",
    "core_flexible_cpi":          "Core Flexible-Price (Atlanta)",
}
ALT_ORDER = [
    "median_cpi", "trimmed_mean_16_cpi", "trimmed_sym_25_cpi_custom",
    "sticky_cpi", "core_sticky_cpi",
    "sticky_cpi_ex_shelter", "core_sticky_cpi_ex_shelter",
    "flexible_cpi", "core_flexible_cpi",
]

BIN_LABELS = {
    "below_0pct": "YoY < 0%",
    "0_to_3pct":  "0% ≤ YoY ≤ 3%",
    "above_3pct": "YoY > 3%",
}
BIN_ORDER = ["below_0pct", "0_to_3pct", "above_3pct"]

DIFF_LABELS = {
    "Headline":      "Headline (todos itens)",
    "Goods":         "Goods",
    "Goods_ex_cars": "Goods ex cars",
    "Services":      "Services",
}
DIFF_ORDER = ["Headline", "Goods", "Goods_ex_cars", "Services"]


def date_window(last: pd.Timestamp, n: int = 12) -> list[pd.Timestamp]:
    start = (last - pd.DateOffset(months=n - 1)).replace(day=1)
    return list(pd.date_range(start, last, freq="MS"))


def to_md(p: pd.DataFrame, title: str, note: str, digits: int = 2) -> str:
    out = [f"### {title}", "", note, ""]
    hdr = ["Série"] + list(p.columns)
    out.append("| " + " | ".join(hdr) + " |")
    out.append("|" + "|".join([":---"] + ["---:"] * len(p.columns)) + "|")
    for name, row in p.iterrows():
        cells = [name] + [
            "n/a" if pd.isna(v) else f"{v:.{digits}f}" for v in row.values
        ]
        out.append("| " + " | ".join(cells) + " |")
    out.append("")
    return "\n".join(out)


# ---------- alt measures ----------
alt = pd.read_csv(ROOT / "data" / "cpi_cpius_alt_measures.csv", parse_dates=["date"])
alt_last = alt["date"].max()
alt_dates = date_window(alt_last)
alt_cols = [d.strftime("%Y-%m") for d in alt_dates]

def alt_pivot(col: str) -> pd.DataFrame:
    sub = alt[alt["date"].isin(alt_dates)]
    p = sub.pivot(index="measure", columns="date", values=col)
    p.columns = [c.strftime("%Y-%m") for c in p.columns]
    p = p.reindex(index=ALT_ORDER, columns=alt_cols)
    p.index = [ALT_LABELS[m] for m in p.index]
    return p

alt_1mo = alt_pivot("ann_1mo")
alt_mom_sa = alt_pivot("mom_sa")
alt_yoy = alt_pivot("ann_12mo")

# ---------- breadth ----------
br = pd.read_csv(ROOT / "data" / "cpi_cpius_breadth.csv", parse_dates=["date"])
br_last = br["date"].max()
br_dates = date_window(br_last)
br_cols = [d.strftime("%Y-%m") for d in br_dates]
br_pivot = br[br["date"].isin(br_dates)].pivot(
    index="bin", columns="date", values="weight_share"
)
br_pivot.columns = [c.strftime("%Y-%m") for c in br_pivot.columns]
br_pivot = br_pivot.reindex(index=BIN_ORDER, columns=br_cols)
br_pivot.index = [BIN_LABELS[b] for b in br_pivot.index]

# ---------- diffusion ----------
di = pd.read_csv(ROOT / "data" / "cpiu_diffusion.csv", parse_dates=["date"])
di_last = di["date"].max()
di_dates = date_window(di_last)
di_cols = [d.strftime("%Y-%m") for d in di_dates]

def di_pivot(metric: str) -> pd.DataFrame:
    sub = di[(di["metric"] == metric) & (di["date"].isin(di_dates))]
    p = sub.pivot(index="aggregate", columns="date", values="value")
    p.columns = [c.strftime("%Y-%m") for c in p.columns]
    p = p.reindex(index=DIFF_ORDER, columns=di_cols)
    p.index = [DIFF_LABELS[a] for a in p.index]
    return p

di_yoy = di_pivot("diffusion_yoy_3pct")
# 6m-ann so eh publicada pra Headline (bate build_diffusion_cpius.py);
# filtra pra evitar linha de n/a.
di_6ma = di_pivot("diffusion_6ma_ann_3pct").loc[[DIFF_LABELS["Headline"]]]

# ---------- montagem ----------
md = [
    "# CPI-U dashboard extras — últimos 12 meses",
    "",
    f"**Alt measures/Breadth last date**: {alt_last:%Y-%m}. "
    f"**Diffusion last date**: {di_last:%Y-%m} "
    f"(pode defasar vs alt — depende de todas as subitens leaves estarem no cache).",
    "",
    "Gerado por `outputs/_make_dashboard_extras_last_12m.py` em cima de "
    "`cpi_cpius_alt_measures.csv` (Atlanta xlsx + Cleveland CSV + custom), "
    "`cpi_cpius_breadth.csv` (cross-section 177 subitens pesados pela RI) e "
    "`cpiu_diffusion.csv` (item-level ponderado, 4 aggregates).",
    "",
    "> **Notas de cobertura**:",
    "> - Cleveland Median/Trimmed Mean 16% publicam **só YoY** (sem 1-mo "
    "annualized) — células de 1mo aparecem `n/a`.",
    "> - Trimmed Sym 25% custom tem **só 1-mo annualized** (construção não "
    "produz YoY) — células de YoY aparecem `n/a`.",
    "> - Breadth em **2025-10 descartado** (cobertura 11% < 70% threshold): "
    "release BLS incompleto no shutdown. Guard aplicado em "
    "`build_breadth_cpi.py` descarta datas com cobertura abaixo do limiar.",
    "> - Diffusion 6m-ann > 3% só é publicada para Headline (bate "
    "`build_diffusion_cpius.py`); Goods/Services não têm essa métrica.",
    "",
    to_md(alt_1mo, "Alt measures — 1-mo annualized (%)",
          "Núcleos alternativos de inflação, taxa anualizada do mês. "
          "Family Atlanta Sticky/Flex (1967+), Cleveland Median/Trimmed (1983+), "
          "Trimmed Sym 25% custom.", 2),
    to_md(alt_mom_sa, "Alt measures — proxy MoM SA (%)",
          "Variação mensal SA derivada do 1-mo annualized: "
          "`mom_sa = (1 + ann_1mo/100)^(1/12) - 1`. Mesma unidade dos MoM SA "
          "do dash CPI principal (comparação direta com all_items/core).", 2),
    to_md(alt_yoy, "Alt measures — YoY (%)",
          "Mesmas 9 séries, variação 12 meses.", 2),
    to_md(br_pivot, "Inflation breadth — share do peso por bin YoY (%)",
          "Cross-section de 177 subitens leaves CPI-U, agrupados em 3 bins "
          "de YoY e ponderados pelo peso RI Dez do ano anterior. "
          "Soma dos 3 bins = 100 em cada mês.", 2),
    to_md(di_yoy, "Diffusion — share de itens com YoY > 3% (%)",
          "Difusão item-level ponderada. Fração do peso agregado em "
          "subitens com YoY acima de 3%, por bloco. Headline = todos os itens; "
          "Goods, Services, Goods ex cars são subsets.", 2),
    to_md(di_6ma, "Diffusion — share de itens com 6m-ann > 3% (%)",
          "Mesma difusão mas usando variação 6 meses anualizada "
          "(sinal mais tempestivo que YoY).", 2),
]

OUT.write_text("\n".join(md), encoding="utf-8")
print(f"[OK] {OUT.relative_to(ROOT)} — alt/breadth={alt_last:%Y-%m}, "
      f"diff={di_last:%Y-%m}, 12 meses.")
