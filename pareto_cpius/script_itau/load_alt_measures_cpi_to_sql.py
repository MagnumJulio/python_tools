#!/usr/bin/env python3
# load_alt_measures_cpi_to_sql.py
#
# Carga das medidas alternativas de inflacao CPI-U no SQL corp Itau.
# Fonte: data/cpi_cpius_alt_measures.csv (gerado por scripts/build_alt_measures_cpi.py)
#
# Cada measure vira 1-2 series no SQL:
#   - {measure}_1mo: 1-month annualized percent change
#   - {measure}_12mo: year-over-year percent change (quando disponivel)
#
# Convenções (compat com schema existente CPI-U):
#   indicator="CPI", country="US", subject="Prices", frequency="M"
#   data_type="NSA" (os valores sao rates, nao idx; nativamente SA pelos Feds)
#   bls_code="CPIUS:alt_{measure}_{metric}"  (ex: CPIUS:alt_median_cpi_1mo)
#   series_name="CPI-U: {label} [metric]"
#   haver_code=NULL
#
# Uso:
#   cd pareto_cpius
#   python script_itau/load_alt_measures_cpi_to_sql.py --dry-run
#   python script_itau/load_alt_measures_cpi_to_sql.py                # pede confirmacao
#   python script_itau/load_alt_measures_cpi_to_sql.py --no-confirm   # sem prompt

import argparse
import sys
from datetime import date
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
IN_CSV = ROOT / "data" / "cpi_cpius_alt_measures.csv"

# Mapa measure -> label legivel. Chave bate com measure no CSV.
MEASURE_LABELS = {
    "median_cpi":                   ("Median (Cleveland Fed)",         "alt_median_cpi"),
    "trimmed_mean_16_cpi":          ("Trimmed Mean 16% (Cleveland Fed)", "alt_trimmed_mean_16_cpi"),
    "trimmed_sym_25_cpi_custom":    ("Trimmed Sym 25% (custom)",       "alt_trimmed_sym_25_cpi_custom"),
    "sticky_cpi":                   ("Sticky-Price (Atlanta Fed)",     "alt_sticky_cpi"),
    "core_sticky_cpi":              ("Core Sticky-Price (Atlanta Fed)", "alt_core_sticky_cpi"),
    "sticky_cpi_ex_shelter":        ("Sticky-Price ex Shelter (Atlanta Fed)", "alt_sticky_cpi_ex_shelter"),
    "core_sticky_cpi_ex_shelter":   ("Core Sticky-Price ex Shelter (Atlanta Fed)", "alt_core_sticky_cpi_ex_shelter"),
    "flexible_cpi":                 ("Flexible-Price (Atlanta Fed)",   "alt_flexible_cpi"),
    "core_flexible_cpi":            ("Core Flexible-Price (Atlanta Fed)", "alt_core_flexible_cpi"),
}

CODE_FMT = "CPIUS:{code_slug}_{metric}"

INCREMENTAL_MONTHS = 24   # carrega so os ultimos N meses na rotina normal


def _load_df() -> pd.DataFrame:
    if not IN_CSV.exists():
        sys.exit(f"[FAIL] {IN_CSV} nao existe. Rode scripts/build_alt_measures_cpi.py primeiro.")
    df = pd.read_csv(IN_CSV, parse_dates=["date"])
    missing = set(df["measure"].unique()) - set(MEASURE_LABELS)
    if missing:
        print(f"[WARN] measures no CSV sem label em MEASURE_LABELS: {missing}")
    return df


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="So lista o que faria.")
    ap.add_argument("--no-confirm", action="store_true", help="Pula prompt.")
    ap.add_argument("--full", action="store_true", help="Carga full history (default: ultimos 24m).")
    ap.add_argument("--only", type=str, default=None,
                    help="Lista CSV de measures pra carregar (ex: 'median_cpi,sticky_cpi').")
    args = ap.parse_args()

    df = _load_df()

    only = set(args.only.split(",")) if args.only else None
    if only:
        df = df[df["measure"].isin(only)]

    if not args.full:
        cutoff = df["date"].max() - pd.DateOffset(months=INCREMENTAL_MONTHS)
        df = df[df["date"] >= cutoff]
        print(f"[info] carga incremental: ultimos {INCREMENTAL_MONTHS} meses "
              f"(data >= {cutoff.date()})")

    # Monta payload: 1 serie por (measure, metric). metric ∈ {1mo, 12mo}
    print(f"\n[1] Series a carregar:")
    series_plan = []
    for measure, g in df.groupby("measure"):
        if measure not in MEASURE_LABELS:
            continue
        label, code_slug = MEASURE_LABELS[measure]
        for metric, col in [("1mo", "ann_1mo"), ("12mo", "ann_12mo")]:
            s = g[["date", col]].rename(columns={col: "value"}).dropna(subset=["value"])
            if s.empty:
                continue
            metric_label = "1-mo annualized" if metric == "1mo" else "YoY"
            series_plan.append({
                "measure": measure,
                "metric": metric,
                "series_name": f"CPI-U: {label} [{metric_label}]",
                "bls_code": CODE_FMT.format(code_slug=code_slug, metric=metric),
                "data": s,
            })
            print(f"  {series_plan[-1]['bls_code']:50s}  n={len(s):4d}  "
                  f"{s.date.min().date()} -> {s.date.max().date()}")

    if args.dry_run:
        print(f"\n[DRY RUN] {len(series_plan)} series listadas, nada escrito.")
        return

    if not args.no_confirm:
        resp = input(f"\nConfirma carga de {len(series_plan)} series no SQL corp? [s/N] ")
        if resp.strip().lower() not in ("s", "sim", "y", "yes"):
            print("Abortado pelo usuario.")
            return

    # Carga real — so disponivel no corp
    try:
        from opt_utils.database import SQLConnector
    except ImportError:
        sys.exit("[FAIL] opt_utils nao disponivel. Esse load so roda no corp Itau.")

    session = SQLConnector(connector="pyodbc")
    today = date.today()

    def _ensure_series(sp: dict) -> int:
        """Lookup ou INSERT em OPT_Macro_Series_2. Retorna series_id."""
        q = session.read_sql(
            """SELECT series_id FROM OPT_Macro_Series_2
               WHERE country='US' AND subject='Prices' AND indicator='CPI'
                 AND series_name=? AND data_type='NSA'""",
            params=[sp["series_name"]],
        )
        if len(q) > 0:
            return int(q["series_id"].iloc[0])
        meta = pd.DataFrame([{
            "country": "US", "subject": "Prices", "indicator": "CPI",
            "series_name": sp["series_name"], "data_type": "NSA",
            "frequency": "M",
            "description": f"CPI-U alt measure {sp['measure']} ({sp['metric']}) — Fed oficial",
            "bls_code": sp["bls_code"],
        }])
        session.write_sql_table_from_dataframe(meta, "OPT_Macro_Series_2", if_exists="append")
        q = session.read_sql(
            """SELECT series_id FROM OPT_Macro_Series_2
               WHERE country='US' AND subject='Prices' AND indicator='CPI'
                 AND series_name=? AND data_type='NSA'""",
            params=[sp["series_name"]],
        )
        return int(q["series_id"].iloc[0])

    n_series = 0
    n_rows = 0
    for sp in series_plan:
        series_id = _ensure_series(sp)
        data = sp["data"].copy()
        # EOM pra bater o padrao dos outros loaders
        data["date"] = (pd.to_datetime(data["date"]) + pd.offsets.MonthEnd(0)).dt.date
        data["series_id"] = series_id
        data["release_date"] = today
        data["vintage_date"] = today
        # Substitui o range coberto
        dmin, dmax = data["date"].min(), data["date"].max()
        session.execute_sql(
            "DELETE FROM OPT_Macro_Series_Data_2 WHERE series_id=? AND date>=? AND date<=?",
            params=[series_id, dmin, dmax],
        )
        session.write_sql_table_from_dataframe(
            data[["date", "series_id", "value", "release_date", "vintage_date"]],
            "OPT_Macro_Series_Data_2", if_exists="append",
        )
        n_series += 1
        n_rows += len(data)
        print(f"  [{n_series}/{len(series_plan)}] {sp['bls_code']}: {len(data)} rows")

    session.close()
    print(f"\n[OK] {n_series} series x {n_rows} rows gravados.")


if __name__ == "__main__":
    main()
