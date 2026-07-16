#!/usr/bin/env python
# simulate_cpius_to_sql.py
# Simulacao do load_cpius_to_sql.py SEM tocar em SQL/opt_utils. Usa um
# MockSQLConnector que guarda OPT_Macro_Series_2 e OPT_Macro_Series_Data_2 em
# pandas DataFrames em memoria, imitando exatamente o schema/contrato do
# loader corp. Util pra testar mapping/labels/proveniencia em casa.
#
# Saidas em pareto_cpius/script_itau/sim_output/:
#   OPT_Macro_Series_2.csv       - metadados (1 linha por serie cadastrada)
#   OPT_Macro_Series_Data_2.csv  - long EAV (1 linha por (serie, mes))
#
# Cada categoria vira ate 5 series: NSA var, NSA idx, SA var, SA idx, Peso.
# SA vem nativo do BLS (nao precisa de X-13 como no pareto_ipca). Peso vem
# da Table 6 do release (Relative Importance) — snapshot atual replicado
# pra toda a serie (MVP; fase 2: annual step function das releases de Dez).
#
# Uso:
#   cd pareto_cpius
#   python script_itau/simulate_cpius_to_sql.py             # todas as 37 cats
#   python script_itau/simulate_cpius_to_sql.py --only all_items,core
#   python script_itau/simulate_cpius_to_sql.py --save      # grava CSVs

import argparse
import subprocess
import sys
from datetime import date
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RECON_CSV = ROOT / "data" / "cpi_cpius_recon.csv"
IDX_CSV   = ROOT / "data" / "cpi_cpius_indice.csv"
PESO_CSV  = ROOT / "data" / "cpi_cpius_pesos.csv"
OUT_DIR   = Path(__file__).resolve().parent / "sim_output"

# 37 category_code -> nome legivel. Espelha Table 1 do release BLS CPI-U
# (Consumer Price Index for All Urban Consumers, U.S. city average, by
# expenditure category). Hierarquia preservada no CSV `cpiu_table_1.csv`
# via coluna `indent_level`.
CATEGORY_LABELS = {
    "all_items":               "CPI-U: All Items",
    "food":                    "CPI-U: Food",
    "food_home":               "CPI-U: Food at Home",
    "food_cereals_bakery":     "CPI-U: Cereals and Bakery Products",
    "food_meats":              "CPI-U: Meats, Poultry, Fish, and Eggs",
    "food_dairy":              "CPI-U: Dairy and Related Products",
    "food_fruits_veg":         "CPI-U: Fruits and Vegetables",
    "food_nonalc_bev":         "CPI-U: Nonalcoholic Beverages and Beverage Materials",
    "food_other_home":         "CPI-U: Other Food at Home",
    "food_away":               "CPI-U: Food Away from Home",
    "energy":                  "CPI-U: Energy",
    "energy_commodities":      "CPI-U: Energy Commodities",
    "fuel_oil":                "CPI-U: Fuel Oil",
    "motor_fuel":              "CPI-U: Motor Fuel",
    "gasoline":                "CPI-U: Gasoline (all types)",
    "energy_services":         "CPI-U: Energy Services",
    "electricity":             "CPI-U: Electricity",
    "utility_gas":             "CPI-U: Utility (piped) Gas Service",
    "core":                    "CPI-U: All Items Less Food and Energy (Core)",
    "core_goods":              "CPI-U: Commodities Less Food and Energy Commodities",
    "apparel":                 "CPI-U: Apparel",
    "new_vehicles":            "CPI-U: New Vehicles",
    "used_cars_trucks":        "CPI-U: Used Cars and Trucks",
    "medical_goods":           "CPI-U: Medical Care Commodities",
    "alcoholic_bev":           "CPI-U: Alcoholic Beverages",
    "tobacco":                 "CPI-U: Tobacco and Smoking Products",
    "core_services":           "CPI-U: Services Less Energy Services",
    "shelter":                 "CPI-U: Shelter",
    "rent":                    "CPI-U: Rent of Primary Residence",
    "oer":                     "CPI-U: Owners' Equivalent Rent of Residences",
    "medical_services":        "CPI-U: Medical Care Services",
    "physicians_services":     "CPI-U: Physicians' Services",
    "hospital_services":       "CPI-U: Hospital Services",
    "transportation_services": "CPI-U: Transportation Services",
    "motor_vehicle_maint":     "CPI-U: Motor Vehicle Maintenance and Repair",
    "motor_vehicle_insur":     "CPI-U: Motor Vehicle Insurance",
    "airline_fares":           "CPI-U: Airline Fares",
}

CPIUS_CODE_VAR  = "CPIUS:{cat}/{sid}/BLS-{sha}"
CPIUS_CODE_IDX  = "CPIUS:{cat}/{sid}/Index/BLS-{sha}"
CPIUS_CODE_PESO = "CPIUS:{cat}/RI/BLS-{sha}"

SERIES_COLS = ["series_id", "country", "subject", "indicator", "series_name",
               "data_type", "frequency", "description", "haver_code"]
DATA_COLS = ["date", "series_id", "value", "release_date", "vintage_date"]


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, stderr=subprocess.DEVNULL
        ).decode().strip()
    except Exception:
        return "nogit"


class MockSQLConnector:
    """Imita o contrato do opt_utils.SQLConnector; auto-incrementa series_id."""

    def __init__(self):
        self.tables = {
            "OPT_Macro_Series_2":      pd.DataFrame(columns=SERIES_COLS),
            "OPT_Macro_Series_Data_2": pd.DataFrame(columns=DATA_COLS),
        }
        self._next_id = 1
        self.conn = self

    def _find_series_id(self, country, subject, indicator, series_name, data_type):
        t = self.tables["OPT_Macro_Series_2"]
        m = (t.country == country) & (t.subject == subject) & (t.indicator == indicator) \
            & (t.series_name == series_name) & (t.data_type == data_type)
        return int(t.loc[m, "series_id"].iloc[0]) if m.any() else None

    @staticmethod
    def _append(base: pd.DataFrame, new: pd.DataFrame) -> pd.DataFrame:
        return new.copy() if base.empty else pd.concat([base, new], ignore_index=True)

    def insert_meta(self, row: dict) -> int:
        row = {**row, "series_id": self._next_id}
        self._next_id += 1
        self.tables["OPT_Macro_Series_2"] = self._append(
            self.tables["OPT_Macro_Series_2"], pd.DataFrame([row])
        )
        return row["series_id"]

    def delete_data(self, series_id: int):
        t = self.tables["OPT_Macro_Series_Data_2"]
        self.tables["OPT_Macro_Series_Data_2"] = t[t.series_id != series_id].reset_index(drop=True)

    def insert_data(self, df: pd.DataFrame):
        self.tables["OPT_Macro_Series_Data_2"] = self._append(
            self.tables["OPT_Macro_Series_Data_2"], df[DATA_COLS]
        )

    def close(self):
        pass


def sim_sidra_to_sql(
    series: pd.Series,
    country: str, subject: str, indicator: str,
    series_name: str, data_type: str, frequency: str,
    description: str, haver_code: str,
    session: MockSQLConnector, replace: bool = True,
) -> int:
    series_id = session._find_series_id(country, subject, indicator, series_name, data_type)
    if series_id is None:
        series_id = session.insert_meta({
            "country": country, "subject": subject, "indicator": indicator,
            "series_name": series_name, "data_type": data_type,
            "frequency": frequency, "description": description, "haver_code": haver_code,
        })

    if replace:
        session.delete_data(series_id)

    s = series.dropna()
    today = date.today()
    df_data = pd.DataFrame({
        "date": s.index.date,
        "series_id": series_id,
        "value": s.values,
        "release_date": today,
        "vintage_date": today,
    })
    session.insert_data(df_data)
    return series_id


def _load_split_by_sa(path: Path, value_col: str) -> dict[tuple[str, str], tuple[pd.Series, str]]:
    """Retorna {(category_code, sa_flag): (series, series_id_BLS)}."""
    if not path.exists():
        sys.exit(f"CSV nao encontrado: {path}. Rode scripts/fetch_bls_cpiu.R primeiro.")
    df = pd.read_csv(path)
    df["date"] = pd.to_datetime(df["date"])
    out: dict[tuple[str, str], tuple[pd.Series, str]] = {}
    key_cols = ["category_code", "sa_flag"]
    for (cat, sa), g in df.groupby(key_cols):
        s = g.set_index("date")[value_col].sort_index().astype(float)
        s.name = f"{cat}/{sa}"
        # series_id BLS (CUUR/CUSR...) so aparece no recon; no indice nao.
        sid = g["series_id"].iloc[0] if "series_id" in g.columns else ""
        out[(cat, sa)] = (s, sid)
    return out


def _load_peso_long(path: Path) -> dict[str, pd.Series]:
    """Retorna {category_code: series} — peso (RI Table 6 BLS), sem sa_flag."""
    df = pd.read_csv(path)
    df["date"] = pd.to_datetime(df["date"])
    out: dict[str, pd.Series] = {}
    for cat, g in df.groupby("category_code"):
        s = g.set_index("date")["value"].sort_index().astype(float)
        s.name = cat
        out[cat] = s
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", type=str, default=None,
                        help="Lista CSV de category_code (ex: 'all_items,core').")
    parser.add_argument("--preview", type=int, default=10,
                        help="Linhas a imprimir de cada tabela ao fim (default 10).")
    parser.add_argument("--save", action="store_true",
                        help="Salva as 2 tabelas em script_itau/sim_output/*.csv.")
    args = parser.parse_args()

    sha = _git_sha()
    only = set(args.only.split(",")) if args.only else None

    print(f"[1] Lendo {RECON_CSV.relative_to(ROOT)}...")
    var_by_key = _load_split_by_sa(RECON_CSV, "value_var_mm")
    print(f"    {len(var_by_key)} (categoria, sa_flag) combinacoes")

    print(f"[2] Lendo {IDX_CSV.relative_to(ROOT)}...")
    idx_by_key = _load_split_by_sa(IDX_CSV, "index")
    print(f"    {len(idx_by_key)} (categoria, sa_flag) combinacoes")

    print(f"[3] Lendo {PESO_CSV.relative_to(ROOT)} (opcional)...")
    peso_series: dict[str, pd.Series] = {}
    if PESO_CSV.exists():
        peso_series = _load_peso_long(PESO_CSV)
        print(f"    {len(peso_series)} categorias com peso (Relative Importance BLS)")
    else:
        print("    [WARN] nao encontrado — pesos nao serao carregados. Rode scripts/fetch_bls_pesos.R.")

    cats = sorted({c for (c, _sa) in var_by_key} & {c for (c, _sa) in idx_by_key})
    if only:
        cats = [c for c in cats if c in only]
    missing_label = [c for c in cats if c not in CATEGORY_LABELS]
    if missing_label:
        sys.exit(f"Falta label em CATEGORY_LABELS pra: {missing_label}")

    session = MockSQLConnector()

    for c in cats:
        label = CATEGORY_LABELS[c]
        for sa in ("NSA", "SA"):
            key = (c, sa)
            if key not in var_by_key or key not in idx_by_key:
                print(f"  [SKIP] {c}/{sa} — faltando em recon ou indice")
                continue
            sv, sid_bls = var_by_key[key]
            si, _ = idx_by_key[key]
            print(f"  - {label:55s} [{sa}]  var={len(sv):4d}   idx={len(si):4d}")

            sim_sidra_to_sql(
                series=sv, country="US", subject="Prices", indicator="CPI-U",
                series_name=label, data_type=sa, frequency="M",
                description=f"{label} - Variacao mensal (%) [{sa}] - BLS API v2 direto",
                haver_code=CPIUS_CODE_VAR.format(cat=c, sid=sid_bls, sha=sha),
                session=session,
            )
            sim_sidra_to_sql(
                series=si, country="US", subject="Prices", indicator="CPI-U",
                series_name=f"{label} (Index)", data_type=sa, frequency="M",
                description=f"{label} - Indice [{sa}] (rebased jan/2000=100) - BLS API v2 direto",
                haver_code=CPIUS_CODE_IDX.format(cat=c, sid=sid_bls, sha=sha),
                session=session,
            )
        # Peso (Relative Importance BLS Table 6). Uma serie por categoria,
        # compartilha series_name com var (sync com padrao IPCA). Nao tem
        # SA/NSA — RI e mesmo valor.
        sp = peso_series.get(c)
        if sp is not None:
            print(f"    peso={len(sp):4d}")
            sim_sidra_to_sql(
                series=sp, country="US", subject="Prices", indicator="CPI-U",
                series_name=label, data_type="Peso", frequency="M",
                description=f"{label} - Peso (Relative Importance, Table 6 BLS)",
                haver_code=CPIUS_CODE_PESO.format(cat=c, sha=sha),
                session=session,
            )

    meta = session.tables["OPT_Macro_Series_2"]
    data = session.tables["OPT_Macro_Series_Data_2"]

    print("\n" + "=" * 70)
    print(f"OPT_Macro_Series_2 - {len(meta)} series cadastradas")
    print("=" * 70)
    with pd.option_context("display.max_columns", None, "display.width", 200):
        print(meta.head(args.preview).to_string(index=False))

    print("\n" + "=" * 70)
    print(f"OPT_Macro_Series_Data_2 - {len(data)} linhas (long EAV)")
    print("=" * 70)
    with pd.option_context("display.max_columns", None, "display.width", 200):
        print(data.head(args.preview).to_string(index=False))

    print("\nContagem por series_id (preview):")
    cnt = data.groupby("series_id").size().rename("n_obs")
    chk = meta.set_index("series_id")[["series_name", "data_type"]].join(cnt)
    print(chk.head(args.preview).to_string())

    if args.save:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        meta.to_csv(OUT_DIR / "OPT_Macro_Series_2.csv", index=False)
        data.to_csv(OUT_DIR / "OPT_Macro_Series_Data_2.csv", index=False)
        print(f"\n[OK] Salvo em {OUT_DIR.relative_to(ROOT)}/")


if __name__ == "__main__":
    main()
