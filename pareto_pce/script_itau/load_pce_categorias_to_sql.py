#!/usr/bin/env python
# load_pce_categorias_to_sql.py
#
# Carrega as 33 categorias "chefe" do pareto_pce no SQL corp Itau. Analogo ao
# load_cpius_to_sql.py (sync 2026-07-20): cada categoria vira ATE 2 series:
#   - Index (SA, data_type='SA'): value_index Jan/2000=100
#   - Weight (data_type='Weight'): share nominal do mes vs headline (%)
#
# Pre-requisito: scripts/build_pce_categorias.py rodou e gerou:
#   data/pce_categorias_indice.csv
#   data/pce_categorias_pesos.csv
#
# Convenções (alinhadas com CPI-US):
#   country='US', subject='Prices', indicator='PCE', frequency='M'
#   bls_code = 'PCE:{slug}' (ex: PCE:all_items, PCE:core_goods, ...)
#   series_name = '{label} (Index)' pro idx, '{label} (Weight)' pro peso
#   haver_code = NULL (bls_code e a chave de proveniencia)
#
# Headline (`all_items`) tem Weight sintetico 100.0 fixo (nao vem do CSV).
#
# Pattern HYC00-safe: DELETE WHERE series_id = ? so, re-escreve full.
#
# Uso:
#   cd pareto_pce
#   python script_itau/load_pce_categorias_to_sql.py --dry-run
#   python script_itau/load_pce_categorias_to_sql.py --no-confirm
#   python script_itau/load_pce_categorias_to_sql.py --only all_items,core

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:
    from opt_utils.database import SQLConnector

ROOT     = Path(__file__).resolve().parent.parent
IDX_CSV  = ROOT / "data" / "pce_categorias_indice.csv"
PESO_CSV = ROOT / "data" / "pce_categorias_pesos.csv"
MAP_CSV  = ROOT / "scripts" / "bea_maps" / "pce_categorias.csv"

CODE_FMT = "PCE:{slug}"


def _load_labels() -> dict[str, str]:
    """Mapa slug -> label legivel (vem do mapping CSV usado no build)."""
    mp = pd.read_csv(MAP_CSV)
    return dict(zip(mp["slug"], mp["label"]))


def _collect_series_plan(args, labels: dict[str, str]) -> list[dict]:
    """Monta plano: lista de dicts com (slug, series_name, bls_code, data_type, data).
    data e DataFrame com cols [date, value]."""
    idx = pd.read_csv(IDX_CSV, parse_dates=["date"])
    peso = pd.read_csv(PESO_CSV, parse_dates=["date"])

    only = set(args.only.split(",")) if args.only else None
    plan = []
    for slug in idx["cat"].drop_duplicates().tolist():
        if only and slug not in only:
            continue
        if slug not in labels:
            print(f"  [WARN] slug={slug}: sem label em MAP_CSV, pulando")
            continue
        label = labels[slug]

        # Index SA
        s = (idx[idx["cat"] == slug][["date", "value_index"]]
             .rename(columns={"value_index": "value"}).dropna(subset=["value"]))
        if not s.empty:
            plan.append({
                "slug": slug,
                "series_name": f"PCE: {label} (Index)",
                "bls_code": CODE_FMT.format(slug=slug),
                "data_type": "SA",
                "data": s,
            })

        # Weight — pra headline sobrescreve com 100.0 fixo
        w = peso[peso["cat"] == slug][["date", "weight"]].rename(columns={"weight": "value"})
        if slug == "all_items":
            w = w.copy()
            w["value"] = 100.0
        w = w.dropna(subset=["value"])
        if not w.empty:
            plan.append({
                "slug": slug,
                "series_name": f"PCE: {label} (Weight)",
                "bls_code": CODE_FMT.format(slug=slug),
                "data_type": "Weight",
                "data": w,
            })
    return plan


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="So lista o que faria.")
    ap.add_argument("--no-confirm", action="store_true", help="Pula prompt.")
    ap.add_argument("--only", type=str, default=None,
                    help="Lista CSV de slugs (ex: 'all_items,core,goods').")
    args = ap.parse_args()

    for p in (IDX_CSV, PESO_CSV, MAP_CSV):
        if not p.exists():
            sys.exit(f"[FAIL] {p} nao existe. Rode scripts/build_pce_categorias.py primeiro.")

    labels = _load_labels()
    plan = _collect_series_plan(args, labels)

    print(f"\n[1] Plano: {len(plan)} series "
          f"({sum(1 for sp in plan if sp['data_type']=='SA')} Index + "
          f"{sum(1 for sp in plan if sp['data_type']=='Weight')} Weight):")
    for sp in plan:
        d = sp["data"]
        print(f"  {sp['bls_code']:40s} {sp['data_type']:6s}  n={len(d):4d}  "
              f"{d.date.min().date()} -> {d.date.max().date()}")

    if args.dry_run:
        print(f"\n[DRY RUN] {len(plan)} series listadas, nada escrito.")
        return

    if not args.no_confirm:
        resp = input(f"\nConfirma carga de {len(plan)} series no SQL corp? [s/N] ")
        if resp.strip().lower() not in ("s", "sim", "y", "yes"):
            print("Abortado.")
            return

    try:
        from opt_utils.database import SQLConnector
    except ImportError:
        sys.exit("[FAIL] opt_utils nao disponivel. Esse load so roda no corp Itau.")

    session = SQLConnector(connector="pyodbc")
    today = date.today()

    def _ensure(sp: dict) -> int:
        q = pd.read_sql(
            """SELECT series_id FROM OPT_Macro_Series_2
               WHERE country='US' AND subject='Prices' AND indicator='PCE'
                 AND series_name=? AND data_type=?""",
            session.conn,
            params=[sp["series_name"], sp["data_type"]],
        )
        if len(q) > 0:
            return int(q["series_id"].iloc[0])
        # Description curta pra evitar o bug NVARCHAR 600 bytes (= 300 chars)
        if sp["data_type"] == "SA":
            desc = (f"PCE {sp['slug']} (Index SA, Jan/2000=100). BEA U20404 "
                    f"direct ou algebra Laspeyres (ver bea_maps/pce_categorias.csv).")
        else:
            desc = (f"PCE {sp['slug']} (Weight %). Share do nominal mensal "
                    f"BEA U20405 vs headline PCE.")
        meta = pd.DataFrame([{
            "country": "US", "subject": "Prices", "indicator": "PCE",
            "series_name": sp["series_name"], "data_type": sp["data_type"],
            "frequency": "M", "description": desc, "bls_code": sp["bls_code"],
        }])
        session.write_sql_table_from_dataframe("OPT_Macro_Series_2", meta, chunk_size=50)
        q = pd.read_sql(
            """SELECT series_id FROM OPT_Macro_Series_2
               WHERE country='US' AND subject='Prices' AND indicator='PCE'
                 AND series_name=? AND data_type=?""",
            session.conn,
            params=[sp["series_name"], sp["data_type"]],
        )
        return int(q["series_id"].iloc[0])

    n_series = 0; n_rows = 0
    for sp in plan:
        sid = _ensure(sp)
        # Pattern HYC00-safe: DELETE WHERE series_id = ? so.
        session.execute(
            "DELETE FROM OPT_Macro_Series_Data_2 WHERE series_id = ?",
            params=[sid],
        )
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
        print(f"  [{n_series}/{len(plan)}] {sp['bls_code']} ({sp['data_type']}): "
              f"{len(df_data)} rows")

    session.close()
    print(f"\n[OK] {n_series} series x {n_rows} rows gravados.")


if __name__ == "__main__":
    main()
