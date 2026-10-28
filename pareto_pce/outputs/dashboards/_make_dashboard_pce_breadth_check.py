#!/usr/bin/env python3
# Dashboard markdown de validacao do breadth PCE:
#  - Last 24m detalhado + anchors long-run (medias anuais)
#  - Sanity: soma dos 3 bins = 100 por mes
#  - Regimes historicos (pre-COVID, COVID, post-COVID)
#  - Comparacao com diffusion (above_3 vs YoY>3 Headline)
# Fonte: data/pce_breadth.csv + data/pce_diffusion.csv.

from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent.parent
OUT = ROOT / "outputs" / "dashboards" / "dashboard_pce_breadth_check.md"
IN_BREADTH = ROOT / "data" / "pce_breadth.csv"
IN_DIFF    = ROOT / "data" / "pce_diffusion.csv"

BIN_LABELS = {
    "below_0pct": "YoY < 0%",
    "0_to_3pct":  "0% ≤ YoY ≤ 3%",
    "above_3pct": "YoY > 3%",
}
BIN_ORDER = ["below_0pct", "0_to_3pct", "above_3pct"]


def to_md(p: pd.DataFrame, title: str, note: str, digits: int = 2) -> str:
    out = [f"### {title}", "", note, ""]
    hdr = [p.index.name or "Série"] + list(p.columns)
    out.append("| " + " | ".join(hdr) + " |")
    out.append("|" + "|".join([":---"] + ["---:"] * len(p.columns)) + "|")
    for name, row in p.iterrows():
        cells = [str(name)] + ["n/a" if pd.isna(v) else f"{v:.{digits}f}" for v in row.values]
        out.append("| " + " | ".join(cells) + " |")
    out.append("")
    return "\n".join(out)


br = pd.read_csv(IN_BREADTH, parse_dates=["date"])
di = pd.read_csv(IN_DIFF, parse_dates=["date"])

last = br["date"].max()

# ---------- last 24m detalhado ----------
last_24 = pd.date_range((last - pd.DateOffset(months=23)).replace(day=1), last, freq="MS")
br_pivot_24 = (br[br["date"].isin(last_24)]
                 .pivot(index="bin", columns="date", values="weight_share"))
br_pivot_24.columns = [c.strftime("%Y-%m") for c in br_pivot_24.columns]
br_pivot_24 = br_pivot_24.reindex(index=BIN_ORDER)
br_pivot_24.index = [BIN_LABELS[b] for b in br_pivot_24.index]
br_pivot_24.index.name = "Bin"

# ---------- anchors anuais (media por ano calendario) ----------
br_annual = br.copy()
br_annual["year"] = br_annual["date"].dt.year
annual = (br_annual.groupby(["year", "bin"])["weight_share"].mean()
                   .unstack("bin")
                   [BIN_ORDER])
annual.columns = [BIN_LABELS[b] for b in annual.columns]
annual.index.name = "Ano"

# ---------- regimes historicos ----------
REGIMES = [
    ("Pre-COVID (2001-2019)", (2001, 2019)),
    ("COVID (2020-2021)",      (2020, 2021)),
    ("Pos-COVID (2022-corrente)", (2022, int(last.year))),
    ("Ultimo ano (12m)",       None),
]
rows = []
for label, period in REGIMES:
    if period is None:
        sub = br[br["date"] > last - pd.DateOffset(months=12)]
    else:
        y0, y1 = period
        sub = br[(br["date"].dt.year >= y0) & (br["date"].dt.year <= y1)]
    pv = sub.groupby("bin")["weight_share"].mean().reindex(BIN_ORDER)
    rows.append({"Regime": label, **{BIN_LABELS[b]: pv.loc[b] for b in BIN_ORDER}})
regimes = pd.DataFrame(rows).set_index("Regime")

# ---------- sanity ----------
sanity = br.groupby("date")["weight_share"].sum()
n_bad = int((sanity - 100).abs().gt(0.01).sum())
sanity_summary = pd.DataFrame({
    "min_sum": [sanity.min()],
    "max_sum": [sanity.max()],
    "mean_sum": [sanity.mean()],
    "n_datas": [len(sanity)],
    "n_bad (|sum-100|>0.01)": [n_bad],
}, index=["Soma 3 bins por data"])

# ---------- cross-check vs diffusion Headline (above_3 breadth vs YoY>3 Headline) ----------
# Diffusion = count-based (share de ITENS, nao peso). Breadth above_3 = peso.
# Nao deveriam bater exato — se baterem muito proximos, universe ta similar.
di_h = di[(di["aggregate"] == "Headline") & (di["metric"] == "diffusion_yoy_3pct")]
br_a = br[br["bin"] == "above_3pct"]
cross = (br_a[["date", "weight_share"]].rename(columns={"weight_share": "above_3_breadth_pct"})
         .merge(di_h[["date", "value"]].rename(columns={"value": "yoy_gt_3_diffusion_pct"}),
                on="date", how="inner"))
cross["diff_pp"] = cross["above_3_breadth_pct"] - cross["yoy_gt_3_diffusion_pct"]
cross_last_12 = cross.tail(12).set_index("date")
cross_last_12.index = cross_last_12.index.strftime("%Y-%m")
cross_last_12.index.name = "Mes"
corr = cross["above_3_breadth_pct"].corr(cross["yoy_gt_3_diffusion_pct"])

# ---------- montagem ----------
md = [
    "# PCE breadth — validação e visão long-run",
    "",
    f"**Last date**: {last:%Y-%m}. **Janela**: {br['date'].min():%Y-%m} → {last:%Y-%m} "
    f"({br['date'].nunique()} datas, {len(br)} rows).",
    "",
    "Fonte: `data/pce_breadth.csv` (gerado por `scripts/build_breadth_pce.py` em "
    "cima do BEA U20404 + U20405). 190 leaves do U20404, peso = nominais do próprio "
    "mês, 3 bins de YoY. Soma dos 3 bins = 100% por data (sanity automático).",
    "",
    "Esse dashboard mostra:",
    "1. **Last 24m detalhado** — valor exato por mês × bin.",
    "2. **Médias anuais** — anchors long-run pra identificar regime shifts.",
    "3. **Regimes** — pre-COVID vs COVID vs pós-COVID vs último ano.",
    "4. **Sanity** — soma dos 3 bins em cada data.",
    "5. **Cross-check vs diffusion Headline** — breadth usa peso (nominais BEA), "
    "diffusion usa count (fração de itens). Divergência esperada; a direção "
    "deve correlacionar.",
    "",
    to_md(br_pivot_24, "Breadth — últimos 24 meses (%)",
          "Share do peso agregado dos 190 leaves em cada bin YoY. "
          "Nominais BEA U20405 do próprio mês como peso. Soma = 100 por coluna.", 2),
    to_md(annual.round(2), "Breadth — média anual por ano calendário (%)",
          "Média simples dos valores mensais dentro de cada ano. "
          "Útil pra ver drift de longo prazo (ex.: expansão da região >3% em "
          "2021-2022, retração em 2023+).", 2),
    to_md(regimes.round(2), "Breadth — média por regime macro (%)",
          "4 regimes: pré-COVID (2001-2019), COVID (2020-2021), pós-COVID "
          "(2022-corrente), último ano (12m rolling). Reposicionamento das 3 "
          "bins ao longo dos regimes.", 2),
    to_md(sanity_summary.round(4), "Sanity check — soma dos 3 bins deve ser 100",
          "Valores próximos de 100 confirmam integridade da renormalização. "
          "`n_bad` = quantidade de datas com |soma−100| > 0.01.", 4),
    to_md(cross_last_12.round(2), "Cross-check — breadth above_3 vs diffusion Headline YoY>3 (%)",
          f"Métrica diferente: breadth = share do PESO (nominais BEA), diffusion "
          f"= share dos ITENS (count). Divergência esperada; "
          f"**correlação histórica = {corr:+.3f}** (toda a janela). Último ano:", 2),
]

OUT.write_text("\n".join(md), encoding="utf-8")
print(f"[OK] {OUT.relative_to(ROOT)} — last={last:%Y-%m}, "
      f"{br['date'].nunique()} datas, correlação breadth×diff Headline = {corr:+.3f}.")
