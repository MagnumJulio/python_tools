#!/usr/bin/env python
# load_diffusion_to_sql.py (pareto_cpius)
# Carrega as 5 series de difusao CPI-U em OPT_Macro_Series_2 /
# OPT_Macro_Series_Data_2. Analogo do pareto_pce/script_itau/load_pce_to_sql.py.
#
# Fonte: data/cpiu_diffusion.csv gerado por scripts/build_diffusion_cpius.py.
#
# Namespace CPIUS eh disjunto de IPCA/IPCA-15/PCE:
#   - country   = 'US'
#   - subject   = 'Prices'
#   - indicator = 'CPI'
#   - bls_code  = 'CPIUS:diffusion_{name}'
# Coexiste com as 49 series de indice CPI-U (CPIUS:{cat}) — nao colidem.
#
# Uso (na maquina corp, com opt_utils disponivel):
#   cd pareto_cpius
#   python script_itau/load_diffusion_to_sql.py           # grava tudo
#   python script_itau/load_diffusion_to_sql.py --dry-run
#   python script_itau/load_diffusion_to_sql.py --check

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:
    from opt_utils.database import SQLConnector

ROOT = Path(__file__).resolve().parent.parent
DIFF_CSV = ROOT / "data" / "cpiu_diffusion.csv"

SERIES_MAP: dict[tuple[str, str], tuple[str, str, str]] = {
    ("Headline", "diffusion_yoy_3pct"): (
        "CPIUS:diffusion_headline_yoy",
        "CPI-U: Diffusion Headline (YoY > 3%)",
        "Share of CPI-U items (BLS ~177 leaves) com YoY price increase > 3%. "
        "Metodologia: contagem simples de leaves; count-based, nao ponderado.",
    ),
    ("Headline", "diffusion_6ma_ann_3pct"): (
        "CPIUS:diffusion_headline_6ma_ann",
        "CPI-U: Diffusion Headline (6m annualized > 3%)",
        "Share of CPI-U items com variacao 6m anualizada > 3%. "
        "Formula: ((idx[t]/idx[t-6])^2 - 1)*100 > 3.",
    ),
    ("Goods", "diffusion_yoy_3pct"): (
        "CPIUS:diffusion_goods_yoy",
        "CPI-U: Diffusion Goods (YoY > 3%)",
        "Share of CPI-U Goods items com YoY > 3% (BLS commodities).",
    ),
    ("Services", "diffusion_yoy_3pct"): (
        "CPIUS:diffusion_services_yoy",
        "CPI-U: Diffusion Services (YoY > 3%)",
        "Share of CPI-U Services items com YoY > 3%.",
    ),
    ("Goods_ex_cars", "diffusion_yoy_3pct"): (
        "CPIUS:diffusion_goods_ex_cars_yoy",
        "CPI-U: Diffusion Goods ex Cars (YoY > 3%)",
        "Share of CPI-U Goods excluindo motor vehicles (New vehicles, "
        "Used cars and trucks, Tires, Vehicle accessories) com YoY > 3%.",
    ),
}


def sidra_to_sql(
    series: pd.Series,
    country: str, subject: str, indicator: str,
    series_name: str, data_type: str, frequency: str,
    description: str, bls_code: str,
    session: SQLConnector, replace: bool = True,
) -> int:
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
            "country": country, "subject": subject, "indicator": indicator,
            "series_name": series_name, "data_type": data_type,
            "frequency": frequency, "description": description,
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


def _load_diffusion() -> dict[tuple[str, str], pd.Series]:
    if not DIFF_CSV.exists():
        sys.exit(f"[FAIL] {DIFF_CSV} nao existe. Rode scripts/build_diffusion_cpius.py primeiro.")
    df = pd.read_csv(DIFF_CSV, parse_dates=["date"])
    out: dict[tuple[str, str], pd.Series] = {}
    for (agg, metric), g in df.groupby(["aggregate", "metric"]):
        s = g.set_index("date")["value"].sort_index().astype(float)
        s.name = f"{agg}:{metric}"
        out[(agg, metric)] = s
    return out


def _preflight(session, max_desc_len: int) -> bool:
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
            print("  [FAIL] coluna bls_code NAO existe."); ok = False
        else:
            print("  [OK] coluna bls_code presente")
    except Exception as e:
        print(f"  [WARN] check bls_code: {e}")

    try:
        df_all = pd.read_sql(
            """SELECT series_id, series_name, data_type, haver_code, bls_code
               FROM OPT_Macro_Series_2
               WHERE bls_code LIKE 'CPIUS:diffusion_%'
               ORDER BY series_id""",
            session.conn,
        )
        print(f"\n  Series CPIUS diffusion existentes: {len(df_all)}")
        if not df_all.empty:
            with pd.option_context("display.max_colwidth", 60, "display.width", 200):
                print(df_all.to_string(index=False))
    except Exception as e:
        print(f"  [WARN] listar CPIUS diffusion: {e}")

    return ok


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--no-confirm", action="store_true")
    args = parser.parse_args()

    print(f"[1] Lendo {DIFF_CSV.relative_to(ROOT)}...")
    diff = _load_diffusion()
    print(f"    {len(diff)} series encontradas no CSV")

    keys = [k for k in SERIES_MAP if k in diff]
    missing = [k for k in SERIES_MAP if k not in diff]
    if missing:
        sys.exit(f"[FAIL] series faltando: {missing}")

    if args.dry_run:
        print("\n[dry-run] Series que seriam gravadas:")
        for k in keys:
            bls, name, desc = SERIES_MAP[k]
            s = diff[k]
            print(f"  - {name:55s}")
            print(f"    bls_code={bls}, {len(s.dropna())} obs, "
                  f"{s.dropna().index.min().date()} -> {s.dropna().index.max().date()}")
        return

    from opt_utils.database import SQLConnector
    session = SQLConnector(connector="pyodbc")
    try:
        max_desc = max(len(SERIES_MAP[k][2]) for k in keys)
        ok = _preflight(session, max_desc)
        if not ok:
            sys.exit("[FAIL] preflight falhou.")

        if args.check:
            print("\n[check] modo read-only concluido.")
            return

        if not args.no_confirm:
            resp = input(f"\nConfirma gravacao de {len(keys)} series CPI-U diffusion? [s/N] ").strip().lower()
            if resp != "s":
                sys.exit("[ABORT] confirmacao negada.")

        for k in keys:
            bls, name, desc = SERIES_MAP[k]
            s = diff[k]
            print(f"\n--- {name} ---")
            print(f"    {len(s.dropna())} obs "
                  f"{s.dropna().index.min().date()} -> {s.dropna().index.max().date()}")
            sidra_to_sql(
                series=s, country="US", subject="Prices", indicator="CPI",
                series_name=name, data_type="NSA", frequency="M",
                description=desc, bls_code=bls,
                session=session, replace=True,
            )
    finally:
        session.close()

    print(f"\n[OK] {len(keys)} series CPI-U diffusion carregadas.")


if __name__ == "__main__":
    main()
