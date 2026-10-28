#!/usr/bin/env python3
# load_alt_measures_pce_to_sql.py
#
# Carga das medidas alternativas de inflacao PCE no SQL corp Itau.
# Fonte: data/pce_alt_measures.csv (gerado por scripts/build_alt_measures_pce.py)
#
# Sync 2026-10-28: alinhado com padrao CPI (sync 2026-10-28) — apenas INDEX
# (level, SA, rebase Jan/2000=100) sobe pro SQL. As variantes ann_1mo /
# mom_sa / ann_12mo foram descontinuadas no SQL (ficam so no CSV). Cada
# measure vira UMA serie:
#
#   bls_code    = "PCE:alt_{measure_slug}"
#   series_name = "PCE: {label} (Index)"
#   data_type   = "SA" (todas as fontes publicam SA — Cleveland + Dallas)
#   indicator   = "PCE", country = "US", subject = "Prices", frequency = "M"
#
# Dallas FRED IDs atualizados em 2026-10 (PCETRIM1M158SFRBDAL +
# PCETRIM12M159SFRBDAL — antigos 680SFRBDAL retornavam 404). Loader tambem
# roda _cleanup_legacy_alt() antes do upsert: deleta qualquer linha
# PCE:alt_% que NAO esteja no plano atual (as variantes antigas
# `_1mo`/`_mom_sa`/`_12mo` + `trimmed_mean_pce_{1mo,12mo}` fragmentadas).
# Idempotente apos o primeiro run.
#
# Uso:
#   cd pareto_pce
#   python script_itau/load_alt_measures_pce_to_sql.py --dry-run
#   python script_itau/load_alt_measures_pce_to_sql.py                # pede confirmacao
#   python script_itau/load_alt_measures_pce_to_sql.py --no-confirm   # sem prompt

import argparse
import sys
from datetime import date
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
IN_CSV = ROOT / "data" / "pce_alt_measures.csv"

# Mapa measure -> (label legivel, slug no bls_code).
MEASURE_LABELS = {
    "median_pce":       ("Median (Cleveland Fed)",       "alt_median_pce"),
    "trimmed_mean_pce": ("Trimmed Mean (Dallas Fed)",    "alt_trimmed_mean_pce"),
}

CODE_FMT = "PCE:{code_slug}"


def _load_df() -> pd.DataFrame:
    if not IN_CSV.exists():
        sys.exit(f"[FAIL] {IN_CSV} nao existe. Rode scripts/build_alt_measures_pce.py primeiro.")
    df = pd.read_csv(IN_CSV, parse_dates=["date"])
    if "value_index" not in df.columns:
        sys.exit(f"[FAIL] {IN_CSV.name} sem coluna 'value_index'. "
                 f"Re-rode scripts/build_alt_measures_pce.py (sync 2026-10-28).")
    missing = set(df["measure"].unique()) - set(MEASURE_LABELS)
    if missing:
        print(f"[WARN] measures no CSV sem label em MEASURE_LABELS: {missing}")
    return df


def _cleanup_legacy_alt(session, keep_codes: set[str]) -> int:
    """Deleta series PCE:alt_% que NAO estao no plano atual. Cobre:
      - Variantes legadas `_1mo`/`_mom_sa`/`_12mo` (data_type='NSA') removidas
        no sync 2026-10-28.
      - Variantes fragmentadas Dallas `trimmed_mean_pce_1mo`/`_12mo`
        agora consolidadas em `trimmed_mean_pce`.
    Deleta data primeiro, depois metadata. Idempotente."""
    print("\n[cleanup] procurando series PCE:alt_% legadas...")
    df = pd.read_sql(
        "SELECT series_id, series_name, data_type, bls_code "
        "FROM OPT_Macro_Series_2 WHERE bls_code LIKE 'PCE:alt_%'",
        session.conn,
    )
    if df.empty:
        print("  nenhuma serie PCE:alt_% no SQL — nada a limpar.")
        return 0
    to_drop = df[~df["bls_code"].isin(keep_codes)]
    if to_drop.empty:
        print(f"  todas as {len(df)} series PCE:alt_% ja estao no plano atual.")
        return 0
    print(f"  {len(to_drop)} series legadas a apagar:")
    with pd.option_context("display.max_colwidth", 60, "display.width", 200):
        print(to_drop.to_string(index=False))
    n = 0
    for sid in to_drop["series_id"].astype(int):
        session.execute(
            "DELETE FROM OPT_Macro_Series_Data_2 WHERE series_id = ?",
            params=[int(sid)],
        )
        session.execute(
            "DELETE FROM OPT_Macro_Series_2 WHERE series_id = ?",
            params=[int(sid)],
        )
        n += 1
    print(f"  [OK] {n} series legadas deletadas (data + metadata).")
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="So lista o que faria.")
    ap.add_argument("--no-confirm", action="store_true", help="Pula prompt.")
    ap.add_argument("--incremental", action="store_true",
                    help="Carga incremental (ultimos 24m). Default: full history (sync 2026-10-28).")
    ap.add_argument("--only", type=str, default=None,
                    help="Lista CSV de measures (ex: 'median_pce,trimmed_mean_pce').")
    args = ap.parse_args()

    df = _load_df()

    only = set(args.only.split(",")) if args.only else None
    if only:
        df = df[df["measure"].isin(only)]

    if args.incremental:
        cutoff = df["date"].max() - pd.DateOffset(months=24)
        df = df[df["date"] >= cutoff]
        print(f"[info] carga incremental: ultimos 24 meses (data >= {cutoff.date()})")
    else:
        print(f"[info] carga full history (default sync 2026-10-28). "
              f"Use --incremental pra ultimos 24m.")

    print(f"\n[1] Series a carregar (1 por measure, so Index SA):")
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
            "series_name": f"PCE: {label} (Index)",
            "bls_code": CODE_FMT.format(code_slug=code_slug),
            "data": s,
        })
        print(f"  {series_plan[-1]['bls_code']:50s}  n={len(s):4d}  "
              f"{s.date.min().date()} -> {s.date.max().date()}")

    keep_codes = {sp["bls_code"] for sp in series_plan}

    if args.dry_run:
        print(f"\n[DRY RUN] plano: {len(series_plan)} series novas; "
              f"cleanup apagaria qualquer PCE:alt_% fora de {len(keep_codes)} codes.")
        return

    if not args.no_confirm:
        resp = input(
            f"\nConfirma: (a) cleanup das PCE:alt_% legadas + "
            f"(b) carga de {len(series_plan)} series (Index SA) no SQL corp? [s/N] "
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

    # (a) cleanup antes do upsert — evita colisao de series_name se houver.
    _cleanup_legacy_alt(session, keep_codes)

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
            "description": f"PCE alt measure {sp['measure']} (Index, SA, rebase Jan/2000=100) — Fed oficial",
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
        # Pattern load_cpius_to_sql.py: DELETE WHERE series_id = ? (sem bind
        # de data — driver corp Microsoft ODBC cospe HYC00 em `date>=? AND
        # date<=?` com datetime.date). Como default e --full, re-escreve tudo.
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
