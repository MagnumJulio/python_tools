#!/usr/bin/env python3
# Dashboard markdown comparando alt measures PCE custom bottom-up vs
# scraped oficial (Cleveland CSV / Dallas FRED):
#  - Mean|d|, max|d|, correlacao global
#  - Side-by-side YoY last 24m
#  - YoY diff (custom - official) last 24m
#  - Divergencia em pontos chave (COVID, pos-COVID, 2024-2025)
# Fonte: data/pce_alt_measures.csv + data/pce_alt_measures_custom.csv.

from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent.parent
OUT = ROOT / "outputs" / "dashboards" / "dashboard_pce_alt_custom_vs_official.md"
IN_OFFICIAL = ROOT / "data" / "pce_alt_measures.csv"
IN_CUSTOM   = ROOT / "data" / "pce_alt_measures_custom.csv"

PAIRS = [
    ("Median PCE",       "median_pce",       "median_pce_custom"),
    ("Trimmed Mean PCE", "trimmed_mean_pce", "trimmed_mean_pce_custom"),
]


def to_md(p: pd.DataFrame, title: str, note: str, digits: int = 3) -> str:
    out = [f"### {title}", "", note, ""]
    hdr = [p.index.name or "Série"] + list(p.columns)
    out.append("| " + " | ".join(hdr) + " |")
    out.append("|" + "|".join([":---"] + ["---:"] * len(p.columns)) + "|")
    for name, row in p.iterrows():
        cells = [str(name)] + ["n/a" if pd.isna(v) else f"{v:.{digits}f}" for v in row.values]
        out.append("| " + " | ".join(cells) + " |")
    out.append("")
    return "\n".join(out)


off = pd.read_csv(IN_OFFICIAL, parse_dates=["date"])
cst = pd.read_csv(IN_CUSTOM, parse_dates=["date"])

last = min(off["date"].max(), cst["date"].max())
last_24 = pd.date_range((last - pd.DateOffset(months=23)).replace(day=1), last, freq="MS")

# ---------- summary stats por pair ----------
summary_rows = []
for label, off_m, cst_m in PAIRS:
    o = off[off["measure"] == off_m][["date", "ann_12mo", "value_index"]].rename(
        columns={"ann_12mo": "yoy_off", "value_index": "idx_off"})
    c = cst[cst["measure"] == cst_m][["date", "ann_12mo", "value_index"]].rename(
        columns={"ann_12mo": "yoy_cst", "value_index": "idx_cst"})
    m = o.merge(c, on="date", how="inner").dropna(subset=["yoy_off", "yoy_cst"])
    if m.empty:
        continue
    diff_yoy = (m["yoy_cst"] - m["yoy_off"]).abs()
    diff_idx = (m["idx_cst"] - m["idx_off"]).abs() / m["idx_off"] * 100  # % diff
    summary_rows.append({
        "Pair": label,
        "n_overlap": len(m),
        "mean|d_yoy| (pp)": diff_yoy.mean(),
        "max|d_yoy| (pp)":  diff_yoy.max(),
        "corr_yoy":          m["yoy_cst"].corr(m["yoy_off"]),
        "mean|d_idx| (%)":  diff_idx.mean(),
        "corr_idx":          m["idx_cst"].corr(m["idx_off"]),
    })
summary = pd.DataFrame(summary_rows).set_index("Pair")

# ---------- YoY side-by-side last 24m ----------
def yoy_pivot(measure_col: str) -> pd.DataFrame:
    """Pivot YoY values over last 24m for both official and custom."""
    rows = []
    for label, off_m, cst_m in PAIRS:
        o = off[(off["measure"] == off_m) & (off["date"].isin(last_24))][["date", "ann_12mo"]]
        c = cst[(cst["measure"] == cst_m) & (cst["date"].isin(last_24))][["date", "ann_12mo"]]
        for _, r in o.iterrows():
            rows.append({"serie": f"{label} — official", "date": r["date"], "value": r["ann_12mo"]})
        for _, r in c.iterrows():
            rows.append({"serie": f"{label} — custom",   "date": r["date"], "value": r["ann_12mo"]})
    df = pd.DataFrame(rows)
    p = df.pivot(index="serie", columns="date", values="value")
    p.columns = [d.strftime("%Y-%m") for d in p.columns]
    order = [f"{lbl} — {kind}" for lbl, _, _ in PAIRS for kind in ("official", "custom")]
    p = p.reindex(index=order, columns=[d.strftime("%Y-%m") for d in last_24])
    p.index.name = "Serie (YoY %)"
    return p

yoy_side = yoy_pivot("ann_12mo")

# ---------- YoY diff pivot ----------
diff_rows = []
for label, off_m, cst_m in PAIRS:
    o = off[(off["measure"] == off_m) & (off["date"].isin(last_24))][["date", "ann_12mo"]].set_index("date")["ann_12mo"]
    c = cst[(cst["measure"] == cst_m) & (cst["date"].isin(last_24))][["date", "ann_12mo"]].set_index("date")["ann_12mo"]
    for d in last_24:
        if d in o.index and d in c.index:
            diff_rows.append({"Pair": label, "date": d, "diff_pp": c.loc[d] - o.loc[d]})
df_diff = pd.DataFrame(diff_rows)
diff_pivot = df_diff.pivot(index="Pair", columns="date", values="diff_pp")
diff_pivot.columns = [d.strftime("%Y-%m") for d in diff_pivot.columns]
diff_pivot = diff_pivot.reindex(columns=[d.strftime("%Y-%m") for d in last_24])
diff_pivot.index.name = "Pair (diff YoY %, custom − official)"

# ---------- regimes macro ----------
regimes = [
    ("Pre-COVID (2001-2019)",  (2001, 2019)),
    ("COVID (2020-2021)",      (2020, 2021)),
    ("Pos-COVID (2022-atual)", (2022, int(last.year))),
    ("Ultimo ano (12m)",       None),
]
reg_rows = []
for label, period in regimes:
    row = {"Regime": label}
    for pair_label, off_m, cst_m in PAIRS:
        o = off[off["measure"] == off_m]
        c = cst[cst["measure"] == cst_m]
        if period is None:
            o = o[o["date"] > last - pd.DateOffset(months=12)]
            c = c[c["date"] > last - pd.DateOffset(months=12)]
        else:
            y0, y1 = period
            o = o[(o["date"].dt.year >= y0) & (o["date"].dt.year <= y1)]
            c = c[(c["date"].dt.year >= y0) & (c["date"].dt.year <= y1)]
        row[f"{pair_label} off"] = o["ann_12mo"].mean()
        row[f"{pair_label} cst"] = c["ann_12mo"].mean()
    reg_rows.append(row)
reg_df = pd.DataFrame(reg_rows).set_index("Regime")

md = [
    "# PCE alt measures — custom bottom-up vs oficial (Cleveland/Dallas)",
    "",
    f"**Last date**: {last:%Y-%m}. Fonte: `pce_alt_measures.csv` (official) + "
    f"`pce_alt_measures_custom.csv` (bottom-up Itau).",
    "",
    "Pedido 2026-10-28: ter os 2 lado-a-lado no SQL pra decomposição e "
    "sensibilidade — **não substitui o oficial**. O custom permite:",
    "- Perguntar \"se eu mudasse o universo / o trim, o que aconteceria?\"",
    "- Decompor quais itens explicam o gap com o oficial",
    "- Entender a sensibilidade da métrica a mudanças metodológicas",
    "",
    "**Metodologia custom** (bottom-up em cima dos 190 leaves U20404 + U20405):",
    "- **Median**: weighted 50th percentile de MoM SAAR (peso = nominais U20405 do mês)",
    "- **Trimmed Mean**: trim **24% low + 31% high** (asimétrico Dallas, calibrado "
    "pra bater headline no long run)",
    "- Chain universal pra value_index (idx[t] = idx[t-1]·(1+mom[t])), rebase Jan/2000=100",
    "",
    "**Threshold mental**:",
    "- `mean|d_yoy|` < 0.3pp → bom, custom é tool de análise confiável",
    "- `mean|d_yoy|` < 0.5pp → aceitável, mas custom diverge o suficiente pra ser citado como \"estimativa Itaú\"",
    "- `mean|d_yoy|` > 1pp → vira só análise interna, não deliverable",
    "",
    to_md(summary.round(3), "Chain fidelity custom vs oficial — stats globais",
          "YoY: ambas rebase Jan/2000=100 por construção. Index diff relativo "
          "(%) mede desvio acumulado da reconstrução.", 3),
    to_md(yoy_side.round(2), "YoY last 24m — side-by-side custom vs official",
          "Cada par (Measure × Pipeline) aparece como linha separada pra comparação "
          "visual direta.", 2),
    to_md(diff_pivot.round(3), "YoY diff last 24m (custom − official, em pp)",
          "Valores próximos de 0 = reconstrução perfeita. Positivo = nosso está "
          "acima do oficial.", 3),
    to_md(reg_df.round(3), "YoY médio por regime macro — custom vs oficial",
          "Média do YoY em cada regime macro. Mostra se a divergência varia por "
          "contexto (ex.: custom pode subestimar em COVID se nominais trimestrais "
          "atrasam, ou se trim/median comportam diferente em cauda larga).", 3),
]

OUT.write_text("\n".join(md), encoding="utf-8")
print(f"[OK] {OUT.relative_to(ROOT)} — last={last:%Y-%m}.")
for _, r in summary.round(3).iterrows():
    print(f"  {r.name}: mean|d_yoy|={r['mean|d_yoy| (pp)']}pp "
          f"(corr={r['corr_yoy']})")
