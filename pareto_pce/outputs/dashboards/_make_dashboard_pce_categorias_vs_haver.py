#!/usr/bin/env python3
# Dashboard markdown de validacao: PCE categorias (BEA U20404+U20405 bottom-up)
# vs tabela Haver Analytics (ground truth). Compara:
#  - Weight (ultima data)
#  - MoM SA last 12 meses (Oct/25 → Sep/26)
#  - max|d| por categoria
# Fonte: data/pce_categorias_indice.csv + data/pce_categorias_pesos.csv.

from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent.parent
OUT = ROOT / "outputs" / "dashboards" / "dashboard_pce_categorias_vs_haver.md"
IDX_CSV = ROOT / "data" / "pce_categorias_indice.csv"
PESO_CSV = ROOT / "data" / "pce_categorias_pesos.csv"
MAP_CSV = ROOT / "scripts" / "bea_maps" / "pce_categorias.csv"

# ---- Haver reference (user-provided tabela, 2026-10-29) ----
# Columns: Oct/25 Nov/25 Dec/25 Jan/26 Feb/26 Mar/26 Apr/26 May/26 Jun/26 Jul/26 Aug/26 Sep/26
HAVER_HEADERS = ["2025-10", "2025-11", "2025-12", "2026-01", "2026-02", "2026-03",
                 "2026-04", "2026-05", "2026-06", "2026-07", "2026-08", "2026-09"]

HAVER_WEIGHT = {
    "all_items": 100.00, "core": 88.88, "goods": 31.08, "core_goods": 21.64,
    "durable_goods": 10.79, "motor_vehicles": 3.54, "furnishings": 2.39,
    "recreational_goods": 3.41, "other_durable": 1.44, "nondurable_goods": 20.29,
    "food_bev_offprem": 7.00, "clothing": 2.71, "gasoline": 2.44, "other_nondurable": 8.14,
    "services": 68.92, "services_ex_energy": 67.24, "services_ex_energy_housing": 51.63,
    "services_ex_energy_airfare_healthcare": 48.94,
    "services_ex_energy_housing_pubtrans_medical": 30.88,
    "housing": 15.61, "hh_consumption_services": 65.96, "housing_utilities": 17.94,
    "health_care": 17.24, "transportation_services": 3.51, "recreation_services": 3.82,
    "food_services_accom": 7.17, "financial_services_insurance": 8.05,
    "other_services": 8.21, "all_items_ex_food_energy_housing": 73.28,
    "food": 7.00, "energy": 4.12, "market_based": 86.36, "market_based_ex_food_energy": 75.25,
}

HAVER_MOM = {
    "all_items":                       [0.15,  0.20,  0.32,  0.30,  0.35,  0.63,  0.44,  0.44, -0.10,  0.06,  0.32,  0.49],
    "core":                            [0.18,  0.16,  0.32,  0.40,  0.34,  0.26,  0.28,  0.31,  0.13,  0.14,  0.26,  0.32],
    "goods":                           [-0.08, 0.12,  0.33,  0.04,  0.60,  1.38,  0.63,  0.46, -0.65, -0.10, 0.35,  0.80],
    "core_goods":                      [-0.01,-0.05,  0.36,  0.29,  0.65,  0.16,  0.19, -0.05, 0.03,  0.16,  0.05,  0.20],
    "durable_goods":                   [0.06, -0.03,  0.39,  0.38,  0.65,  0.31,  0.34,  0.09,-0.10,  0.40,  0.13,  0.24],
    "motor_vehicles":                  [0.19,  0.08, -0.25, -0.69, 0.22, -0.08, -0.09, -0.19, 0.05,  0.41, -0.02, 0.26],
    "furnishings":                     [0.00,  0.00,  0.79,  0.89, 0.30, -0.50, -0.13, -0.43, 0.14, -0.90, 0.03, -0.01],
    "recreational_goods":              [-0.27,-0.45,  1.31,  1.49, 1.03,  1.19,  0.85,  0.43, 0.52,  1.25, 0.54,  0.18],
    "other_durable":                   [0.60,  0.59, -0.80, -0.38, 1.43, 0.61,  1.02,  0.83,-2.30,  0.56,-0.28,  0.72],
    "nondurable_goods":                [-0.15, 0.20,  0.30, -0.14, 0.58, 1.96,  0.79,  0.66,-0.94, -0.36, 0.47,  1.11],
    "food_bev_offprem":                [-0.01,-0.01,  0.41,  0.23, 0.27,-0.14,  0.49,  0.06, 0.25, -0.08, 0.03, -0.02],
    "clothing":                        [-0.33,-0.33,  0.49,  0.40, 1.05, 1.04,  0.40,  0.04,-0.17, -0.12, 0.16,  0.16],
    "gasoline":                        [-1.08, 2.53, -0.32, -3.37, 1.37, 20.92, 5.49,  6.47,-9.24, -2.68, 4.36,  9.24],
    "other_nondurable":                [0.00,  0.01,  0.28,  0.13, 0.50,-0.33, -0.10, -0.25, 0.27, -0.06,-0.09,  0.16],
    "services":                        [0.25,  0.24,  0.32,  0.42, 0.23, 0.29,  0.35,  0.42, 0.14,  0.13, 0.31,  0.35],
    "services_ex_energy":              [0.24,  0.22,  0.30,  0.43, 0.24, 0.29,  0.31,  0.42, 0.17,  0.13, 0.33,  0.36],
    "services_ex_energy_housing":      [0.27,  0.25,  0.30,  0.49, 0.25, 0.29,  0.25,  0.46, 0.15,  0.09, 0.37,  0.37],
    "services_ex_energy_airfare_healthcare":           [0.15, 0.21, 0.40, 0.35, 0.22, 0.24, 0.35, 0.41, 0.11, 0.11, 0.39, 0.34],
    "services_ex_energy_housing_pubtrans_medical":     [0.14, 0.24, 0.50, 0.42, 0.20, 0.15, 0.31, 0.51,-0.00, 0.03, 0.46, 0.29],
    "housing":                         [0.14,  0.14,  0.30,  0.23, 0.20, 0.26,  0.53,  0.31, 0.22,  0.26, 0.19,  0.32],
    "hh_consumption_services":         [0.28,  0.26,  0.33,  0.40, 0.24, 0.32,  0.33,  0.41, 0.20,  0.13, 0.31,  0.37],
    "housing_utilities":               [0.20,  0.21,  0.36,  0.23, 0.21, 0.29,  0.63,  0.31, 0.14,  0.26, 0.14,  0.30],
    "health_care":                     [0.46,  0.25,  0.01,  0.57, 0.20, 0.35,  0.12,  0.29, 0.34,  0.18, 0.08,  0.14],
    "transportation_services":         [0.40,  0.26, -0.03,  0.81, 0.90, 1.29,  0.36,  0.88, 0.58,  0.19, 1.09,  2.14],
    "recreation_services":             [0.02, -0.04,  2.33,  0.42,-0.50, 0.25,  0.33,  0.20,-0.14, -0.04,-0.05,  0.39],
    "food_services_accom":             [0.13,  0.13,  0.87,  0.10, 0.35, 0.24,  0.54,  0.30,-0.08, -0.07, 0.48,  0.43],
    "financial_services_insurance":    [0.34,  0.49,  0.40,  0.55, 0.12, 0.33,  0.46,  0.58, 0.32,  0.06, 0.28,  0.39],
    "other_services":                  [0.23,  0.41, -0.36,  0.33, 0.49, 0.04, -0.18,  0.71, 0.16,  0.03, 0.86,  0.17],
    "all_items_ex_food_energy_housing":[0.18,  0.16,  0.32,  0.43, 0.37, 0.25,  0.23,  0.31, 0.12,  0.11, 0.28,  0.32],
    "food":                            [-0.01,-0.01,  0.41,  0.23, 0.27,-0.14,  0.49,  0.06, 0.25, -0.08, 0.03, -0.02],
    "energy":                          [-0.24, 1.72,  0.23, -1.78, 0.77,11.51,  3.86,  3.95,-5.84, -1.41, 2.30,  5.36],
    "market_based":                    [0.16,  0.19,  0.33,  0.26, 0.38, 0.71,  0.45,  0.40,-0.11,  0.05, 0.32,  0.54],
    "market_based_ex_food_energy":     [0.19,  0.13,  0.33,  0.36, 0.37, 0.28,  0.27,  0.25, 0.17,  0.14, 0.24,  0.34],
}


def _to_md(df: pd.DataFrame, title: str, note: str, digits: int = 2) -> str:
    out = [f"### {title}", "", note, ""]
    hdr = [df.index.name or "Série"] + list(df.columns)
    out.append("| " + " | ".join(hdr) + " |")
    out.append("|" + "|".join([":---"] + ["---:"] * len(df.columns)) + "|")
    for name, row in df.iterrows():
        cells = [str(name)] + ["n/a" if pd.isna(v) else f"{v:.{digits}f}" for v in row.values]
        out.append("| " + " | ".join(cells) + " |")
    out.append("")
    return "\n".join(out)


# ----- Dados nossos -----
idx = pd.read_csv(IDX_CSV, parse_dates=["date"])
pesos = pd.read_csv(PESO_CSV, parse_dates=["date"])
mp = pd.read_csv(MAP_CSV)
labels = dict(zip(mp["slug"], mp["label"]))

# MoM% derivado do value_index (last 12m que o Haver tem)
dates_window = [pd.Timestamp(d) for d in HAVER_HEADERS]
mom_rows = []
for cat, g in idx.groupby("cat"):
    g = g.sort_values("date").reset_index(drop=True).copy()
    g["mom_pct"] = g["value_index"].pct_change() * 100
    gw = g[g["date"].isin(dates_window)]
    for _, r in gw.iterrows():
        mom_rows.append({"cat": cat, "date": r["date"], "mom": r["mom_pct"]})
mom_our_df = pd.DataFrame(mom_rows)
mom_our = (mom_our_df.pivot(index="cat", columns="date", values="mom"))
mom_our.columns = [d.strftime("%Y-%m") for d in mom_our.columns]
mom_our = mom_our.reindex(columns=HAVER_HEADERS)

# Weight ultimo mes
last_date = pesos["date"].max()
our_weight = pesos[pesos["date"] == last_date].set_index("cat")["weight"].round(2)

# Ordem canonica (bate com a tabela que o user mandou)
CAT_ORDER = [
    "all_items", "core", "goods", "core_goods", "durable_goods", "motor_vehicles",
    "furnishings", "recreational_goods", "other_durable", "nondurable_goods",
    "food_bev_offprem", "clothing", "gasoline", "other_nondurable",
    "services", "services_ex_energy", "services_ex_energy_housing",
    "services_ex_energy_airfare_healthcare", "services_ex_energy_housing_pubtrans_medical",
    "housing", "hh_consumption_services", "housing_utilities", "health_care",
    "transportation_services", "recreation_services", "food_services_accom",
    "financial_services_insurance", "other_services",
    "all_items_ex_food_energy_housing", "food", "energy",
    "market_based", "market_based_ex_food_energy",
]

# Tabela Weight comparando os 2
weight_rows = []
for slug in CAT_ORDER:
    label = labels.get(slug, slug)
    our = our_weight.get(slug, float("nan"))
    hav = HAVER_WEIGHT.get(slug, float("nan"))
    weight_rows.append({
        "Categoria": label, "Nosso": our, "Haver": hav,
        "Diff (pp)": our - hav if pd.notna(our) and pd.notna(hav) else float("nan"),
    })
weight_df = pd.DataFrame(weight_rows).set_index("Categoria")

# Tabela MoM — nossos valores pros 12 meses do Haver
mom_our_tbl = mom_our.reindex(index=CAT_ORDER).copy()
mom_our_tbl.index = [labels.get(c, c) for c in mom_our_tbl.index]
mom_our_tbl.index.name = "Categoria (nosso MoM %)"

# Tabela MoM — valores Haver
mom_haver_tbl = pd.DataFrame({d: [HAVER_MOM.get(c, [None]*12)[i] for c in CAT_ORDER]
                               for i, d in enumerate(HAVER_HEADERS)})
mom_haver_tbl.index = [labels.get(c, c) for c in CAT_ORDER]
mom_haver_tbl.index.name = "Categoria (Haver MoM %)"

# Diff MoM
mom_diff = mom_our_tbl.values - mom_haver_tbl.values
mom_diff_tbl = pd.DataFrame(mom_diff, index=mom_our_tbl.index, columns=HAVER_HEADERS)
mom_diff_tbl.index.name = "Categoria (diff pp, nosso − Haver)"

# Resumo global: max|d| por categoria sobre os 12m
abs_diff = pd.DataFrame({c: [abs(mom_our.loc[c, d] - HAVER_MOM.get(c, [None]*12)[i])
                              if (c in mom_our.index and HAVER_MOM.get(c) is not None) else None
                              for i, d in enumerate(HAVER_HEADERS)]
                          for c in CAT_ORDER}).T
abs_diff.columns = HAVER_HEADERS
summary = pd.DataFrame({
    "max|d| (pp)":  abs_diff.max(axis=1),
    "mean|d| (pp)": abs_diff.mean(axis=1),
})
summary.index = [labels.get(c, c) for c in CAT_ORDER]
summary.index.name = "Categoria"
summary_sorted = summary.sort_values("max|d| (pp)", ascending=False)

md = [
    "# PCE categorias — validação vs Haver Analytics (ground truth)",
    "",
    f"**Last date**: {last_date:%Y-%m}. Fonte: `pce_categorias_indice.csv` + "
    f"`pce_categorias_pesos.csv` (bottom-up do BEA U20404+U20405 via "
    f"`build_pce_categorias.py`).",
    "",
    "Validação direto contra a tabela Haver que o usuário usa como referência. "
    "33 categorias cobertas:",
    "- **24 directs** — line_number do BEA U20404 (ex: `Services`=150, `Core PCE`=374)",
    "- **4 customs** — álgebra Laspeyres via `bea_maps/pce_categorias.csv`",
    "  (`Services ex Energy and Housing`, `Services ex Energy Airfare Healthcare`, "
    "`Services ex Energy Housing PubTrans Medical`, `PCE ex Food Energy Housing`)",
    "- **5 outros** — `Food`, `Energy`, `Market-based PCE`, `Market-based PCE ex food energy`, "
    "`Household Consumption Expenditures (Services)`",
    "",
    "Threshold mental: `max|d| < 0.02pp` em qualquer mês = **conta perfeita**. "
    "Diffs maiores indicam arredondamento na tabela Haver ou drift metodológico "
    "(improvável).",
    "",
    _to_md(weight_df.round(2), "Weight (último mês vs Haver)",
           "Weight = share do nominal mensal U20405 vs headline. Para custom aggregates "
           "é a weight derivada da álgebra. All_items é sintético 100.0 fixo.", 2),
    _to_md(summary_sorted.round(4),
           "Chain fidelity — max|d| MoM (12m overlap Oct/25-Sep/26)",
           "max|d| por categoria sobre os 12 meses. Valores < 0.02pp = diff só "
           "de arredondamento da tabela Haver (2 decimais).", 4),
    _to_md(mom_our_tbl.round(2), "MoM SA % — nossos valores (bottom-up BEA)",
           "Derivado de `pce_categorias_indice.csv`: `(idx[t]/idx[t-1] − 1) × 100`.", 2),
    _to_md(mom_haver_tbl.round(2), "MoM SA % — Haver reference",
           "Tabela que o usuário usa como ground truth (Haver Analytics).", 2),
    _to_md(mom_diff_tbl.round(2), "MoM SA — Diff (nosso − Haver, pp)",
           "Valores próximos de 0 = reconstrução perfeita. Até 0.01pp é esperado "
           "pelo arredondamento da tabela Haver.", 2),
]

OUT.write_text("\n".join(md), encoding="utf-8")
print(f"[OK] {OUT.relative_to(ROOT)} — last={last_date:%Y-%m}, "
      f"max|d| global = {summary['max|d| (pp)'].max():.4f}pp")
print(f"\nResumo top 5 maiores diffs:")
print(summary_sorted.head(5).round(4).to_string())
