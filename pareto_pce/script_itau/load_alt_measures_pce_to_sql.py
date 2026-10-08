#!/usr/bin/env python3
# load_alt_measures_pce_to_sql.py
#
# Carga das medidas alternativas de inflacao PCE no SQL corp Itau.
# Fonte: data/pce_alt_measures.csv (gerado por scripts/build_alt_measures_pce.py)
#
# Convenções (compat com schema existente PCE):
#   indicator="PCE", country="US", subject="Prices", frequency="M"
#   data_type="NSA"
#   bls_code="PCE:alt_{measure}_{metric}"
#   series_name="PCE: {label} [metric]"
#
# Uso:
#   cd pareto_pce
#   python script_itau/load_alt_measures_pce_to_sql.py --dry-run

import argparse
import sys
from datetime import date
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
IN_CSV = ROOT / "data" / "pce_alt_measures.csv"

MEASURE_LABELS = {
    "median_pce":              ("Median (Cleveland Fed)",         "alt_median_pce"),
    "trimmed_mean_pce_1mo":    ("Trimmed Mean (Dallas Fed)",      "alt_trimmed_mean_pce"),
    "trimmed_mean_pce_12mo":   ("Trimmed Mean (Dallas Fed)",      "alt_trimmed_mean_pce"),
}

CODE_FMT = "PCE:{code_slug}_{metric}"
INCREMENTAL_MONTHS = 24


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-confirm", action="store_true")
    ap.add_argument("--full", action="store_true")
    ap.add_argument("--only", type=str, default=None)
    args = ap.parse_args()

    if not IN_CSV.exists():
        sys.exit(f"[FAIL] {IN_CSV} nao existe. Rode scripts/build_alt_measures_pce.py primeiro.")
    df = pd.read_csv(IN_CSV, parse_dates=["date"])

    only = set(args.only.split(",")) if args.only else None
    if only:
        df = df[df["measure"].isin(only)]

    if not args.full:
        cutoff = df["date"].max() - pd.DateOffset(months=INCREMENTAL_MONTHS)
        df = df[df["date"] >= cutoff]
        print(f"[info] carga incremental (data >= {cutoff.date()})")

    # Normaliza: Dallas FRED retorna duas series separadas (1mo e 12mo); Cleveland
    # retorna uma com ambas as colunas. Agrupamos.
    print(f"\n[1] Series a carregar:")
    series_plan = []

    # Cleveland Median PCE: 1 measure, 2 metricas
    for measure in ["median_pce"]:
        g = df[df["measure"] == measure]
        if g.empty: continue
        label, code_slug = MEASURE_LABELS[measure]
        for metric, col in [("1mo", "ann_1mo"), ("12mo", "ann_12mo")]:
            s = g[["date", col]].rename(columns={col: "value"}).dropna(subset=["value"])
            if s.empty: continue
            metric_label = "1-mo annualized" if metric == "1mo" else "YoY"
            series_plan.append({
                "measure": measure, "metric": metric,
                "series_name": f"PCE: {label} [{metric_label}]",
                "bls_code": CODE_FMT.format(code_slug=code_slug, metric=metric),
                "data": s,
            })

    # Dallas FRED split: measure "_1mo" tem col ann_1mo; measure "_12mo" tem col ann_12mo
    for measure, metric, col in [
        ("trimmed_mean_pce_1mo", "1mo", "ann_1mo"),
        ("trimmed_mean_pce_12mo", "12mo", "ann_12mo"),
    ]:
        g = df[df["measure"] == measure]
        if g.empty: continue
        label, code_slug = MEASURE_LABELS[measure]
        s = g[["date", col]].rename(columns={col: "value"}).dropna(subset=["value"])
        if s.empty: continue
        metric_label = "1-mo annualized" if metric == "1mo" else "YoY"
        series_plan.append({
            "measure": measure, "metric": metric,
            "series_name": f"PCE: {label} [{metric_label}]",
            "bls_code": CODE_FMT.format(code_slug=code_slug, metric=metric),
            "data": s,
        })

    for sp in series_plan:
        print(f"  {sp['bls_code']:50s}  n={len(sp['data']):4d}  "
              f"{sp['data'].date.min().date()} -> {sp['data'].date.max().date()}")

    if args.dry_run:
        print(f"\n[DRY RUN] {len(series_plan)} series listadas.")
        return

    if not args.no_confirm:
        resp = input(f"\nConfirma {len(series_plan)} series? [s/N] ")
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
        q = session.read_sql(
            """SELECT series_id FROM OPT_Macro_Series_2
               WHERE country='US' AND subject='Prices' AND indicator='PCE'
                 AND series_name=? AND data_type='NSA'""",
            params=[sp["series_name"]],
        )
        if len(q) > 0:
            return int(q["series_id"].iloc[0])
        meta = pd.DataFrame([{
            "country": "US", "subject": "Prices", "indicator": "PCE",
            "series_name": sp["series_name"], "data_type": "NSA",
            "frequency": "M",
            "description": f"PCE alt measure {sp['measure']} ({sp['metric']}) — Fed oficial",
            "bls_code": sp["bls_code"],
        }])
        session.write_sql_table_from_dataframe(meta, "OPT_Macro_Series_2", if_exists="append")
        q = session.read_sql(
            """SELECT series_id FROM OPT_Macro_Series_2
               WHERE country='US' AND subject='Prices' AND indicator='PCE'
                 AND series_name=? AND data_type='NSA'""",
            params=[sp["series_name"]],
        )
        return int(q["series_id"].iloc[0])

    n_series = 0; n_rows = 0
    for sp in series_plan:
        sid = _ensure(sp)
        d = sp["data"].copy()
        d["date"] = (pd.to_datetime(d["date"]) + pd.offsets.MonthEnd(0)).dt.date
        d["series_id"] = sid; d["release_date"] = today; d["vintage_date"] = today
        dmin, dmax = d["date"].min(), d["date"].max()
        session.execute_sql(
            "DELETE FROM OPT_Macro_Series_Data_2 WHERE series_id=? AND date>=? AND date<=?",
            params=[sid, dmin, dmax],
        )
        session.write_sql_table_from_dataframe(
            d[["date", "series_id", "value", "release_date", "vintage_date"]],
            "OPT_Macro_Series_Data_2", if_exists="append",
        )
        n_series += 1; n_rows += len(d)
        print(f"  [{n_series}/{len(series_plan)}] {sp['bls_code']}: {len(d)} rows")

    session.close()
    print(f"\n[OK] {n_series} series x {n_rows} rows gravados.")


if __name__ == "__main__":
    main()
