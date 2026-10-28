#!/usr/bin/env python3
# Dashboard markdown de validacao da serie INDEX das alt measures:
#  - Index level por measure (last 24m + anchors de longo prazo)
#  - YoY derivado do index vs ann_12mo publicado (diff checa chain)
#  - MoM derivado do index vs mom_sa publicado (diff checa chain)
# Fonte: data/cpi_cpius_alt_measures.csv (gerado por scripts/build_alt_measures_cpi.py).

from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent.parent
OUT = ROOT / "outputs" / "dashboards" / "dashboard_cpius_alt_index_check.md"
IN_CSV = ROOT / "data" / "cpi_cpius_alt_measures.csv"

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
ALT_ORDER = list(ALT_LABELS.keys())

ANCHORS = [
    pd.Timestamp("1983-01-01"),
    pd.Timestamp("2000-01-01"),
    pd.Timestamp("2010-01-01"),
    pd.Timestamp("2020-01-01"),
]


def _to_md(p: pd.DataFrame, title: str, note: str, digits: int = 3) -> str:
    out = [f"### {title}", "", note, ""]
    hdr = ["Série"] + list(p.columns)
    out.append("| " + " | ".join(hdr) + " |")
    out.append("|" + "|".join([":---"] + ["---:"] * len(p.columns)) + "|")
    for name, row in p.iterrows():
        cells = [name] + ["n/a" if pd.isna(v) else f"{v:.{digits}f}" for v in row.values]
        out.append("| " + " | ".join(cells) + " |")
    out.append("")
    return "\n".join(out)


df = pd.read_csv(IN_CSV, parse_dates=["date"])

# Deriva YoY/MoM a partir do value_index pra cada measure.
derived = []
for m, g in df.groupby("measure"):
    g = g.sort_values("date").reset_index(drop=True).copy()
    g["mom_derived"] = (g["value_index"] / g["value_index"].shift(1) - 1) * 100
    g["yoy_derived"] = (g["value_index"] / g["value_index"].shift(12) - 1) * 100
    derived.append(g)
df = pd.concat(derived, ignore_index=True)

last = df["date"].max()
last_12 = pd.date_range((last - pd.DateOffset(months=11)).replace(day=1), last, freq="MS")
last_24 = pd.date_range((last - pd.DateOffset(months=23)).replace(day=1), last, freq="MS")


def _pivot(sub: pd.DataFrame, col: str, dates: list[pd.Timestamp]) -> pd.DataFrame:
    s = sub[sub["date"].isin(dates)]
    p = s.pivot(index="measure", columns="date", values=col)
    p.columns = [c.strftime("%Y-%m") for c in p.columns]
    p = p.reindex(index=ALT_ORDER, columns=[d.strftime("%Y-%m") for d in dates])
    p.index = [ALT_LABELS[k] for k in p.index]
    return p


idx_24 = _pivot(df, "value_index", list(last_24))
yoy_derived = _pivot(df, "yoy_derived", list(last_12))
yoy_pub = _pivot(df, "ann_12mo", list(last_12))
yoy_diff = (yoy_derived - yoy_pub)
mom_derived = _pivot(df, "mom_derived", list(last_12))
mom_pub = _pivot(df, "mom_sa", list(last_12))
mom_diff = (mom_derived - mom_pub)

# Anchors de longo prazo + estatistica global de diff.
anc = df[df["date"].isin(ANCHORS + [last])].pivot(
    index="measure", columns="date", values="value_index"
)
anc.columns = [c.strftime("%Y-%m") for c in anc.columns]
anc = anc.reindex(index=ALT_ORDER, columns=[d.strftime("%Y-%m") for d in ANCHORS + [last]])
anc.index = [ALT_LABELS[k] for k in anc.index]

# Resumo chain-fidelity: max|diff| YoY e MoM por measure sobre TODA a historia.
chain_stats = []
for m, g in df.groupby("measure"):
    g = g.sort_values("date")
    yoy_full = (g.dropna(subset=["yoy_derived", "ann_12mo"])
                 .assign(d=lambda x: (x["yoy_derived"] - x["ann_12mo"]).abs()))
    mom_full = (g.dropna(subset=["mom_derived", "mom_sa"])
                 .assign(d=lambda x: (x["mom_derived"] - x["mom_sa"]).abs()))
    chain_stats.append({
        "measure": ALT_LABELS[m],
        "n_yoy_overlap": len(yoy_full),
        "max|Δyoy| (pp)": yoy_full["d"].max() if not yoy_full.empty else None,
        "mean|Δyoy| (pp)": yoy_full["d"].mean() if not yoy_full.empty else None,
        "n_mom_overlap": len(mom_full),
        "max|Δmom| (pp)": mom_full["d"].max() if not mom_full.empty else None,
        "mean|Δmom| (pp)": mom_full["d"].mean() if not mom_full.empty else None,
    })
chain_tbl = pd.DataFrame(chain_stats).set_index("measure")
chain_tbl = chain_tbl.reindex(index=[ALT_LABELS[m] for m in ALT_ORDER])

md = [
    "# CPI-U alt measures — validação da série INDEX",
    "",
    f"**Last date**: {last:%Y-%m}. Fonte: `data/cpi_cpius_alt_measures.csv`. "
    f"Index rebase: Jan/2000=100 (custom = primeira obs=100 pq começa 2001-01).",
    "",
    "Esse dashboard foi gerado pra **conferir se o index está mantendo conta** depois "
    "do sync 2026-10-28 (SQL CPI alt agora só sobe level, não mais rate).",
    "",
    "**Metodologia do index**: `idx[t] = idx[t-1] * (1 + mom[t])` com "
    "`mom = (1+ann_1mo/100)^(1/12)−1`. Rebase final pra Jan/2000=100 por measure. "
    "Atlanta não publica index level nativo (col 1 do xlsx é MoM decimal), então "
    "a reconstrução do index é universal via chain-from-ann_1mo.",
    "",
    "**Checks**:",
    "1. **Chain fidelity** (tabela abaixo): max|diff| entre YoY/MoM derivado "
    "do index vs valor publicado — tem que ser `~0` pra toda measure com overlap.",
    "2. **Anchors long-run**: idx em datas de referência (1983, 2000, 2010, 2020, last) "
    "— verificar monotonia implícita e magnitude plausível.",
    "3. **Side-by-side último ano**: YoY derivado vs publicado em cada mês dos "
    "últimos 12m; coluna de diff tem que ser `0.00`-ish.",
    "",
    _to_md(chain_tbl, "Chain fidelity — diff entre derivado e publicado (TODA a história)",
           "YoY: compara `yoy_derived = idx[t]/idx[t-12]-1` com `ann_12mo` publicado. "
           "MoM: compara `mom_derived = idx[t]/idx[t-1]-1` com `mom_sa` (que é proxy "
           "derivado do ann_1mo pela inversão). Custom não tem YoY publicado "
           "(construção só produz 1-mo).", 4),
    _to_md(anc, "Index level — anchors long-run",
           "Jan/2000=100 por construção. Custom começa 2001-01 (100 ancora na primeira obs). "
           "Cleveland FRED começa 1983-01 (antes é n/a). Atlanta 1967+ é mostrado em 1983.", 3),
    _to_md(idx_24, "Index level — últimos 24 meses",
           "Nível do índice (rebase Jan/2000=100). É isso que vai pro SQL "
           "(`CPIUS:alt_{measure}`, data_type=SA, 9 series).", 3),
    _to_md(yoy_derived, "YoY derivado do index — últimos 12 meses (%)",
           "`yoy_derived[t] = idx[t]/idx[t-12] - 1`. Tem que bater YoY publicado "
           "(próxima tabela).", 3),
    _to_md(yoy_pub, "YoY publicado — últimos 12 meses (%)",
           "`ann_12mo` do CSV, direto de Atlanta/Cleveland chartdata.", 3),
    _to_md(yoy_diff, "YoY — diff (derivado − publicado), últimos 12 meses (pp)",
           "Qualquer valor fora de ±0.01pp indica round-trip de precisão (xlsx) "
           "ou bug na chain. Spot check visual.", 4),
    _to_md(mom_derived, "MoM derivado do index — últimos 12 meses (%)",
           "`mom_derived[t] = idx[t]/idx[t-1] - 1`.", 4),
    _to_md(mom_pub, "MoM publicado (mom_sa proxy) — últimos 12 meses (%)",
           "`mom_sa = (1+ann_1mo/100)^(1/12) - 1` do CSV. Chain inverte o ann_1mo "
           "pra MoM, chain em MoM, re-derivação deveria dar o mesmo MoM.", 4),
    _to_md(mom_diff, "MoM — diff (derivado − publicado), últimos 12 meses (pp)",
           "Deve ser `0.0000` exato pq a chain usa literalmente o mesmo `mom_sa` "
           "pra encadear → re-derivação é identidade.", 4),
]

OUT.write_text("\n".join(md), encoding="utf-8")
print(f"[OK] {OUT.relative_to(ROOT)} — last={last:%Y-%m}, 9 measures.")
