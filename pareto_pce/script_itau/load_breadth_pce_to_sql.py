#!/usr/bin/env python3
# load_breadth_pce_to_sql.py
#
# Carga das 3 series de inflation breadth PCE no SQL corp Itau.
# Fonte: data/pce_breadth.csv (gerado por scripts/build_breadth_pce.py)
#
# 3 series, todas country="US", subject="Prices", indicator="PCE",
# data_type="NSA" (series temporais, nao transformacao):
#
#   bls_code                   series_name
#   PCE:breadth_above_3pct     PCE: Breadth (share YoY > 3%)
#   PCE:breadth_0_to_3pct      PCE: Breadth (share 0 <= YoY <= 3%)
#   PCE:breadth_below_0pct     PCE: Breadth (share YoY < 0%)
#
# Valores sao percentuais 0-100; soma dos 3 bins = 100 em cada mes.
# Pesos: nominais BEA U20405 (current dollars) do proprio mes.
#
# Uso:
#   cd pareto_pce
#   python script_itau/load_breadth_pce_to_sql.py --dry-run
#   python script_itau/load_breadth_pce_to_sql.py --no-confirm --full

import argparse
import sys
from datetime import date
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
IN_CSV = ROOT / "data" / "pce_breadth.csv"

BIN_META = {
    # bin_code -> (series_name, bls_code)
    "above_3pct": ("PCE: Breadth (share YoY > 3%)",       "PCE:breadth_above_3pct"),
    "0_to_3pct":  ("PCE: Breadth (share 0 <= YoY <= 3%)", "PCE:breadth_0_to_3pct"),
    "below_0pct": ("PCE: Breadth (share YoY < 0%)",       "PCE:breadth_below_0pct"),
}

INCREMENTAL_MONTHS = 24


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="So lista o que faria.")
    ap.add_argument("--no-confirm", action="store_true", help="Pula prompt.")
    ap.add_argument("--full", action="store_true", help="Carga full history (default: 24m).")
    args = ap.parse_args()

    if not IN_CSV.exists():
        sys.exit(f"[FAIL] {IN_CSV} nao existe. Rode scripts/build_breadth_pce.py primeiro.")
    df = pd.read_csv(IN_CSV, parse_dates=["date"])

    if not args.full:
        cutoff = df["date"].max() - pd.DateOffset(months=INCREMENTAL_MONTHS)
        df = df[df["date"] >= cutoff]
        print(f"[info] carga incremental (data >= {cutoff.date()})")

    print(f"\n[1] Series a carregar:")
    series_plan = []
    for bin_code, (sname, bls) in BIN_META.items():
        sub = df[df["bin"] == bin_code][["date", "weight_share"]].rename(
            columns={"weight_share": "value"}
        ).dropna(subset=["value"])
        if sub.empty:
            print(f"  [SKIP] {bls} — zero rows no CSV")
            continue
        series_plan.append({
            "bin": bin_code,
            "series_name": sname,
            "bls_code": bls,
            "data": sub,
        })
        print(f"  {bls:35s}  n={len(sub):4d}  "
              f"{sub.date.min().date()} -> {sub.date.max().date()}")

    if args.dry_run:
        print(f"\n[DRY RUN] {len(series_plan)} series listadas, nada escrito.")
        return

    if not args.no_confirm:
        resp = input(f"\nConfirma carga de {len(series_plan)} series no SQL corp? [s/N] ")
        if resp.strip().lower() not in ("s", "sim", "y", "yes"):
            print("Abortado.")
            return

    try:
        from opt_utils.database import SQLConnector
    except ImportError:
        sys.exit("[FAIL] opt_utils nao disponivel. Esse load so roda no corp Itau.")

    session = SQLConnector(connector="pyodbc")
    today = date.today()

    def _ensure(sp):
        q = pd.read_sql(
            """SELECT series_id FROM OPT_Macro_Series_2
               WHERE country='US' AND subject='Prices' AND indicator='PCE'
                 AND series_name=? AND data_type='NSA'""",
            session.conn,
            params=[sp["series_name"]],
        )
        if len(q) > 0:
            return int(q["series_id"].iloc[0])
        meta = pd.DataFrame([{
            "country": "US", "subject": "Prices", "indicator": "PCE",
            "series_name": sp["series_name"], "data_type": "NSA",
            "frequency": "M",
            "description": f"PCE inflation breadth bin ({sp['bin']}) — "
                           f"share do peso agregado em leaves do U20404 cujo YoY "
                           f"cai no bin. Peso nominais BEA U20405 do proprio mes.",
            "bls_code": sp["bls_code"],
        }])
        session.write_sql_table_from_dataframe("OPT_Macro_Series_2", meta, chunk_size=50)
        q = pd.read_sql(
            """SELECT series_id FROM OPT_Macro_Series_2
               WHERE country='US' AND subject='Prices' AND indicator='PCE'
                 AND series_name=? AND data_type='NSA'""",
            session.conn,
            params=[sp["series_name"]],
        )
        return int(q["series_id"].iloc[0])

    n_series = 0; n_rows = 0
    for sp in series_plan:
        sid = _ensure(sp)
        # Pattern load_cpius_to_sql.py / fix HYC00 do CPI 2026-10-28:
        # DELETE WHERE series_id = ? so, nao binda data (driver corp cospe
        # HYC00 em `date>=? AND date<=?` com datetime.date). Como --full
        # re-escreve tudo, deletar tudo da serie da no mesmo resultado.
        session.execute(
            "DELETE FROM OPT_Macro_Series_Data_2 WHERE series_id = ?",
            params=[sid],
        )
        # DataFrame do zero (padrao cpius loader) pra evitar quirks de dtype
        # object em coluna mutada por .dt.date.
        src = sp["data"]
        dates_eom = (pd.to_datetime(src["date"]) + pd.offsets.MonthEnd(0)).dt.date.values
        df_data = pd.DataFrame({
            "date": dates_eom,
            "series_id": sid,
            "value": src["value"].values,
            "release_date": today,
            "vintage_date": today,
        })
        session.write_sql_table_from_dataframe(
            "OPT_Macro_Series_Data_2",
            df_data[["date", "series_id", "value", "release_date", "vintage_date"]],
            chunk_size=5_000,
        )
        n_series += 1; n_rows += len(df_data)
        print(f"  [{n_series}/{len(series_plan)}] {sp['bls_code']}: {len(df_data)} rows")

    session.close()
    print(f"\n[OK] {n_series} series x {n_rows} rows gravados.")


if __name__ == "__main__":
    main()
