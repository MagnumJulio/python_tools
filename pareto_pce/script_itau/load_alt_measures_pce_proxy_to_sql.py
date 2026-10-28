#!/usr/bin/env python3
# load_alt_measures_pce_proxy_to_sql.py
#
# Carga das 2 series de alt measures PCE RECONSTRUIDAS bottom-up (nao
# scraped). Fonte: data/pce_alt_measures_proxy.csv (gerado por
# scripts/build_alt_measures_pce_proxy.py).
#
# Pipeline PARALELO ao load_alt_measures_pce_to_sql.py (que serve
# Cleveland CSV + Dallas FRED oficiais). Objetivo: ter os 2 lado-a-lado
# no SQL pra decomposicao e sensibilidade — NAO substitui oficial.
#
# Convencoes identicas ao loader oficial (SA, Index level, rebase Jan/2000=100):
#   bls_code    = "PCE:alt_{measure_slug}_proxy"
#   series_name = "PCE: {label} (Index, proxy bottom-up Itau)"
#   data_type   = "SA"
#   indicator   = "PCE", country = "US", subject = "Prices", frequency = "M"
#
# 2 series:
#   PCE:alt_median_pce_proxy
#   PCE:alt_trimmed_mean_pce_proxy
#
# Methodology (build_alt_measures_pce_proxy.py):
#  - Universe: 190 leaves U20404 (mesmo breadth/diffusion/altas_dist)
#  - Peso: nominais U20405 do mes
#  - Median: weighted 50th percentile de MoM SAAR
#  - Trimmed Mean: 24% low + 31% high asimetrico (Dallas)
#  - Chain + rebase Jan/2000=100
#
# Validado 2026-10-28 vs oficiais: mean|d| no YoY = 0.10pp (median) e
# 0.09pp (trim mean). Bem abaixo do threshold 0.3pp "bom".
#
# Uso:
#   cd pareto_pce
#   python script_itau/load_alt_measures_pce_proxy_to_sql.py --dry-run
#   python script_itau/load_alt_measures_pce_proxy_to_sql.py --no-confirm

import argparse
import sys
from datetime import date
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
IN_CSV = ROOT / "data" / "pce_alt_measures_proxy.csv"

MEASURE_LABELS = {
    "median_pce_proxy":       ("Median PCE",       "alt_median_pce_proxy"),
    "trimmed_mean_pce_proxy": ("Trimmed Mean PCE", "alt_trimmed_mean_pce_proxy"),
}

CODE_FMT = "PCE:{code_slug}"


def _load_df() -> pd.DataFrame:
    if not IN_CSV.exists():
        sys.exit(f"[FAIL] {IN_CSV} nao existe. "
                 f"Rode scripts/build_alt_measures_pce_proxy.py primeiro.")
    df = pd.read_csv(IN_CSV, parse_dates=["date"])
    if "value_index" not in df.columns:
        sys.exit(f"[FAIL] {IN_CSV.name} sem coluna 'value_index'.")
    missing = set(df["measure"].unique()) - set(MEASURE_LABELS)
    if missing:
        print(f"[WARN] measures no CSV sem label em MEASURE_LABELS: {missing}")
    return df


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="So lista o que faria.")
    ap.add_argument("--no-confirm", action="store_true", help="Pula prompt.")
    ap.add_argument("--incremental", action="store_true",
                    help="Carga incremental (ultimos 24m). Default: full history.")
    ap.add_argument("--only", type=str, default=None,
                    help="Lista CSV de measures (ex: 'median_pce_proxy').")
    args = ap.parse_args()

    df = _load_df()

    only = set(args.only.split(",")) if args.only else None
    if only:
        df = df[df["measure"].isin(only)]

    if args.incremental:
        cutoff = df["date"].max() - pd.DateOffset(months=24)
        df = df[df["date"] >= cutoff]
        print(f"[info] carga incremental (data >= {cutoff.date()})")
    else:
        print(f"[info] carga full history. Use --incremental pra ultimos 24m.")

    print(f"\n[1] Series a carregar (proxy bottom-up Itau, so Index SA):")
    series_plan = []
    for measure, g in df.groupby("measure"):
        if measure not in MEASURE_LABELS:
            continue
        label, code_slug = MEASURE_LABELS[measure]
        s = g[["date", "value_index"]].rename(columns={"value_index": "value"}).dropna(subset=["value"])
        if s.empty:
            print(f"  [SKIP] {measure}: zero obs com value_index")
            continue
        series_plan.append({
            "measure": measure,
            "series_name": f"PCE: {label} (Index, proxy bottom-up Itau)",
            "bls_code": CODE_FMT.format(code_slug=code_slug),
            "data": s,
        })
        print(f"  {series_plan[-1]['bls_code']:50s}  n={len(s):4d}  "
              f"{s.date.min().date()} -> {s.date.max().date()}")

    if args.dry_run:
        print(f"\n[DRY RUN] {len(series_plan)} series listadas, nada escrito.")
        return

    if not args.no_confirm:
        resp = input(
            f"\nConfirma carga de {len(series_plan)} series proxy (Index SA) "
            f"no SQL corp? [s/N] "
        )
        if resp.strip().lower() not in ("s", "sim", "y", "yes"):
            print("Abortado pelo usuario.")
            return

    try:
        from opt_utils.database import SQLConnector
    except ImportError:
        sys.exit("[FAIL] opt_utils nao disponivel. Esse load so roda no corp Itau.")

    session = SQLConnector(connector="pyodbc")
    today = date.today()

    def _ensure_series(sp: dict) -> int:
        q = pd.read_sql(
            """SELECT series_id FROM OPT_Macro_Series_2
               WHERE country='US' AND subject='Prices' AND indicator='PCE'
                 AND series_name=? AND data_type='SA'""",
            session.conn,
            params=[sp["series_name"]],
        )
        if len(q) > 0:
            return int(q["series_id"].iloc[0])
        meta = pd.DataFrame([{
            "country": "US", "subject": "Prices", "indicator": "PCE",
            "series_name": sp["series_name"], "data_type": "SA",
            "frequency": "M",
            "description": (
                f"PCE alt measure {sp['measure']} (Index, SA, rebase Jan/2000=100). "
                f"Reconstruct bottom-up Itau: 190 leaves U20404 ponderados por "
                f"nominais U20405. Median = weighted 50th percentile MoM SAAR; "
                f"Trimmed Mean = trim 24/31 asimetrico Dallas. Validado 2026-10-28: "
                f"mean|d| YoY vs oficial < 0.11pp. NAO substitui o oficial — "
                f"pair com PCE:alt_{sp['measure'].replace('_proxy', '')} pra "
                f"decomposicao/sensibilidade."
            ),
            "bls_code": sp["bls_code"],
        }])
        session.write_sql_table_from_dataframe("OPT_Macro_Series_2", meta, chunk_size=50)
        q = pd.read_sql(
            """SELECT series_id FROM OPT_Macro_Series_2
               WHERE country='US' AND subject='Prices' AND indicator='PCE'
                 AND series_name=? AND data_type='SA'""",
            session.conn,
            params=[sp["series_name"]],
        )
        return int(q["series_id"].iloc[0])

    n_series = 0
    n_rows = 0
    for sp in series_plan:
        series_id = _ensure_series(sp)
        # Pattern HYC00-safe: DELETE WHERE series_id = ? so.
        session.execute(
            "DELETE FROM OPT_Macro_Series_Data_2 WHERE series_id = ?",
            params=[series_id],
        )
        src = sp["data"]
        dates_eom = (pd.to_datetime(src["date"]) + pd.offsets.MonthEnd(0)).dt.date.values
        df_data = pd.DataFrame({
            "date": dates_eom,
            "series_id": series_id,
            "value": src["value"].values,
            "release_date": today,
            "vintage_date": today,
        })
        session.write_sql_table_from_dataframe(
            "OPT_Macro_Series_Data_2",
            df_data[["date", "series_id", "value", "release_date", "vintage_date"]],
            chunk_size=5_000,
        )
        n_series += 1
        n_rows += len(df_data)
        print(f"  [{n_series}/{len(series_plan)}] {sp['bls_code']}: {len(df_data)} rows")

    session.close()
    print(f"\n[OK] {n_series} series x {n_rows} rows gravados.")


if __name__ == "__main__":
    main()
