#!/usr/bin/env python3
# Dashboard markdown da distribuicao de altas PCE (estilo Dallas):
#  - Last 24m detalhado (5 bins + complemento)
#  - Benchmark side-by-side vs Dallas pcedata.xlsx (13 meses de overlap)
#  - Correlacao por bin
#  - Media por regime macro
# Fonte: data/pce_altas_distribution.csv + data/raw/dallas/pcedata.xlsx.

from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent.parent
OUT = ROOT / "outputs" / "dashboards" / "dashboard_pce_altas_distribution.md"
IN_DIST   = ROOT / "data" / "pce_altas_distribution.csv"
IN_DALLAS = ROOT / "data" / "raw" / "dallas" / "pcedata.xlsx"

BIN_LABELS = {
    "0_to_2":        "0-2% MoM SAAR",
    "2_to_3":        "2-3% MoM SAAR",
    "3_to_5":        "3-5% MoM SAAR",
    "5_to_10":       "5-10% MoM SAAR",
    "gt_10":         ">10% MoM SAAR",
    "zero_or_below": "<= 0% (deflationary)",
}
BIN_ORDER_DALLAS = ["0_to_2", "2_to_3", "3_to_5", "5_to_10", "gt_10"]
BIN_ORDER_ALL = BIN_ORDER_DALLAS + ["zero_or_below"]


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


# ---------- nossa dist ----------
dist = pd.read_csv(IN_DIST, parse_dates=["date"])
last = dist["date"].max()

last_24 = pd.date_range((last - pd.DateOffset(months=23)).replace(day=1), last, freq="MS")
piv_24 = (dist[dist["date"].isin(last_24)]
             .pivot(index="bin", columns="date", values="weight_share"))
piv_24.columns = [c.strftime("%Y-%m") for c in piv_24.columns]
piv_24 = piv_24.reindex(index=BIN_ORDER_ALL)
piv_24.index = [BIN_LABELS[b] for b in piv_24.index]
piv_24.index.name = "Bin"

# ---------- Dallas pcedata.xlsx ----------
dallas_raw = pd.read_excel(IN_DALLAS, sheet_name=0, header=None)
dallas_dates = pd.to_datetime(dallas_raw.iloc[2, 1:].values)
dallas_vals = dallas_raw.iloc[3:8, 1:].values.astype(float)
dallas = pd.DataFrame(dallas_vals.T, index=dallas_dates,
                      columns=BIN_ORDER_DALLAS)
dallas["zero_or_below"] = 100 - dallas.sum(axis=1)

# Overlap janela
overlap_dates = sorted(set(dist["date"].unique()) & set(dallas.index))
mine_overlap = (dist[dist["date"].isin(overlap_dates)]
                   .pivot(index="date", columns="bin", values="weight_share")
                   [BIN_ORDER_ALL])
dallas_overlap = dallas.loc[overlap_dates, BIN_ORDER_ALL]

# ---------- side-by-side ultimo mes ----------
last_overlap = pd.Timestamp(overlap_dates[-1])
side = pd.DataFrame({
    "Nosso (190 leaves U20404)":   mine_overlap.loc[last_overlap],
    "Dallas (Trimmed Mean universe)": dallas_overlap.loc[last_overlap],
})
side["Diff (pp)"] = side["Nosso (190 leaves U20404)"] - side["Dallas (Trimmed Mean universe)"]
side.index = [BIN_LABELS[b] for b in side.index]
side.index.name = f"Bin ({last_overlap:%Y-%m})"

# ---------- medias historicas ----------
hist = pd.DataFrame({
    "Nossa media (janela overlap)":   mine_overlap.mean(),
    "Dallas media (janela overlap)":  dallas_overlap.mean(),
})
hist["Diff (pp)"] = hist["Nossa media (janela overlap)"] - hist["Dallas media (janela overlap)"]
hist.index = [BIN_LABELS[b] for b in hist.index]
hist.index.name = "Bin"

# ---------- correlacao por bin ----------
corr_rows = []
for b in BIN_ORDER_ALL:
    corr_rows.append({
        "Bin": BIN_LABELS[b],
        "Correlacao": mine_overlap[b].corr(dallas_overlap[b]),
        "n_overlap": len(mine_overlap[b].dropna()),
    })
corr = pd.DataFrame(corr_rows).set_index("Bin")

# ---------- regimes macro (nossa serie, janela completa) ----------
dist["year"] = dist["date"].dt.year
annual = (dist.groupby(["year", "bin"])["weight_share"].mean()
              .unstack("bin")
              [BIN_ORDER_ALL])
annual.columns = [BIN_LABELS[b] for b in annual.columns]
annual.index.name = "Ano"

REGIMES = [
    ("Pre-COVID (2001-2019)",  (2001, 2019)),
    ("COVID (2020-2021)",      (2020, 2021)),
    ("Pos-COVID (2022-atual)", (2022, int(last.year))),
    ("Ultimo ano (12m)",       None),
]
reg_rows = []
for label, period in REGIMES:
    if period is None:
        sub = dist[dist["date"] > last - pd.DateOffset(months=12)]
    else:
        y0, y1 = period
        sub = dist[(dist["date"].dt.year >= y0) & (dist["date"].dt.year <= y1)]
    pv = sub.groupby("bin")["weight_share"].mean().reindex(BIN_ORDER_ALL)
    reg_rows.append({"Regime": label, **{BIN_LABELS[b]: pv.loc[b] for b in BIN_ORDER_ALL}})
regimes = pd.DataFrame(reg_rows).set_index("Regime")

# ---------- sanity ----------
sanity = dist.groupby("date")["weight_share"].sum()
n_bad = int((sanity - 100).abs().gt(0.01).sum())
sanity_tbl = pd.DataFrame({
    "min_sum":  [sanity.min()],
    "max_sum":  [sanity.max()],
    "mean_sum": [sanity.mean()],
    "n_datas":  [len(sanity)],
    "n_bad":    [n_bad],
}, index=["Soma 6 bins por data"])

# ---------- montagem ----------
md = [
    "# PCE distribuição de altas — estilo Dallas Fed",
    "",
    f"**Last date**: {last:%Y-%m}. **Janela**: {dist['date'].min():%Y-%m} → {last:%Y-%m} "
    f"({dist['date'].nunique()} datas). **Overlap Dallas**: {len(overlap_dates)} meses "
    f"({overlap_dates[0]:%Y-%m} → {overlap_dates[-1]:%Y-%m}).",
    "",
    "Fonte: `data/pce_altas_distribution.csv` (gerado por "
    "`scripts/build_altas_distribution_pce.py` em cima do BEA U20404 + U20405). "
    "190 leaves do U20404, peso = nominais BEA do mês, bins de **MoM SAAR** "
    "(`((idx[t]/idx[t-1])^12 - 1)*100`). U20404 é SA — chain direto sem STL.",
    "",
    "**5 bins Dallas-style sobem pro SQL** (`PCE:dist_{0_2, 2_3, 3_5, "
    "5_10, gt_10}`). O 6º bin `zero_or_below` (deflationary) fica só no CSV; "
    "o analista deriva via `(100 - soma dos 5)` se precisar.",
    "",
    "**Benchmark Dallas pcedata.xlsx**: dessa vez a métrica é a MESMA (MoM "
    "SAAR, 5 bins); diferença é só o universo (190 leaves U20404 vs ~178 "
    "components do Trimmed Mean Dallas). Correlação por bin alta esperada e "
    "observada.",
    "",
    to_md(piv_24, "Distribuição de altas — últimos 24 meses (%)",
          "Share do peso dos 190 leaves em cada bin de MoM SAAR. Soma 6 bins = 100 "
          "por coluna.", 2),
    to_md(side.round(2), f"Side-by-side nosso vs Dallas ({last_overlap:%Y-%m}, último overlap)",
          "Diff positivo = nosso bin tem mais peso que Dallas. Diff ~0 pra bins "
          "altos (3-5, 5-10, >10) e zero_or_below; diferença concentra em "
          "0-2 e 2-3 por universo.", 2),
    to_md(hist.round(2), "Médias históricas (janela overlap, 13 meses)",
          "Média dos valores mensais na janela de overlap com Dallas.", 2),
    to_md(corr.round(3), "Correlação histórica por bin (overlap Dallas)",
          "Correlação de Pearson entre nossa serie e a serie Dallas pcedata.xlsx "
          "na janela de overlap. Valores altos (>0.85) confirmam que ambas medem "
          "o mesmo signal; diferença só no universo.", 3),
    to_md(regimes.round(2), "Distribuição por regime macro",
          "Média simples dos valores mensais em cada regime. Mostra reposição das "
          "6 bins ao longo do tempo (ex.: `>10%` saiu de ~3% pré-COVID pra ~17% em "
          "2022, caiu pra ~12% em 2025).", 2),
    to_md(sanity_tbl.round(4), "Sanity check — soma das 6 bins deve ser 100",
          "`n_bad` = quantidade de datas com |soma−100| > 0.01.", 4),
    to_md(annual.round(2), "Distribuição anual (média por ano calendário, %)",
          "Média mensal por ano. Útil pra ver drift long-run das 6 bins.", 2),
]

OUT.write_text("\n".join(md), encoding="utf-8")
print(f"[OK] {OUT.relative_to(ROOT)} — last={last:%Y-%m}, "
      f"{dist['date'].nunique()} datas, overlap Dallas={len(overlap_dates)}m. "
      f"Correlacao media = {corr['Correlacao'].mean():+.3f}.")
