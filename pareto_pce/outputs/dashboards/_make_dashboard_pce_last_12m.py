#!/usr/bin/env python3
# Dashboard markdown last-12m das metricas PCE que vao pro SQL corp:
#  - Alt measures (2): Median Cleveland + Trimmed Mean Dallas
#  - Diffusion (5 series): Headline, Goods, Services, Goods_ex_cars x YoY + 6m-ann
#  - Breadth (3 series): below_0 / 0_to_3 / above_3, ponderado por nominais BEA
# Fonte: pce_alt_measures.csv + pce_diffusion.csv + pce_breadth.csv.

from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent.parent
OUT = ROOT / "outputs" / "dashboards" / "dashboard_pce_last_12m.md"

ALT_LABELS = {
    "median_pce":       "Median (Cleveland)",
    "trimmed_mean_pce": "Trimmed Mean (Dallas)",
}
ALT_ORDER = ["median_pce", "trimmed_mean_pce"]

DIFF_LABELS = {
    "Headline":      "Headline (todos itens)",
    "Goods":         "Goods",
    "Goods_ex_cars": "Goods ex cars",
    "Services":      "Services",
}
DIFF_ORDER = ["Headline", "Goods", "Goods_ex_cars", "Services"]

BIN_LABELS = {
    "below_0pct": "YoY < 0%",
    "0_to_3pct":  "0% ≤ YoY ≤ 3%",
    "above_3pct": "YoY > 3%",
}
BIN_ORDER = ["below_0pct", "0_to_3pct", "above_3pct"]


def date_window(last: pd.Timestamp, n: int = 12) -> list[pd.Timestamp]:
    start = (last - pd.DateOffset(months=n - 1)).replace(day=1)
    return list(pd.date_range(start, last, freq="MS"))


def to_md(p: pd.DataFrame, title: str, note: str, digits: int = 2) -> str:
    out = [f"### {title}", "", note, ""]
    hdr = ["Série"] + list(p.columns)
    out.append("| " + " | ".join(hdr) + " |")
    out.append("|" + "|".join([":---"] + ["---:"] * len(p.columns)) + "|")
    for name, row in p.iterrows():
        cells = [name] + ["n/a" if pd.isna(v) else f"{v:.{digits}f}" for v in row.values]
        out.append("| " + " | ".join(cells) + " |")
    out.append("")
    return "\n".join(out)


# ---------- alt measures ----------
alt = pd.read_csv(ROOT / "data" / "pce_alt_measures.csv", parse_dates=["date"])
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

alt_idx     = alt_pivot("value_index")
alt_1mo     = alt_pivot("ann_1mo")
alt_mom_sa  = alt_pivot("mom_sa")
alt_yoy     = alt_pivot("ann_12mo")

# ---------- diffusion ----------
di = pd.read_csv(ROOT / "data" / "pce_diffusion.csv", parse_dates=["date"])
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
# 6m-ann so eh publicada pra Headline (mesma convencao do CPI); filtra pra
# evitar linha de n/a.
di_6ma = di_pivot("diffusion_6ma_ann_3pct").loc[[DIFF_LABELS["Headline"]]]

# ---------- breadth ----------
br = pd.read_csv(ROOT / "data" / "pce_breadth.csv", parse_dates=["date"])
br_last = br["date"].max()
br_dates = date_window(br_last)
br_cols = [d.strftime("%Y-%m") for d in br_dates]
br_pivot = br[br["date"].isin(br_dates)].pivot(
    index="bin", columns="date", values="weight_share"
)
br_pivot.columns = [c.strftime("%Y-%m") for c in br_pivot.columns]
br_pivot = br_pivot.reindex(index=BIN_ORDER, columns=br_cols)
br_pivot.index = [BIN_LABELS[b] for b in br_pivot.index]

# ---------- montagem ----------
md = [
    "# PCE dashboard — últimos 12 meses",
    "",
    f"**Alt measures last date**: {alt_last:%Y-%m}. "
    f"**Diffusion last date**: {di_last:%Y-%m}. "
    f"**Breadth last date**: {br_last:%Y-%m} "
    f"(pode defasar vs alt — depende do release BEA U20404+U20405).",
    "",
    "Gerado por `outputs/dashboards/_make_dashboard_pce_last_12m.py` em cima de "
    "`pce_alt_measures.csv` (Cleveland CSV + Dallas FRED), `pce_diffusion.csv` "
    "e `pce_breadth.csv` (BEA U20404 + nominais U20405, 190 leaves).",
    "",
    "> **Notas de cobertura**:",
    "> - Alt measures no SQL: 2 series `PCE:alt_{median_pce,trimmed_mean_pce}` "
    "(Index SA, rebase Jan/2000=100, sync 2026-10-28).",
    "> - Diffusion no SQL: 5 series `PCE:diffusion_{headline,goods,services,goods_ex_cars}_yoy` "
    "+ `PCE:diffusion_headline_6ma_ann` (count-based, nao ponderado).",
    "> - Breadth no SQL: 3 series `PCE:breadth_{above_3pct,0_to_3pct,below_0pct}` "
    "(peso = nominais BEA U20405 do proprio mes; soma = 100% por data).",
    "> - Dallas IDs renomeados em 2026-10 (`PCETRIM1M158SFRBDAL` + "
    "`PCETRIM12M159SFRBDAL`) — antigos `680SFRBDAL` retornavam 404.",
    "> - Dallas `pcedata.xlsx` NAO e benchmark comparavel direto do breadth: "
    "Dallas mede MoM annualized sobre universe Trimmed Mean customizado (nao YoY "
    "sobre U20404). Correlacao observada ~0 em 2026-10-28.",
    "> - Diffusion 6m-ann > 3% so e publicada pra Headline (bate "
    "`build_diffusion.py`); Goods/Services nao tem essa metrica.",
    "",
    to_md(alt_idx, "Alt measures — Index level (SA, Jan/2000=100)",
          "Nível do índice que vai pro SQL (`PCE:alt_{measure}`, data_type=SA). "
          "Derivadas: YoY = idx[t]/idx[t-12]-1, MoM = idx[t]/idx[t-1]-1.", 3),
    to_md(alt_1mo, "Alt measures — 1-mo annualized (%)",
          "Taxa anualizada do mês. Cleveland Median (1977+ full history), "
          "Dallas Trimmed Mean (1977+ full history).", 2),
    to_md(alt_mom_sa, "Alt measures — proxy MoM SA (%)",
          "Variação mensal SA derivada do 1-mo annualized: "
          "`mom_sa = (1+ann_1mo/100)^(1/12)-1`. Mesma unidade do MoM SA do "
          "dash PCE principal (Haver).", 2),
    to_md(alt_yoy, "Alt measures — YoY (%)",
          "Variação 12 meses. Cleveland sai do CSV direto, Dallas do FRED "
          "`PCETRIM12M159SFRBDAL` (round-trip de 2 decimais pode criar diff "
          "~0.01pp vs derivado do index).", 2),
    to_md(di_yoy, "Diffusion — share de itens com YoY > 3% (%)",
          "Difusão item-level sobre 190 leaves do BEA U20404. Fração de itens "
          "com YoY acima de 3%, por bloco. Count-based, não ponderado.", 2),
    to_md(di_6ma, "Diffusion — share de itens com 6m-ann > 3% (%)",
          "Mesma difusão mas usando variação 6 meses anualizada (sinal mais "
          "tempestivo que YoY).", 2),
    to_md(br_pivot, "Breadth — share do peso por bin YoY (%)",
          "Cross-section de 190 leaves BEA U20404, agrupados em 3 bins de YoY "
          "e ponderados por nominais BEA U20405 do próprio mês. Soma dos 3 "
          "bins = 100 em cada mês. Guard de cobertura 70% descarta releases "
          "parciais.", 2),
]

OUT.write_text("\n".join(md), encoding="utf-8")
print(f"[OK] {OUT.relative_to(ROOT)} — alt={alt_last:%Y-%m}, diff={di_last:%Y-%m}, "
      f"breadth={br_last:%Y-%m}, 12 meses.")
