#!/usr/bin/env python
# load_cpius_to_sql.py
# Carrega as 47 categorias do pareto_cpius (idx NSA + SA + Weight) na base SQL
# corp (OPT_Macro_Series_2 / OPT_Macro_Series_Data_2), mesmo padrao do
# sidra_itau.ipynb e do load_pareto_to_sql.py. Cada categoria vira ate 3
# series: NSA idx, SA idx, Weight. Var (NSA/SA) foi removida no sync
# 2026-07-20 pra nao lotar SQL de lixo — a variacao mensal pode ser derivada
# no consumo a partir do indice. SA vem nativo do BLS (nao precisa X-13);
# Weight vem da Table 6 do release (Relative Importance).
#
# Pre-requisito: pipeline R ja rodou:
#   cd pareto_cpius
#   Rscript scripts/fetch_bls_cpiu.R      # idx (NSA + SA), var no CSV mas nao usado aqui
#   Rscript scripts/fetch_bls_pesos.R     # peso (RI Table 6 BLS)
# Gera data/cpi_cpius_indice.csv, data/cpi_cpius_pesos.csv.
#
# Uso (na maquina corp, com opt_utils disponivel):
#   cd pareto_cpius
#   python script_itau/load_cpius_to_sql.py             # todas as 47 cats
#   python script_itau/load_cpius_to_sql.py --dry-run   # so lista o que faria
#   python script_itau/load_cpius_to_sql.py --check     # preflight so
#   python script_itau/load_cpius_to_sql.py --only all_items,core

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:
    from opt_utils.database import SQLConnector  # corp-only; import preguicoso em main()

ROOT             = Path(__file__).resolve().parent.parent
IDX_CSV          = ROOT / "data" / "cpi_cpius_indice.csv"
PESO_CSV         = ROOT / "data" / "cpi_cpius_pesos.csv"
CUSTOM_CSV       = ROOT / "data" / "cpi_cpius_custom.csv"
CUSTOM_PESOS_CSV = ROOT / "data" / "cpi_cpius_pesos_custom.csv"

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
    "core_services": "Services less energy services (BLS item SASL5)",
}

# Labels antigos (pre sync 2026-07-21) mantidos aqui pra migracao renomear
# rows existentes no SQL do label longo pro curto. Fora do escopo da migracao
# se a row estiver com series_name que nao contem o label antigo.
LEGACY_LABELS = {
    "core_goods":    "CPI-U: Commodities Less Food and Energy Commodities",
    "core_services": "CPI-U: Services Less Energy Services",
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
# series_name+country+indicator entre serie e Weight companheiro). Base e
# custom compartilham o mesmo esquema — a distincao ("é agregacao custom?")
# sai do proprio category_code (ex: `core_ex_oer` vs `core`), nao do code de
# proveniencia. haver_code (legado) fica NULL nos INSERTs novos e eh setado
# explicitamente pra NULL na migracao de rows antigas.
CODE = "CPIUS:{cat}"


def sidra_to_sql(
    series: pd.Series,
    country: str,
    subject: str,
    indicator: str,
    series_name: str,
    data_type: str,
    frequency: str,
    description: str,
    bls_code: str,
    session: SQLConnector,
    replace: bool = True,
) -> int:
    """Espelho do sidra_to_sql do sidra_itau.ipynb (limpo).
    Novos INSERTs NAO tocam em haver_code (fica NULL por default do SQL);
    o code novo grava em bls_code."""
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
            "bls_code": bls_code,
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
    """Preflight read-only: conexao, tabelas existem, coluna bls_code presente,
    largura de description, e lista series pre-existentes tanto no formato novo
    (bls_code LIKE 'CPIUS:%') quanto no antigo (haver_code LIKE 'CPIUS:%',
    pendentes de migracao)."""
    print("\n[preflight] Validando ambiente SQL...")
    ok = True

    for tbl in ("OPT_Macro_Series_2", "OPT_Macro_Series_Data_2"):
        try:
            n = pd.read_sql(f"SELECT COUNT(*) AS n FROM {tbl}", session.conn).iloc[0]["n"]
            print(f"  [OK] {tbl:22s} acessivel ({n} linhas)")
        except Exception as e:
            print(f"  [FAIL] {tbl}: {e}"); ok = False

    # Coluna bls_code existe (necessaria pra sync 2026-07-17)
    try:
        col = pd.read_sql(
            """SELECT column_name FROM INFORMATION_SCHEMA.COLUMNS
               WHERE table_name = 'OPT_Macro_Series_2' AND column_name = 'bls_code'""",
            session.conn,
        )
        if col.empty:
            print("  [FAIL] coluna bls_code NAO existe em OPT_Macro_Series_2 — "
                  "rode ALTER TABLE OPT_Macro_Series_2 ADD bls_code VARCHAR(255) NULL;")
            ok = False
        else:
            print("  [OK] coluna bls_code presente")
    except Exception as e:
        print(f"  [WARN] nao foi possivel checar coluna bls_code: {e}")

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
        df_all = pd.read_sql(
            """SELECT series_id, series_name, indicator, data_type, haver_code, bls_code
               FROM OPT_Macro_Series_2
               WHERE bls_code LIKE 'CPIUS:%' OR haver_code LIKE 'CPIUS:%'
               ORDER BY series_id""",
            session.conn,
        )
        print(f"\n  Series CPIUS existentes (qualquer formato): {len(df_all)}")
        if not df_all.empty:
            with pd.option_context("display.max_colwidth", 60, "display.width", 200):
                print(df_all.head(30).to_string(index=False))
            print("  -> qualquer row fora do formato atual (haver_code=NULL, "
                  "bls_code='CPIUS:{cat}' sem sufixo, indicator='CPI') sera "
                  "normalizada antes do main loop.")
    except Exception as e:
        print(f"  [WARN] nao foi possivel listar series CPIUS: {e}")

    return ok


def _migrate_cpius_to_current(session, cats: set[str]) -> int:
    """Traz TODA row CPIUS pro formato atual (sync 2026-07-20). Cobre 2
    origens de rows antigas:
      (A) haver_code LIKE 'CPIUS:%' — nunca migradas (formato pre 2026-07-17).
      (B) bls_code LIKE 'CPIUS:%'   — migradas em 2026-07-17-b mas com sufixo
                                       /Index no code e indicator='CPI-U'.
    Atualiza pra:
      - haver_code -> NULL (idempotente pra rows ja migradas)
      - bls_code   -> CPIUS:{cat} (colapsa /Index; distincao via series_name)
      - indicator  -> 'CPI' (era 'CPI-U')
      - data_type  -> 'Weight' (era 'Peso' em rows muito antigas)
    Idempotente: rows ja no formato final sao puladas. Somente cats no escopo
    do run. Nao apaga rows de var (data_type NSA/SA sem '(Index)' no
    series_name); elas ficam orphan apos a mudanca — cleanup separado por
    pedido explicito do usuario."""
    print("\n[migracao] Normalizando series CPIUS pro formato atual (sync 2026-07-20)...")
    df = pd.read_sql(
        """SELECT series_id, series_name, indicator, data_type, haver_code, bls_code
           FROM OPT_Macro_Series_2
           WHERE haver_code LIKE 'CPIUS:%' OR bls_code LIKE 'CPIUS:%'
           ORDER BY series_id""",
        session.conn,
    )
    if df.empty:
        print("  nenhuma serie CPIUS encontrada — nada a migrar.")
        return 0

    n_updated = 0
    n_orphan_var = 0
    n_renamed = 0
    for _, row in df.iterrows():
        code_src = row["haver_code"] if row["haver_code"] else row["bls_code"]
        cat = code_src.split(":", 1)[1].split("/", 1)[0]
        if cat not in cats:
            continue
        new_code  = CODE.format(cat=cat)
        new_dtype = "Weight" if row["data_type"] == "Peso" else row["data_type"]
        new_ind   = "CPI"
        # Sync 2026-07-21: rename series_name se estava com label antigo longo.
        legacy = LEGACY_LABELS.get(cat)
        current_name = row["series_name"] or ""
        new_name = current_name.replace(legacy, CATEGORY_LABELS[cat]) if (legacy and legacy in current_name) else current_name
        already_ok = (
            row["haver_code"] is None
            and row["bls_code"]  == new_code
            and row["indicator"] == new_ind
            and row["data_type"] == new_dtype
            and new_name == current_name
        )
        if already_ok:
            continue
        session.execute(
            "UPDATE OPT_Macro_Series_2 SET haver_code = NULL, bls_code = ?, "
            "indicator = ?, data_type = ?, series_name = ? WHERE series_id = ?",
            params=[new_code, new_ind, new_dtype, new_name, int(row["series_id"])],
        )
        n_updated += 1
        if new_name != current_name:
            n_renamed += 1
        if new_dtype in ("NSA", "SA") and "(Index)" not in current_name:
            n_orphan_var += 1
        print(f"  [UPDATE] id={row['series_id']:5d} {current_name:55s} "
              f"{row['data_type']:6s}/{row['indicator']:6s} -> "
              f"{new_dtype:6s}/{new_ind:3s}  bls_code={new_code}"
              f"{'  RENAME->' + new_name if new_name != current_name else ''}")
    print(f"  {n_updated} series migradas ({n_renamed} com rename de series_name).")
    if n_orphan_var:
        print(f"  [WARN] {n_orphan_var} rows de VAR (NSA/SA sem '(Index)') ficaram "
              f"orphan — dados nao serao atualizados. Se quiser deletar, peca "
              f"cleanup explicito.")
    return n_updated


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
    # geradas por build_custom_aggregations.R). Merge no dict de idx.
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

    if args.dry_run:
        print("\n[dry-run] Seriam carregadas:")
        for c in cats:
            label = all_labels[c]
            for sa in ("NSA", "SA"):
                key = (c, sa)
                if key not in idx_by_key:
                    print(f"  - {label:55s} [{sa}]  [SKIP: faltando em idx]")
                    continue
                si, _ = idx_by_key[key]
                tag = "[CUSTOM]" if c in custom_cats else "        "
                print(f"  - {label:55s} [{sa}]  idx: {len(si)} obs {tag}")
            sp = peso_series.get(c)
            if sp is not None:
                print(f"  - {label:55s} [Weight] {len(sp)} obs")
            print(f"    bls_code: {CODE.format(cat=c)}")
        return

    from opt_utils.database import SQLConnector  # import preguicoso (corp-only)
    session = SQLConnector(connector="pyodbc")
    try:
        max_desc = max(
            len(f"{all_labels[c]} - Indice [NSA] (rebased jan/2000=100) - custom aggregation (Laspeyres algebra)")
            for c in cats
        )
        ok = _preflight(session, max_desc)
        if args.check:
            print("\n[--check] preflight only; nada gravado.")
            return
        if not ok:
            sys.exit("\n[ABORT] preflight reprovou. Veja [FAIL] acima.")

        # Migracao: normaliza qualquer row CPIUS antiga (haver_code preenchido
        # OU bls_code com sufixo /Index OU indicator='CPI-U') pro formato atual
        # (haver_code=NULL, bls_code=CPIUS:{cat}, indicator='CPI', Peso->Weight).
        # Idempotente: rows ja no formato final sao puladas. Rows de var
        # (data_type NSA/SA sem '(Index)') ficam orphan — nao serao apagadas
        # aqui.
        _migrate_cpius_to_current(session, set(cats))

        if not args.no_confirm:
            # 2 series (idx NSA+SA) por cat + 1 Weight quando disponivel
            n_peso = sum(1 for c in cats if c in peso_series)
            n_writes = len(cats) * 2 + n_peso
            resp = input(f"\nConfirma gravacao de ate {n_writes} series no SQL? [s/N] ").strip().lower()
            if resp != "s":
                sys.exit("[ABORT] confirmacao negada.")

        for c in cats:
            label = all_labels[c]
            is_custom = c in custom_cats
            bls = CODE.format(cat=c)
            src = "custom aggregation (Laspeyres algebra)" if is_custom else "BLS API v2 direto"
            bls_def = CATEGORY_BLS_DEFS.get(c)
            def_suffix = f" - {bls_def}" if bls_def else ""
            print(f"\n--- {label} ({c}){' [CUSTOM]' if is_custom else ''} ---")
            for sa in ("NSA", "SA"):
                key = (c, sa)
                if key not in idx_by_key:
                    print(f"    [{sa}] SKIP: faltando em idx")
                    continue
                si, _ = idx_by_key[key]
                print(f"    [{sa}] idx: {len(si)} obs {si.index.min().date()} -> {si.index.max().date()}")

                sidra_to_sql(
                    series=si, country="US", subject="Prices", indicator="CPI",
                    series_name=f"{label} (Index)", data_type=sa, frequency="M",
                    description=f"{label} - Indice [{sa}] (rebased jan/2000=100){def_suffix} - {src}",
                    bls_code=bls,
                    session=session, replace=True,
                )
            # Weight. Base: RI Table 6 BLS. Custom: derivado via algebra da recipe.
            # Gravado 1x (sync 2026-07-20): pareado so com o idx via
            # series_name=f"{label} (Index)" — o var sumiu, entao a segunda
            # gravacao (com series_name=label) tambem deixou de fazer sentido.
            sp = peso_series.get(c)
            if sp is not None:
                print(f"    [Weight] {len(sp)} obs {sp.index.min().date()} -> {sp.index.max().date()}")
                peso_desc = (
                    f"{label} - Weight derivado (algebra Laspeyres da recipe){def_suffix}"
                    if is_custom else f"{label} - Weight (Relative Importance, Table 6 BLS){def_suffix}"
                )
                sidra_to_sql(
                    series=sp, country="US", subject="Prices", indicator="CPI",
                    series_name=f"{label} (Index)", data_type="Weight", frequency="M",
                    description=peso_desc,
                    bls_code=bls,
                    session=session, replace=True,
                )

    finally:
        session.close()

    n_peso_ok = sum(1 for c in cats if c in peso_series)
    n_custom_ok = sum(1 for c in cats if c in custom_cats)
    print(f"\n[OK] {len(cats)} categorias carregadas ({n_custom_ok} custom) — {len(cats) * 2} idx NSA+SA + {n_peso_ok} Weight em OPT_Macro_Series_2 / OPT_Macro_Series_Data_2.")


if __name__ == "__main__":
    main()


