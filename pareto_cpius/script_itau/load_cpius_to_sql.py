#!/usr/bin/env python
# load_cpius_to_sql.py
# Carrega as 37 categorias do pareto_cpius (var + idx, NSA + SA, + Peso) na
# base SQL corp (OPT_Macro_Series_2 / OPT_Macro_Series_Data_2), mesmo padrao
# do sidra_itau.ipynb e do load_pareto_to_sql.py. Cada categoria vira ate 5
# series: NSA var, NSA idx, SA var, SA idx, Peso. SA vem nativo do BLS (nao
# precisa X-13); Peso vem da Table 6 do release (Relative Importance).
#
# Pre-requisito: pipeline R ja rodou:
#   cd pareto_cpius
#   Rscript scripts/fetch_bls_cpiu.R      # var + idx (NSA + SA)
#   Rscript scripts/fetch_bls_pesos.R     # peso (RI Table 6 BLS)
# Gera data/cpi_cpius_recon.csv, data/cpi_cpius_indice.csv, data/cpi_cpius_pesos.csv.
#
# Uso (na maquina corp, com opt_utils disponivel):
#   cd pareto_cpius
#   python script_itau/load_cpius_to_sql.py             # todas as 37 cats
#   python script_itau/load_cpius_to_sql.py --dry-run   # so lista o que faria
#   python script_itau/load_cpius_to_sql.py --check     # preflight so
#   python script_itau/load_cpius_to_sql.py --only all_items,core

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:
    from opt_utils.database import SQLConnector  # corp-only; import preguicoso em main()

ROOT      = Path(__file__).resolve().parent.parent
RECON_CSV = ROOT / "data" / "cpi_cpius_recon.csv"
IDX_CSV   = ROOT / "data" / "cpi_cpius_indice.csv"
PESO_CSV  = ROOT / "data" / "cpi_cpius_pesos.csv"

# 37 category_code -> nome legivel. Espelha Table 1 do release BLS CPI-U
# (Consumer Price Index for All Urban Consumers, U.S. city average, by
# expenditure category). Hierarquia preservada em `cpiu_table_1.csv`.
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


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, stderr=subprocess.DEVNULL
        ).decode().strip()
    except Exception:
        return "nogit"


CPIUS_CODE_VAR  = "CPIUS:{cat}/{sid}/BLS-{sha}"
CPIUS_CODE_IDX  = "CPIUS:{cat}/{sid}/Index/BLS-{sha}"
CPIUS_CODE_PESO = "CPIUS:{cat}/RI/BLS-{sha}"


def sidra_to_sql(
    series: pd.Series,
    country: str,
    subject: str,
    indicator: str,
    series_name: str,
    data_type: str,
    frequency: str,
    description: str,
    haver_code: str,
    session: SQLConnector,
    replace: bool = True,
) -> int:
    """Espelho do sidra_to_sql do sidra_itau.ipynb (limpo)."""
    df_existing = pd.read_sql(
        """
        SELECT series_id FROM OPT_Macro_Series_2
        WHERE country = ? AND subject = ? AND indicator = ?
          AND series_name = ? AND data_type = ?
        """,
        session.conn,
        params=[country, subject, indicator, series_name, data_type],
    )

    if df_existing.empty:
        df_meta = pd.DataFrame([{
            "country": country,
            "subject": subject,
            "indicator": indicator,
            "series_name": series_name,
            "data_type": data_type,
            "frequency": frequency,
            "description": description,
            "haver_code": haver_code,
        }])
        session.write_sql_table_from_dataframe("OPT_Macro_Series_2", df_meta, chunk_size=50)
        df_new = pd.read_sql(
            """
            SELECT series_id FROM OPT_Macro_Series_2
            WHERE country = ? AND subject = ? AND indicator = ?
              AND series_name = ? AND data_type = ?
            """,
            session.conn,
            params=[country, subject, indicator, series_name, data_type],
        )
        series_id = int(df_new.iloc[0]["series_id"])
    else:
        series_id = int(df_existing.iloc[0]["series_id"])

    if replace:
        session.execute(
            "DELETE FROM OPT_Macro_Series_Data_2 WHERE series_id = ?",
            params=[series_id],
        )

    s = series.dropna()
    today = date.today()
    # Alinha data ao ultimo dia do mes (convencao Haver corp).
    dates_eom = (pd.to_datetime(s.index) + pd.offsets.MonthEnd(0)).date
    df_data = pd.DataFrame({
        "date": dates_eom,
        "series_id": series_id,
        "value": s.values,
        "release_date": today,
        "vintage_date": today,
    })
    session.write_sql_table_from_dataframe(
        "OPT_Macro_Series_Data_2",
        df_data[["date", "series_id", "value", "release_date", "vintage_date"]],
        chunk_size=5_000,
    )
    return series_id


def _load_split_by_sa(path: Path, value_col: str) -> dict[tuple[str, str], tuple[pd.Series, str]]:
    """Retorna {(category_code, sa_flag): (series, series_id_BLS)}."""
    if not path.exists():
        sys.exit(f"CSV nao encontrado: {path}. Rode scripts/fetch_bls_cpiu.R primeiro.")
    df = pd.read_csv(path)
    df["date"] = pd.to_datetime(df["date"])
    out: dict[tuple[str, str], tuple[pd.Series, str]] = {}
    for (cat, sa), g in df.groupby(["category_code", "sa_flag"]):
        s = g.set_index("date")[value_col].sort_index().astype(float)
        s.name = f"{cat}/{sa}"
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


def _preflight(session, max_desc_len: int) -> bool:
    """Preflight read-only: conexao, tabelas existem, largura de description,
    lista series pre-existentes com nossa proveniencia (haver_code LIKE 'CPIUS:%')."""
    print("\n[preflight] Validando ambiente SQL...")
    ok = True

    for tbl in ("OPT_Macro_Series_2", "OPT_Macro_Series_Data_2"):
        try:
            n = pd.read_sql(f"SELECT COUNT(*) AS n FROM {tbl}", session.conn).iloc[0]["n"]
            print(f"  [OK] {tbl:22s} acessivel ({n} linhas)")
        except Exception as e:
            print(f"  [FAIL] {tbl}: {e}"); ok = False

    try:
        col = pd.read_sql(
            """SELECT character_maximum_length AS n
               FROM INFORMATION_SCHEMA.COLUMNS
               WHERE table_name = 'OPT_Macro_Series_2' AND column_name = 'description'""",
            session.conn,
        )
        if col.empty:
            print("  [WARN] description column metadata not found")
        else:
            n = int(col.iloc[0]["n"]) if col.iloc[0]["n"] is not None else -1
            if n == -1:
                print(f"  [OK] description = VARCHAR(MAX) - suporta {max_desc_len} chars")
            elif n >= max_desc_len:
                print(f"  [OK] description = VARCHAR({n}) - suporta {max_desc_len} chars")
            else:
                print(f"  [FAIL] description = VARCHAR({n}), precisa {max_desc_len}"); ok = False
    except Exception as e:
        print(f"  [WARN] nao foi possivel checar tamanho de description: {e}")

    try:
        df = pd.read_sql(
            """SELECT series_id, series_name, data_type, haver_code
               FROM OPT_Macro_Series_2
               WHERE haver_code LIKE 'CPIUS:%'
               ORDER BY series_id""",
            session.conn,
        )
        print(f"\n  Series CPIUS ja cadastradas: {len(df)}")
        if not df.empty:
            with pd.option_context("display.max_colwidth", 60, "display.width", 200):
                print(df.head(20).to_string(index=False))
            print("  -> serao reusadas (mesmo series_id); dados antigos serao apagados se --replace.")
    except Exception as e:
        print(f"  [WARN] nao foi possivel listar series CPIUS: {e}")

    return ok


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="So lista o que seria feito, sem abrir conexao SQL.")
    parser.add_argument("--check", action="store_true",
                        help="Conecta no SQL e roda preflight read-only (sem escrever).")
    parser.add_argument("--only", type=str, default=None,
                        help="Lista CSV de category_code pra carregar (ex: 'all_items,core').")
    parser.add_argument("--no-confirm", action="store_true",
                        help="Pula confirmacao interativa antes de escrever no SQL.")
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

    if args.dry_run:
        print("\n[dry-run] Seriam carregadas:")
        for c in cats:
            label = CATEGORY_LABELS[c]
            for sa in ("NSA", "SA"):
                key = (c, sa)
                if key not in var_by_key or key not in idx_by_key:
                    print(f"  - {label:55s} [{sa}]  [SKIP: faltando em recon/idx]")
                    continue
                sv, _ = var_by_key[key]
                si, _ = idx_by_key[key]
                print(f"  - {label:55s} [{sa}]  var: {len(sv)} obs   idx: {len(si)} obs")
            sp = peso_series.get(c)
            if sp is not None:
                print(f"  - {label:55s} [Peso] {len(sp)} obs")
        return

    from opt_utils.database import SQLConnector  # import preguicoso (corp-only)
    session = SQLConnector(connector="pyodbc")
    try:
        max_desc = max(
            len(f"{CATEGORY_LABELS[c]} - Indice [NSA] (rebased jan/2000=100) - BLS API v2 direto")
            for c in cats
        )
        ok = _preflight(session, max_desc)
        if args.check:
            print("\n[--check] preflight only; nada gravado.")
            return
        if not ok:
            sys.exit("\n[ABORT] preflight reprovou. Veja [FAIL] acima.")
        if not args.no_confirm:
            # 4 series NSA+SA por cat + 1 peso quando disponivel
            n_peso = sum(1 for c in cats if c in peso_series)
            n_writes = len(cats) * 4 + n_peso
            resp = input(f"\nConfirma gravacao de ate {n_writes} series no SQL? [s/N] ").strip().lower()
            if resp != "s":
                sys.exit("[ABORT] confirmacao negada.")

        for c in cats:
            label = CATEGORY_LABELS[c]
            print(f"\n--- {label} ({c}) ---")
            for sa in ("NSA", "SA"):
                key = (c, sa)
                if key not in var_by_key or key not in idx_by_key:
                    print(f"    [{sa}] SKIP: faltando em recon/idx")
                    continue
                sv, sid_bls = var_by_key[key]
                si, _ = idx_by_key[key]
                print(f"    [{sa}] var: {len(sv)} obs {sv.index.min().date()} -> {sv.index.max().date()}   idx: {len(si)} obs")

                # 1) Variacao mensal
                sidra_to_sql(
                    series=sv, country="US", subject="Prices", indicator="CPI-U",
                    series_name=label, data_type=sa, frequency="M",
                    description=f"{label} - Variacao mensal (%) [{sa}] - BLS API v2 direto",
                    haver_code=CPIUS_CODE_VAR.format(cat=c, sid=sid_bls, sha=sha),
                    session=session, replace=True,
                )
                # 2) Indice
                sidra_to_sql(
                    series=si, country="US", subject="Prices", indicator="CPI-U",
                    series_name=f"{label} (Index)", data_type=sa, frequency="M",
                    description=f"{label} - Indice [{sa}] (rebased jan/2000=100) - BLS API v2 direto",
                    haver_code=CPIUS_CODE_IDX.format(cat=c, sid=sid_bls, sha=sha),
                    session=session, replace=True,
                )
            # 3) Peso (Relative Importance Table 6 BLS). Compartilha series_name
            # com var (sync com padrao IPCA); diferenciacao so via data_type=Peso.
            sp = peso_series.get(c)
            if sp is not None:
                print(f"    [Peso] {len(sp)} obs {sp.index.min().date()} -> {sp.index.max().date()}")
                sidra_to_sql(
                    series=sp, country="US", subject="Prices", indicator="CPI-U",
                    series_name=label, data_type="Peso", frequency="M",
                    description=f"{label} - Peso (Relative Importance, Table 6 BLS)",
                    haver_code=CPIUS_CODE_PESO.format(cat=c, sha=sha),
                    session=session, replace=True,
                )

    finally:
        session.close()

    n_peso_ok = sum(1 for c in cats if c in peso_series)
    print(f"\n[OK] {len(cats)} categorias carregadas ({len(cats) * 4} NSA+SA + {n_peso_ok} Peso) em OPT_Macro_Series_2 / OPT_Macro_Series_Data_2.")


if __name__ == "__main__":
    main()


