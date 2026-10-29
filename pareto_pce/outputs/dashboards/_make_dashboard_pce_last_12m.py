#!/usr/bin/env python3
# Dashboard markdown last-12m das metricas PCE que vao pro SQL corp:
#  - Alt measures scraped (2): Median Cleveland + Trimmed Mean Dallas
#  - Alt measures proxy  (2): Median + Trim Mean bottom-up Itau
#  - Diffusion (5 series): Headline, Goods, Services, Goods_ex_cars x YoY + 6m-ann
#  - Breadth (3 series): below_0 / 0_to_3 / above_3, ponderado por nominais BEA
# Fonte: pce_alt_measures.csv + pce_alt_measures_proxy.csv +
#        pce_diffusion.csv + pce_breadth.csv.

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

# ---------- alt measures proxy (bottom-up Itau) ----------
alt_c = pd.read_csv(ROOT / "data" / "pce_alt_measures_proxy.csv", parse_dates=["date"])
ALT_PROXY_LABELS = {
    "median_pce_proxy":              "Median (proxy bottom-up)",
    "trimmed_mean_pce_proxy":        "Trimmed Mean (proxy bottom-up)",
    "median_pce_goods_proxy":        "Median Goods (proxy)",
    "trimmed_mean_pce_goods_proxy":  "Trimmed Mean Goods (proxy)",
    "median_pce_services_proxy":     "Median Services (proxy)",
    "trimmed_mean_pce_services_proxy": "Trimmed Mean Services (proxy)",
}
# ORDER só pros 2 headline (combined view). G/S saem num bloco separado.
ALT_PROXY_ORDER = ["median_pce_proxy", "trimmed_mean_pce_proxy"]
ALT_PROXY_GS_ORDER = [
    "median_pce_goods_proxy", "median_pce_services_proxy",
    "trimmed_mean_pce_goods_proxy", "trimmed_mean_pce_services_proxy",
]

def alt_proxy_pivot(col: str) -> pd.DataFrame:
    sub = alt_c[alt_c["date"].isin(alt_dates)]
    p = sub.pivot(index="measure", columns="date", values=col)
    p.columns = [c.strftime("%Y-%m") for c in p.columns]
    p = p.reindex(index=ALT_PROXY_ORDER, columns=alt_cols)
    p.index = [ALT_PROXY_LABELS[m] for m in p.index]
    return p

alt_c_idx    = alt_proxy_pivot("value_index")
alt_c_1mo    = alt_proxy_pivot("ann_1mo")
alt_c_mom_sa = alt_proxy_pivot("mom_sa")
alt_c_yoy    = alt_proxy_pivot("ann_12mo")

def alt_proxy_gs_pivot(col: str) -> pd.DataFrame:
    """So os 4 G/S proxies, sem oficial pareado (G/S nao tem oficial Fed)."""
    sub = alt_c[alt_c["date"].isin(alt_dates)]
    p = sub.pivot(index="measure", columns="date", values=col)
    p.columns = [c.strftime("%Y-%m") for c in p.columns]
    p = p.reindex(index=ALT_PROXY_GS_ORDER, columns=alt_cols)
    p.index = [ALT_PROXY_LABELS[m] for m in p.index]
    return p

alt_gs_yoy = alt_proxy_gs_pivot("ann_12mo")
alt_gs_1mo = alt_proxy_gs_pivot("ann_1mo")

# ---------- combined view: oficial + proxy side-by-side ----------
# Alt measures scraped vs proxy em uma única tabela por métrica (4 linhas).
def alt_combined_pivot(col_scraped: str, col_proxy: str = None) -> pd.DataFrame:
    """Empilha scraped (2 linhas) + proxy (2 linhas) na mesma pivot."""
    col_proxy = col_proxy or col_scraped
    scraped = alt_pivot(col_scraped)
    proxy_df = alt_proxy_pivot(col_proxy)
    combined = pd.concat([scraped, proxy_df])
    return combined

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
# MoM > 0 — impulso corrente (adicionado 2026-10-29), 4 agregados
di_mom = di_pivot("diffusion_mom_above_0")

# ---------- altas distribution (5 bins Dallas-style MoM SAAR) ----------
ad = pd.read_csv(ROOT / "data" / "pce_altas_distribution.csv", parse_dates=["date"])
ad_last = ad["date"].max()
ad_dates = date_window(ad_last)
ad_cols = [d.strftime("%Y-%m") for d in ad_dates]
AD_LABELS = {
    "0_to_2":        "0-2% MoM SAAR",
    "2_to_3":        "2-3%",
    "3_to_5":        "3-5%",
    "5_to_10":       "5-10%",
    "gt_10":         ">10%",
    "zero_or_below": "≤ 0% (deflationary)",
}
AD_ORDER = ["0_to_2", "2_to_3", "3_to_5", "5_to_10", "gt_10", "zero_or_below"]
ad_pivot = ad[ad["date"].isin(ad_dates)].pivot(
    index="bin", columns="date", values="weight_share"
)
ad_pivot.columns = [c.strftime("%Y-%m") for c in ad_pivot.columns]
ad_pivot = ad_pivot.reindex(index=AD_ORDER, columns=ad_cols)
ad_pivot.index = [AD_LABELS[b] for b in ad_pivot.index]

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
    "`pce_alt_measures.csv` (Cleveland CSV + Dallas FRED, scraped), "
    "`pce_alt_measures_proxy.csv` (bottom-up Itaú), `pce_diffusion.csv` e "
    "`pce_breadth.csv` (BEA U20404 + nominais U20405, 190 leaves).",
    "",
    "> **Notas de cobertura**:",
    "> - Alt measures scraped no SQL: 2 series `PCE:alt_{median_pce,trimmed_mean_pce}` "
    "(Index SA, rebase Jan/2000=100, sync 2026-10-28).",
    "> - Alt measures proxy no SQL: **6 series** (2 headline + 4 Goods/Services). "
    "Headline validado 2026-10-28: mean|d| YoY = 0.09-0.11pp vs scraped. "
    "G/S sao proxy puro — Cleveland/Dallas nao publicam decomposicao.",
    "> - Diffusion no SQL: **9 series** = 4 YoY>3% + 1 6m-ann>3% (headline) + "
    "4 MoM>0% (adicionado 2026-10-29). MoM>0 mede impulso corrente, YoY>3 mede "
    "escala estrutural — analises diferentes.",
    "> - Breadth no SQL: 3 series `PCE:breadth_{above_3pct,0_to_3pct,below_0pct}` "
    "(peso = nominais BEA U20405 do proprio mes; soma = 100% por data).",
    "> - Altas distribution no SQL: 5 series `PCE:altas_dist_{0_2,2_3,3_5,5_10,gt_10}` "
    "(mesmo pesos, mas em bins de MoM SAAR em vez de YoY — estilo Dallas pcedata.xlsx; "
    "bin `zero_or_below` fica so no CSV, nao sobe pro SQL).",
    "> - Dallas IDs renomeados em 2026-10 (`PCETRIM1M158SFRBDAL` + "
    "`PCETRIM12M159SFRBDAL`) — antigos `680SFRBDAL` retornavam 404.",
    "> - Dallas `pcedata.xlsx` NAO e benchmark comparavel direto do breadth: "
    "Dallas mede MoM annualized sobre universe Trimmed Mean customizado (nao YoY "
    "sobre U20404). Correlacao observada ~0 em 2026-10-28.",
    "> - Diffusion 6m-ann > 3% so e publicada pra Headline (bate "
    "`build_diffusion.py`); Goods/Services nao tem essa metrica.",
    "",
    to_md(alt_combined_pivot("value_index"),
          "Alt measures — Index level (SA, Jan/2000=100)",
          "Nível do índice que vai pro SQL. **4 series**: 2 scraped (Cleveland "
          "CSV + Dallas FRED) + 2 proxy (bottom-up Itaú em cima dos 190 leaves). "
          "Jan/2000=100 por construção.", 3),
    to_md(alt_combined_pivot("ann_1mo"),
          "Alt measures — 1-mo annualized (%)",
          "Taxa anualizada do mês. Scraped vs proxy em paralelo — proximidade "
          "mês-a-mês indica se o universe/metodologia bota conta parecida.", 2),
    to_md(alt_combined_pivot("mom_sa"),
          "Alt measures — proxy MoM SA (%)",
          "Variação mensal SA derivada do 1-mo annualized: "
          "`mom_sa = (1+ann_1mo/100)^(1/12)-1`.", 3),
    to_md(alt_combined_pivot("ann_12mo"),
          "Alt measures — YoY (%)",
          "Variação 12 meses. Scraped vs proxy: diffs esperados < 0.5pp mês-a-mês "
          "(mean|d| global = 0.09pp Trim Mean / 0.11pp Median — validado em "
          "`dashboard_pce_alt_proxy_vs_official.md`).", 2),
    to_md(alt_gs_yoy, "Alt measures proxy Goods/Services — YoY (%)",
          "Reconstrução bottom-up aplicada só nos leaves Goods (90) ou "
          "Services (100). **Sem oficial Fed pra comparar** — Cleveland/Dallas "
          "só publicam headline. Esperado Services > Goods em YoY (sticky vs "
          "cíclico).", 2),
    to_md(alt_gs_1mo, "Alt measures proxy Goods/Services — 1-mo annualized (%)",
          "Mesma decomposição em taxa anualizada mensal.", 2),
    to_md(di_yoy, "Diffusion — share de itens com YoY > 3% (%)",
          "Difusão item-level sobre 190 leaves do BEA U20404. Fração de itens "
          "com YoY acima de 3%, por bloco. Count-based, não ponderado.", 2),
    to_md(di_6ma, "Diffusion — share de itens com 6m-ann > 3% (%)",
          "Mesma difusão mas usando variação 6 meses anualizada (sinal mais "
          "tempestivo que YoY).", 2),
    to_md(di_mom, "Diffusion — share de itens com MoM > 0% (%)",
          "**Impulso corrente do mês**: fração de leaves com MoM positiva "
          "vs deflationary. Threshold 0 (não 3) — mede quão **amplo** é o "
          "aumento de preço, independente de magnitude. Sinal mais tempestivo "
          "que YoY (que carrega 12m de bagagem).", 2),
    to_md(br_pivot, "Breadth — share do peso por bin YoY (%)",
          "Cross-section de 190 leaves BEA U20404, agrupados em 3 bins de YoY "
          "e ponderados por nominais BEA U20405 do próprio mês. Soma dos 3 "
          "bins = 100 em cada mês. Guard de cobertura 70% descarta releases "
          "parciais.", 2),
    to_md(ad_pivot, "Altas distribution — share do peso por bin MoM SAAR (%)",
          "Decomposição do share positivo em 5 bins Dallas-style (0-2 / 2-3 / "
          "3-5 / 5-10 / >10%) + bin complemento `≤ 0`. Mesmos 190 leaves + "
          "nominais, mas em magnitude de MoM SAAR em vez de YoY. Soma 6 bins = "
          "100%. Pros 5 bins positivos vão pro SQL `PCE:altas_dist_*`; "
          "`zero_or_below` fica só no CSV (derivável = 100 − Σ(5)).", 2),
]

OUT.write_text("\n".join(md), encoding="utf-8")
print(f"[OK] {OUT.relative_to(ROOT)} — alt={alt_last:%Y-%m}, diff={di_last:%Y-%m}, "
      f"breadth={br_last:%Y-%m}, 12 meses.")
