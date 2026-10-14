#!/usr/bin/env python
# load_oer_regional_to_sql.py
# Carrega OER (Owners' Equivalent Rent of Residences) do CPI-U por regiao
# Census (US + 4 regions: Northeast, Midwest, South, West) na base SQL corp
# (OPT_Macro_Series_2 / OPT_Macro_Series_Data_2). Mesmo contrato do
# load_cpius_to_sql.py, mas:
#   - So Index NSA (BLS nao publica SA regional; so pra area 0000).
#   - Sem Weight (nao faz sentido isolar peso de 1 subitem por regiao).
#   - Namespace isolado: bls_code = 'CPIUS_OER:{area}'. Nao usa CPIUS:oer_...
#     pra evitar colisao com CPIUS:oer (US headline ja gravado pelo loader
#     principal) e desacoplar migrations (LIKE 'CPIUS:%' != LIKE 'CPIUS_OER:%').
#   - US (area_code='us') skipado por default — ja existe como CPIUS:oer no
#     SQL. Flag --include-us pra forcar (gera CPI-U: OER - U.S. city average
#     (Index), separado do headline existente).
#
# Pre-requisito: pipeline R ja rodou:
#   cd pareto_cpius
#   Rscript scripts/fetch_bls_oer_regional.R
# Gera data/cpi_cpius_oer_regional_indice.csv.
#
# Uso (na maquina corp, com opt_utils disponivel):
#   cd pareto_cpius
#   python script_itau/load_oer_regional_to_sql.py              # 4 regions
#   python script_itau/load_oer_regional_to_sql.py --include-us # 5 series
#   python script_itau/load_oer_regional_to_sql.py --dry-run    # so lista
#   python script_itau/load_oer_regional_to_sql.py --check      # preflight only
#   python script_itau/load_oer_regional_to_sql.py --only northeast,south

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:
    from opt_utils.database import SQLConnector  # corp-only; lazy import em main()

ROOT    = Path(__file__).resolve().parent.parent
IDX_CSV = ROOT / "data" / "cpi_cpius_oer_regional_indice.csv"
MAP_CSV = ROOT / "scripts" / "bls_maps" / "cpiu_oer_regional.csv"

CODE = "CPIUS_OER:{area}"


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
    """Espelho do sidra_to_sql do load_cpius_to_sql.py. Novos INSERTs nao
    tocam em haver_code (fica NULL por default do SQL); o code vai em bls_code."""
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


def _load_area_map(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        sys.exit(f"Mapa nao encontrado: {path}")
    df = pd.read_csv(path, dtype={"bls_area": str})
    df["bls_area"] = df["bls_area"].str.zfill(4)
    return {
        row["area_code"]: {
            "area_label": row["area_label"],
            "bls_area":   row["bls_area"],
            "item_code":  row["item_code"],
            "series_id":  f"CUUR{row['bls_area']}{row['item_code']}",
        }
        for _, row in df.iterrows()
    }


def _load_oer_regional(path: Path) -> dict[str, pd.Series]:
    """Retorna {area_code: series_index}."""
    if not path.exists():
        sys.exit(f"CSV nao encontrado: {path}. Rode scripts/fetch_bls_oer_regional.R.")
    df = pd.read_csv(path)
    df["date"] = pd.to_datetime(df["date"])
    out: dict[str, pd.Series] = {}
    for area, g in df.groupby("area_code"):
        s = g.set_index("date")["index"].sort_index().astype(float)
        s.name = area
        out[area] = s
    return out


def _series_name(area_label: str) -> str:
    return f"CPI-U: OER - {area_label} (Index)"


def _preflight(session, max_desc_len: int) -> bool:
    """Preflight read-only: tabelas acessiveis, coluna bls_code presente,
    description cabe, e lista series CPIUS_OER:% pre-existentes."""
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
               WHERE bls_code LIKE 'CPIUS_OER:%'
               ORDER BY series_id""",
            session.conn,
        )
        print(f"\n  Series CPIUS_OER existentes: {len(df_all)}")
        if not df_all.empty:
            with pd.option_context("display.max_colwidth", 60, "display.width", 200):
                print(df_all.to_string(index=False))
    except Exception as e:
        print(f"  [WARN] nao foi possivel listar series CPIUS_OER: {e}")

    return ok


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="So lista o que seria feito, sem abrir conexao SQL.")
    parser.add_argument("--check", action="store_true",
                        help="Conecta no SQL e roda preflight read-only (sem escrever).")
    parser.add_argument("--only", type=str, default=None,
                        help="Lista CSV de area_code pra carregar (ex: 'northeast,south').")
    parser.add_argument("--include-us", action="store_true",
                        help="Inclui US (area_code=us) no load. Default: skipa pq ja "
                             "existe no SQL via CPIUS:oer do loader principal.")
    parser.add_argument("--no-confirm", action="store_true",
                        help="Pula confirmacao interativa antes de escrever no SQL.")
    args = parser.parse_args()

    only = set(args.only.split(",")) if args.only else None

    print(f"[1] Lendo mapa {MAP_CSV.relative_to(ROOT)}...")
    amap = _load_area_map(MAP_CSV)
    print(f"    {len(amap)} areas")

    print(f"[2] Lendo {IDX_CSV.relative_to(ROOT)}...")
    series_by_area = _load_oer_regional(IDX_CSV)
    print(f"    {len(series_by_area)} series carregadas")

    areas = sorted(series_by_area)
    if not args.include_us:
        areas = [a for a in areas if a != "us"]
    if only:
        areas = [a for a in areas if a in only]
    missing_map = [a for a in areas if a not in amap]
    if missing_map:
        sys.exit(f"Falta entrada em cpiu_oer_regional.csv pra: {missing_map}")

    if args.dry_run:
        print("\n[dry-run] Seriam carregadas:")
        for area in areas:
            meta = amap[area]
            sn = _series_name(meta["area_label"])
            si = series_by_area[area]
            print(f"  - {sn:60s} [NSA]  idx: {len(si)} obs  bls_code: {CODE.format(area=area)}")
        return

    from opt_utils.database import SQLConnector  # import preguicoso (corp-only)
    session = SQLConnector(connector="pyodbc")
    try:
        max_desc = max(
            len(
                f"CPI-U OER (Owners' Equivalent Rent of Residences) - {amap[a]['area_label']} "
                f"- Indice NSA (base nativa DEZ 1982=100, rebased jan/2000=100 pra "
                f"comparabilidade) - BLS API v2 ({amap[a]['series_id']})"
            )
            for a in areas
        )
        ok = _preflight(session, max_desc)
        if args.check:
            print("\n[--check] preflight only; nada gravado.")
            return
        if not ok:
            sys.exit("\n[ABORT] preflight reprovou. Veja [FAIL] acima.")

        if not args.no_confirm:
            resp = input(f"\nConfirma gravacao de {len(areas)} series no SQL? [s/N] ").strip().lower()
            if resp != "s":
                sys.exit("[ABORT] confirmacao negada.")

        for area in areas:
            meta = amap[area]
            sn = _series_name(meta["area_label"])
            bls = CODE.format(area=area)
            si = series_by_area[area]
            desc = (
                f"CPI-U OER (Owners' Equivalent Rent of Residences) - {meta['area_label']} "
                f"- Indice NSA (base nativa DEZ 1982=100, rebased jan/2000=100 pra "
                f"comparabilidade) - BLS API v2 ({meta['series_id']})"
            )
            print(f"\n--- {sn} ---")
            print(f"    [NSA] idx: {len(si)} obs  {si.index.min().date()} -> {si.index.max().date()}  bls_code={bls}")
            sidra_to_sql(
                series=si, country="US", subject="Prices", indicator="CPI",
                series_name=sn, data_type="NSA", frequency="M",
                description=desc,
                bls_code=bls,
                session=session, replace=True,
            )
    finally:
        session.close()

    print(f"\n[OK] {len(areas)} series OER regional carregadas em OPT_Macro_Series_2 / OPT_Macro_Series_Data_2.")


if __name__ == "__main__":
    main()
