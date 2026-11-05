#!/usr/bin/env python3
# load_alt_bottomup_cpi_to_sql.py
#
# Carga das medidas alternativas BOTTOM-UP (construcao propria Itau) do CPI-U
# no SQL corp. Fonte: data/cpi_cpius_alt_bottomup.csv
# (gerado por scripts/build_alt_bottomup_cpi.py).
#
# Separado de load_alt_measures_cpi_to_sql.py em 2026-11-05: as series
# oficiais Fed e as bottom-up sobem em cargas independentes, mas usam o
# MESMO padrao de codigo/nome no SQL (nada muda pro dashboard):
#
#   bls_code    = "CPIUS:alt_{measure_slug}"   (sufixo _custom = bottom-up)
#   series_name = "CPI-U: {label} (Index)"
#   data_type = "SA", indicator = "CPI", country = "US", subject = "Prices"
#
# Este loader so mexe nas series CPIUS:alt_%_custom. O cleanup do loader das
# oficiais ignora o sufixo _custom, entao um nao apaga o que o outro gravou.
#
# Uso:
#   cd pareto_cpius
#   python script_itau/load_alt_bottomup_cpi_to_sql.py --dry-run
#   python script_itau/load_alt_bottomup_cpi_to_sql.py                # pede confirmacao
#   python script_itau/load_alt_bottomup_cpi_to_sql.py --no-confirm   # sem prompt

import argparse
import sys
from datetime import date
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
IN_CSV = ROOT / "data" / "cpi_cpius_alt_bottomup.csv"

# Mapa measure -> (label legivel, slug no bls_code). Chave bate com measure no CSV.
# Todo slug termina em _custom: e isso que separa bottom-up de Fed oficial no SQL.
MEASURE_LABELS = {
    "trimmed_sym_25_cpi_custom": ("Trimmed Sym 25% (custom)", "alt_trimmed_sym_25_cpi_custom"),
}

CODE_FMT = "CPIUS:{code_slug}"


def _load_df() -> pd.DataFrame:
    if not IN_CSV.exists():
        sys.exit(f"[FAIL] {IN_CSV} nao existe. Rode scripts/build_alt_bottomup_cpi.py primeiro.")
    df = pd.read_csv(IN_CSV, parse_dates=["date"])
    if "value_index" not in df.columns:
        sys.exit(f"[FAIL] {IN_CSV.name} sem coluna 'value_index'. Re-rode scripts/build_alt_bottomup_cpi.py.")
    missing = set(df["measure"].unique()) - set(MEASURE_LABELS)
    if missing:
        print(f"[WARN] measures no CSV sem label em MEASURE_LABELS: {missing}")
    return df


def _cleanup_stale_custom(session, keep_codes: set[str]) -> int:
    """Deleta series CPIUS:alt_%_custom que NAO estao no plano atual (medida
    bottom-up descontinuada). Nao toca nas series Fed oficiais."""
    print("\n[cleanup] procurando series CPIUS:alt_%_custom fora do plano...")
    df = pd.read_sql(
        "SELECT series_id, series_name, data_type, bls_code "
        "FROM OPT_Macro_Series_2 WHERE bls_code LIKE 'CPIUS:alt_%_custom'",
        session.conn,
    )
    to_drop = df[~df["bls_code"].isin(keep_codes)] if not df.empty else df
    if to_drop.empty:
        print("  nada a limpar.")
        return 0
    print(f"  {len(to_drop)} series a apagar:")
    with pd.option_context("display.max_colwidth", 60, "display.width", 200):
        print(to_drop.to_string(index=False))
    n = 0
    for sid in to_drop["series_id"].astype(int):
        session.execute("DELETE FROM OPT_Macro_Series_Data_2 WHERE series_id = ?", params=[int(sid)])
        session.execute("DELETE FROM OPT_Macro_Series_2 WHERE series_id = ?", params=[int(sid)])
        n += 1
    print(f"  [OK] {n} series deletadas (data + metadata).")
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="So lista o que faria.")
    ap.add_argument("--no-confirm", action="store_true", help="Pula prompt.")
    ap.add_argument("--incremental", action="store_true",
                    help="Carga incremental (ultimos 24m). Default: full history.")
    ap.add_argument("--only", type=str, default=None,
                    help="Lista CSV de measures pra carregar.")
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
        print("[info] carga full history (default). Use --incremental pra ultimos 24m.")

    print("\n[1] Series a carregar (1 por measure, so Index SA):")
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
            "series_name": f"CPI-U: {label} (Index)",
            "bls_code": CODE_FMT.format(code_slug=code_slug),
            "data": s,
        })
        print(f"  {series_plan[-1]['bls_code']:50s}  n={len(s):4d}  "
              f"{s.date.min().date()} -> {s.date.max().date()}")

    if not series_plan:
        sys.exit("[FAIL] nenhuma serie com dados no CSV — nada a carregar.")

    keep_codes = {sp["bls_code"] for sp in series_plan}

    if args.dry_run:
        print(f"\n[DRY RUN] plano: {len(series_plan)} series; "
              f"cleanup apagaria qualquer CPIUS:alt_%_custom fora de {sorted(keep_codes)}.")
        return

    if not args.no_confirm:
        resp = input(f"\nConfirma carga de {len(series_plan)} series bottom-up (Index SA) no SQL corp? [s/N] ")
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

    _cleanup_stale_custom(session, keep_codes)

    def _ensure_series(sp: dict) -> int:
        """Lookup ou INSERT em OPT_Macro_Series_2. Retorna series_id."""
        lookup = """SELECT series_id FROM OPT_Macro_Series_2
                    WHERE country='US' AND subject='Prices' AND indicator='CPI'
                      AND series_name=? AND data_type='SA'"""
        q = pd.read_sql(lookup, session.conn, params=[sp["series_name"]])
        if len(q) > 0:
            return int(q["series_id"].iloc[0])
        meta = pd.DataFrame([{
            "country": "US", "subject": "Prices", "indicator": "CPI",
            "series_name": sp["series_name"], "data_type": "SA",
            "frequency": "M",
            "description": (f"CPI-U alt measure {sp['measure']} (Index, SA, rebase Jan/2000=100) "
                            f"— custom bottom-up Itau (nao e fonte oficial Fed)"),
            "bls_code": sp["bls_code"],
        }])
        session.write_sql_table_from_dataframe("OPT_Macro_Series_2", meta, chunk_size=50)
        q = pd.read_sql(lookup, session.conn, params=[sp["series_name"]])
        return int(q["series_id"].iloc[0])

    n_series = 0
    n_rows = 0
    for sp in series_plan:
        series_id = _ensure_series(sp)
        # Deleta tudo da serie e re-escreve full (mesmo padrao dos outros loaders;
        # o driver ODBC corp nao binda datetime.date em BETWEEN).
        session.execute("DELETE FROM OPT_Macro_Series_Data_2 WHERE series_id = ?", params=[series_id])
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
