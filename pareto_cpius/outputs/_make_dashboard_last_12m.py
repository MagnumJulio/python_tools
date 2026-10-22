#!/usr/bin/env python3
# Gera dashboard markdown last-12m das 22 cats dashboard CPI-U.
# Tabelas: pesos NSA | MoM NSA | MoM SA | YoY NSA | YoY SA.
# Fonte: data/cpi_cpius_recon.csv + cpi_cpius_custom.csv + pesos{_custom}.csv.

from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "outputs" / "dashboard_cpius_last_12m.md"

CATS = [
    "all_items", "core", "core_goods", "core_services",
    "food", "energy",
    "shelter", "rent", "oer", "lodging_away",
    "new_vehicles", "used_cars_trucks", "car_truck_rental",
    "medical_services", "transportation_services", "airline_fares",
    "core_ex_oer", "cpi_ex_oer",
    "core_services_ex_shelter", "core_services_ex_volatiles",
    "supercore_powell_old", "super_super_core",
]

LABELS = {
    "all_items": "All items", "core": "Core (ex food & energy)",
    "core_goods": "Core goods", "core_services": "Core services",
    "food": "Food", "energy": "Energy",
    "shelter": "Shelter", "rent": "Rent", "oer": "OER",
    "lodging_away": "Lodging away",
    "new_vehicles": "New vehicles", "used_cars_trucks": "Used cars/trucks",
    "car_truck_rental": "Car/truck rental",
    "medical_services": "Medical services",
    "transportation_services": "Transportation services",
    "airline_fares": "Airline fares",
    "core_ex_oer": "Core ex OER", "cpi_ex_oer": "CPI ex OER",
    "core_services_ex_shelter": "Core services ex shelter",
    "core_services_ex_volatiles": "Core services ex volatiles",
    "supercore_powell_old": "Supercore (Powell old)",
    "super_super_core": "Super-super core",
}

recon = pd.read_csv(ROOT / "data" / "cpi_cpius_recon.csv", parse_dates=["date"])
custom = pd.read_csv(ROOT / "data" / "cpi_cpius_custom.csv", parse_dates=["date"])
df = pd.concat([recon, custom], ignore_index=True)
df = df[df["category_code"].isin(CATS)].copy()

pesos_base = pd.read_csv(ROOT / "data" / "cpi_cpius_pesos.csv", parse_dates=["date"])
pesos_custom = pd.read_csv(ROOT / "data" / "cpi_cpius_pesos_custom.csv", parse_dates=["date"])
pesos = pd.concat([pesos_base, pesos_custom], ignore_index=True)
pesos = pesos[pesos["category_code"].isin(CATS)].copy()

last_date = df["date"].max()
start = (last_date - pd.DateOffset(months=11)).replace(day=1)
dates = pd.date_range(start, last_date, freq="MS")
date_cols = [d.strftime("%Y-%m") for d in dates]


def pivot(metric: str, sa_flag: str) -> pd.DataFrame:
    sub = df[(df["sa_flag"] == sa_flag) & (df["date"].isin(dates))]
    p = sub.pivot(index="category_code", columns="date", values=metric)
    p.columns = [c.strftime("%Y-%m") for c in p.columns]
    p = p.reindex(index=CATS, columns=date_cols)
    p.index = [LABELS[c] for c in p.index]
    return p


def pivot_pesos() -> pd.DataFrame:
    sub = pesos[pesos["date"].isin(dates)]
    p = sub.pivot(index="category_code", columns="date", values="value")
    p.columns = [c.strftime("%Y-%m") for c in p.columns]
    p = p.reindex(index=CATS, columns=date_cols)
    p.index = [LABELS[c] for c in p.index]
    return p


def to_md(p: pd.DataFrame, title: str, note: str, digits: int = 2) -> str:
    out = [f"### {title}", "", note, ""]
    hdr = ["Categoria"] + list(p.columns)
    out.append("| " + " | ".join(hdr) + " |")
    out.append("|" + "|".join([":---"] + ["---:"] * len(p.columns)) + "|")
    for cat, row in p.iterrows():
        cells = [cat] + [
            "n/a" if pd.isna(v) else f"{v:.{digits}f}" for v in row.values
        ]
        out.append("| " + " | ".join(cells) + " |")
    out.append("")
    return "\n".join(out)


md = [
    "# CPI-U dashboard — últimos 12 meses",
    "",
    f"**Última data**: {last_date:%Y-%m}. **Fonte**: BLS Public Data API v2 "
    f"(idx NSA/SA, Table 1) + Laspeyres Dez-anchor (customs). "
    f"**Categorias**: 22 (18 base + 4 custom), ordem do dashboard.",
    "",
    "Dados montados a partir de `data/cpi_cpius_recon.csv` + "
    "`cpi_cpius_custom.csv` + `cpi_cpius_pesos{,_custom}.csv`. Gerado por "
    "`outputs/_make_dashboard_last_12m.py`.",
    "",
    "> **Gap 2025-10**: release BLS daquele mês ficou incompleto (shutdown). "
    "Só `new_vehicles`, `used_cars_trucks` e `car_truck_rental` têm dado — "
    "demais cats aparecem `n/a`. Pesos também não têm 2025-10.",
    "",
    to_md(pivot_pesos(), "Pesos NSA (%)",
          "Peso mensal (RI Dez + ajuste implícito BLS). Soma food+energy+core = 100.", 2),
    to_md(pivot("value_var_mm", "SA"), "MoM SA (%)",
          "Variação mês a mês dessazonalizada (BLS CUSR0000...).", 2),
    to_md(pivot("value_var_mm", "NSA"), "MoM NSA (%)",
          "Variação mês a mês sem ajuste sazonal (BLS CUUR0000...).", 2),
    to_md(pivot("value_var_yoy", "NSA"), "YoY NSA (%)",
          "Variação 12 meses NSA — métrica headline do release.", 2),
    to_md(pivot("value_var_yoy", "SA"), "YoY SA (%)",
          "YoY calculado em cima do índice SA (robustez: deve bater YoY NSA dentro de rev. sazonal).", 2),
]

OUT.write_text("\n".join(md), encoding="utf-8")
print(f"[OK] {OUT.relative_to(ROOT)} — last_date={last_date:%Y-%m}, "
      f"{len(dates)} meses, {len(CATS)} cats.")
