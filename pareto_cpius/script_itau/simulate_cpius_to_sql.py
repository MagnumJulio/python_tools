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
# Cada categoria vira ate 3 series: NSA idx, SA idx, Weight. Var (NSA/SA)
# foi removida no sync 2026-07-20 pra nao lotar SQL de lixo — usuario prefere
# derivar variacao mensal a partir do indice. SA vem nativo do BLS (nao
# precisa de X-13 como no pareto_ipca). Weight vem da Table 6 do release
# (Relative Importance).
#
# Uso:
#   cd pareto_cpius
#   python script_itau/simulate_cpius_to_sql.py             # todas as 47 cats
#   python script_itau/simulate_cpius_to_sql.py --only all_items,core
#   python script_itau/simulate_cpius_to_sql.py --save      # grava CSVs

import argparse
import sys
from datetime import date
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
IDX_CSV          = ROOT / "data" / "cpi_cpius_indice.csv"
PESO_CSV         = ROOT / "data" / "cpi_cpius_pesos.csv"
CUSTOM_CSV       = ROOT / "data" / "cpi_cpius_custom.csv"
CUSTOM_PESOS_CSV = ROOT / "data" / "cpi_cpius_pesos_custom.csv"
OUT_DIR          = Path(__file__).resolve().parent / "sim_output"

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
    "core_goods":              "CPI-U: Core Goods",
    "apparel":                 "CPI-U: Apparel",
    "new_vehicles":            "CPI-U: New Vehicles",
    "used_cars_trucks":        "CPI-U: Used Cars and Trucks",
    "car_truck_rental":        "CPI-U: Car and Truck Rental",
    "medical_care":            "CPI-U: Medical Care",
    "medical_goods":           "CPI-U: Medical Care Commodities",
    "alcoholic_bev":           "CPI-U: Alcoholic Beverages",
    "tobacco":                 "CPI-U: Tobacco and Smoking Products",
    "core_services":           "CPI-U: Core Services",
    "shelter":                 "CPI-U: Shelter",
    "rent":                    "CPI-U: Rent of Primary Residence",
    "oer":                     "CPI-U: Owners' Equivalent Rent of Residences",
    "medical_services":        "CPI-U: Medical Care Services",
    "physicians_services":     "CPI-U: Physicians' Services",
    "hospital_services":       "CPI-U: Hospital Services",
    "transportation_services": "CPI-U: Transportation Services",
    "motor_vehicle_maint":     "CPI-U: Motor Vehicle Maintenance and Repair",
    "motor_vehicle_insur":     "CPI-U: Motor Vehicle Insurance",
    "public_transportation":   "CPI-U: Public Transportation",
    "airline_fares":           "CPI-U: Airline Fares",
    "lodging_away":            "CPI-U: Lodging Away from Home",
}

# Definicao BLS oficial pra cats cujo `series_name` foi encurtado (sync
# 2026-07-21). Injetada no `description` do SQL pra preservar rastreabilidade
# da definicao formal do release. Se a cat nao estiver aqui, description
# permanece sem sufixo de definicao.
CATEGORY_BLS_DEFS = {
    "core_goods":    "Commodities less food and energy commodities (BLS item SACL1E)",
    "core_services": "Services less energy services (BLS item SASLE)",
}

# Agregacoes custom derivadas via algebra Laspeyres (build_custom_aggregations.R).
# Recipes em scripts/bls_maps/custom_aggregations.csv.
CUSTOM_LABELS = {
    "rent_of_shelter":                           "CPI-U: Rent of Shelter (Custom)",
    "core_ex_oer":                               "CPI-U: Core ex OER (Custom)",
    "cpi_ex_oer":                                "CPI-U: All Items ex OER (Custom)",
    "core_services_ex_shelter":                  "CPI-U: Core Services ex Rent of Shelter (Custom)",
    "supercore_powell_old":                      "CPI-U: Core Services ex RPR & OER (Old Powell Supercore, Custom)",
    "core_services_ex_shelter_pubtrans_medical": "CPI-U: Core Services ex Shelter/PubTrans/Medical (Custom)",
    "super_super_core":                          "CPI-U: Super Super Core (Custom)",
    "core_services_ex_volatiles":                "CPI-U: Core Services ex Volatiles (Custom)",
}

# Sync 2026-07-20: bls_code colapsado pra um unico formato CPIUS:{cat}. Como
# var (NSA/SA) foi removida, nao ha mais dois "lados" (var-side vs idx-side);
# so o lado idx sobra, entao o sufixo /Index no bls_code virou redundante e
# foi removido. Distincao idx vs Weight sai de data_type + series_name (idx
# tem "(Index)" no series_name; Weight tambem — porque frontend casa
# series_name+country+indicator entre serie e Weight companheiro).
# haver_code (legado) fica NULL em INSERTs novos — nao setamos o campo, SQL
# resolve como NULL por default.
CODE = "CPIUS:{cat}"

SERIES_COLS = ["series_id", "country", "subject", "indicator", "series_name",
               "data_type", "frequency", "description", "haver_code", "bls_code"]
DATA_COLS = ["date", "series_id", "value", "release_date", "vintage_date"]


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
        # Reindexa pra SERIES_COLS: colunas ausentes do dict (ex: haver_code)
        # entram como NaN, replicando o comportamento do SQL Server que grava
        # NULL nas colunas nao referenciadas pelo INSERT.
        df_new = pd.DataFrame([row]).reindex(columns=SERIES_COLS)
        self.tables["OPT_Macro_Series_2"] = self._append(
            self.tables["OPT_Macro_Series_2"], df_new
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
    description: str, bls_code: str,
    session: MockSQLConnector, replace: bool = True,
) -> int:
    series_id = session._find_series_id(country, subject, indicator, series_name, data_type)
    if series_id is None:
        # haver_code fica None (SQL NULL) — nao passamos o campo no dict pra
        # replicar exatamente o INSERT do loader corp. Reindex em insert_meta
        # preenche haver_code com NaN.
        series_id = session.insert_meta({
            "country": country, "subject": subject, "indicator": indicator,
            "series_name": series_name, "data_type": data_type,
            "frequency": frequency, "description": description, "bls_code": bls_code,
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

    only = set(args.only.split(",")) if args.only else None

    print(f"[1] Lendo {IDX_CSV.relative_to(ROOT)}...")
    idx_by_key = _load_split_by_sa(IDX_CSV, "index")
    print(f"    {len(idx_by_key)} (categoria, sa_flag) combinacoes")

    print(f"[2] Lendo {PESO_CSV.relative_to(ROOT)} (opcional)...")
    peso_series: dict[str, pd.Series] = {}
    if PESO_CSV.exists():
        peso_series = _load_peso_long(PESO_CSV)
        print(f"    {len(peso_series)} categorias com peso (Relative Importance BLS)")
    else:
        print("    [WARN] nao encontrado — pesos nao serao carregados. Rode scripts/fetch_bls_pesos.R.")

    # Custom aggregations (recipes em scripts/bls_maps/custom_aggregations.csv,
    # geradas por build_custom_aggregations.R). Merge nos dicts principais.
    custom_cats: set[str] = set()
    if CUSTOM_CSV.exists():
        print(f"[3] Lendo {CUSTOM_CSV.relative_to(ROOT)}...")
        cidx = _load_split_by_sa(CUSTOM_CSV, "value_index")
        idx_by_key.update(cidx)
        custom_cats = {c for (c, _sa) in cidx}
        print(f"    {len(custom_cats)} agregacoes custom + NSA/SA")
        if CUSTOM_PESOS_CSV.exists():
            cpes = _load_peso_long(CUSTOM_PESOS_CSV)
            peso_series.update(cpes)
            print(f"    {len(cpes)} pesos custom derivados")
    else:
        print(f"[3] {CUSTOM_CSV.relative_to(ROOT)} nao existe — rode build_custom_aggregations.R pra habilitar.")

    # Peso sintetico do headline: all_items sempre = 100.0 constante (definicao
    # semantica, nao medicao). Sobrescreve o valor renormalizado do CSV (~99.9997)
    # pra bater com pareto_ipca (ipca_total = 100 constante).
    if "all_items" in peso_series:
        idx_ai = peso_series["all_items"].index
        peso_series["all_items"] = pd.Series(100.0, index=idx_ai, name="all_items")

    all_labels = {**CATEGORY_LABELS, **CUSTOM_LABELS}
    cats = sorted({c for (c, _sa) in idx_by_key})
    if only:
        cats = [c for c in cats if c in only]
    missing_label = [c for c in cats if c not in all_labels]
    if missing_label:
        sys.exit(f"Falta label em CATEGORY_LABELS/CUSTOM_LABELS pra: {missing_label}")

    session = MockSQLConnector()

    for c in cats:
        label = all_labels[c]
        is_custom = c in custom_cats
        bls = CODE.format(cat=c)
        src = "custom aggregation (Laspeyres algebra)" if is_custom else "BLS API v2 direto"
        bls_def = CATEGORY_BLS_DEFS.get(c)
        def_suffix = f" - {bls_def}" if bls_def else ""
        for sa in ("NSA", "SA"):
            key = (c, sa)
            if key not in idx_by_key:
                print(f"  [SKIP] {c}/{sa} — faltando em indice")
                continue
            si, _ = idx_by_key[key]
            print(f"  - {label:55s} [{sa}]  idx={len(si):4d}")

            sim_sidra_to_sql(
                series=si, country="US", subject="Prices", indicator="CPI",
                series_name=f"{label} (Index)", data_type=sa, frequency="M",
                description=f"{label} - Indice [{sa}] (rebased jan/2000=100){def_suffix} - {src}",
                bls_code=bls,
                session=session,
            )
        # Weight. Base: RI Table 6 BLS. Custom: derivado via algebra da recipe.
        # Gravado 1x (sync 2026-07-20): pareado so com o idx via
        # series_name=f"{label} (Index)" — o var sumiu, entao a segunda gravacao
        # (com series_name=label) tambem deixou de fazer sentido. Frontend
        # continua casando series_name+country+indicator entre idx e Weight.
        sp = peso_series.get(c)
        if sp is not None:
            print(f"    weight={len(sp):4d}")
            peso_desc = (
                f"{label} - Weight derivado (algebra Laspeyres da recipe){def_suffix}"
                if is_custom else f"{label} - Weight (Relative Importance, Table 6 BLS){def_suffix}"
            )
            sim_sidra_to_sql(
                series=sp, country="US", subject="Prices", indicator="CPI",
                series_name=f"{label} (Index)", data_type="Weight", frequency="M",
                description=peso_desc,
                bls_code=bls,
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
