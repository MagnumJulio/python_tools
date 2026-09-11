#!/usr/bin/env python
# load_pce_to_sql.py (pareto_pce)
# Carrega as 5 series de difusao PCE em OPT_Macro_Series_2 /
# OPT_Macro_Series_Data_2. Fonte: data/pce_diffusion.csv gerado por
# scripts/build_diffusion.py (que le U20404 do BEA).
#
# Namespace PCE eh estritamente disjunto de IPCA, IPCA-15 e CPI-US:
#   - country   = 'US'
#   - subject   = 'Prices'
#   - indicator = 'PCE'
#   - bls_code  = 'PCE:diffusion_{aggregate}_{metric}'
# Todas as 5 series usam data_type='NSA' (o BEA U20404 nao publica versao
# dessazonalizada separada; a metrica de difusao YoY nao carrega
# sazonalidade relevante pra desagregar).
#
# Uso (na maquina corp, com opt_utils disponivel):
#   cd pareto_pce
#   python script_itau/load_pce_to_sql.py             # grava tudo
#   python script_itau/load_pce_to_sql.py --dry-run   # so lista o que faria
#   python script_itau/load_pce_to_sql.py --check     # preflight read-only

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:
    from opt_utils.database import SQLConnector  # corp-only

ROOT = Path(__file__).resolve().parent.parent
DIFF_CSV = ROOT / "data" / "pce_diffusion.csv"

# 5 series. Chave = (aggregate, metric) — bate exato com o CSV.
# Cada tupla: (bls_code, series_name, description).
SERIES_MAP: dict[tuple[str, str], tuple[str, str, str]] = {
    ("Headline", "diffusion_yoy_3pct"): (
        "PCE:diffusion_headline_yoy",
        "PCE: Diffusion Headline (YoY > 3%)",
        "Share of PCE items (BEA U20404) with YoY price increase > 3%. "
        "Metodologia: contagem simples de leaves; count-based, nao ponderado.",
    ),
    ("Headline", "diffusion_6ma_ann_3pct"): (
        "PCE:diffusion_headline_6ma_ann",
        "PCE: Diffusion Headline (6m annualized > 3%)",
        "Share of PCE items com variacao 6m anualizada > 3%. "
        "Formula: ((idx[t]/idx[t-6])^2 - 1)*100 > 3.",
    ),
    ("Goods", "diffusion_yoy_3pct"): (
        "PCE:diffusion_goods_yoy",
        "PCE: Diffusion Goods (YoY > 3%)",
        "Share of PCE Goods items com YoY > 3% (subset Goods de U20404).",
    ),
    ("Services", "diffusion_yoy_3pct"): (
        "PCE:diffusion_services_yoy",
        "PCE: Diffusion Services (YoY > 3%)",
        "Share of PCE Services items com YoY > 3% (subset Services de U20404, "
        "excluindo imputed financial services e items volateis).",
    ),
    ("Goods_ex_cars", "diffusion_yoy_3pct"): (
        "PCE:diffusion_goods_ex_cars_yoy",
        "PCE: Diffusion Goods ex Cars (YoY > 3%)",
        "Share of PCE Goods (excluindo motor vehicles: New autos, New light "
        "trucks, Used autos, Used light trucks, Tires, Accessories) com YoY > 3%.",
    ),
}


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
    """Espelho do padrao dos outros loaders (IPCA/CPI-US). Novos INSERTs nao
    tocam em haver_code (fica NULL por default)."""
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


def _load_diffusion() -> dict[tuple[str, str], pd.Series]:
    if not DIFF_CSV.exists():
        sys.exit(f"[FAIL] {DIFF_CSV} nao existe. Rode scripts/build_diffusion.py primeiro.")
    df = pd.read_csv(DIFF_CSV, parse_dates=["date"])
    out: dict[tuple[str, str], pd.Series] = {}
    for (agg, metric), g in df.groupby(["aggregate", "metric"]):
        s = g.set_index("date")["value"].sort_index().astype(float)
        s.name = f"{agg}:{metric}"
        out[(agg, metric)] = s
    return out


def _preflight(session, max_desc_len: int) -> bool:
    """Checagens read-only antes de escrever."""
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
        if not col.empty:
            n = int(col.iloc[0]["n"]) if col.iloc[0]["n"] is not None else -1
            if n == -1:
                print(f"  [OK] description = VARCHAR(MAX) — suporta {max_desc_len} chars")
            elif n >= max_desc_len:
                print(f"  [OK] description = VARCHAR({n}) — suporta {max_desc_len} chars")
            else:
                print(f"  [FAIL] description = VARCHAR({n}), precisa {max_desc_len}"); ok = False
    except Exception as e:
        print(f"  [WARN] nao foi possivel checar tamanho de description: {e}")

    try:
        df_all = pd.read_sql(
            """SELECT series_id, series_name, data_type, haver_code, bls_code
               FROM OPT_Macro_Series_2
               WHERE bls_code LIKE 'PCE:%' OR haver_code LIKE 'PARETO_PCE:%'
               ORDER BY series_id""",
            session.conn,
        )
        print(f"\n  Series PCE existentes: {len(df_all)}")
        if not df_all.empty:
            with pd.option_context("display.max_colwidth", 60, "display.width", 200):
                print(df_all.to_string(index=False))
    except Exception as e:
        print(f"  [WARN] nao foi possivel listar series PCE: {e}")

    return ok


def _migrate_pce_to_current(session) -> int:
    """Defensivo. PCE eh fork novo, nao ha historia pre-existente — mas se
    algum dia rows antigas aparecerem (recarga manual, formato divergente),
    normaliza pro atual. Namespace PCE eh disjunto — filtra estritamente
    'PCE:%' ou 'PARETO_PCE:%'."""
    print("\n[migracao] Normalizando series PCE pareto pro formato atual...")
    df = pd.read_sql(
        """SELECT series_id, series_name, data_type, haver_code, bls_code
           FROM OPT_Macro_Series_2
           WHERE haver_code LIKE 'PARETO_PCE:%' OR bls_code LIKE 'PCE:%'
           ORDER BY series_id""",
        session.conn,
    )
    if df.empty:
        print("  nenhuma serie PCE encontrada — nada a migrar.")
        return 0

    n_updated = 0
    for _, row in df.iterrows():
        already_ok = row["haver_code"] is None
        if already_ok:
            continue
        session.execute(
            "UPDATE OPT_Macro_Series_2 SET haver_code = NULL WHERE series_id = ?",
            params=[int(row["series_id"])],
        )
        n_updated += 1
        print(f"  [UPDATE] id={row['series_id']:5d} haver_code -> NULL "
              f"({row['series_name']})")
    print(f"  {n_updated} series migradas ({len(df) - n_updated} ja no formato final).")
    return n_updated


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="So lista o que seria feito, sem abrir conexao SQL.")
    parser.add_argument("--check", action="store_true",
                        help="Conecta no SQL e roda preflight read-only (sem escrever).")
    parser.add_argument("--no-confirm", action="store_true",
                        help="Pula confirmacao interativa antes de escrever no SQL.")
    args = parser.parse_args()

    print(f"[1] Lendo {DIFF_CSV.relative_to(ROOT)}...")
    diff = _load_diffusion()
    print(f"    {len(diff)} series encontradas no CSV")

    # Ordena pela chave do SERIES_MAP pra ter output previsivel.
    keys = [k for k in SERIES_MAP if k in diff]
    missing = [k for k in SERIES_MAP if k not in diff]
    if missing:
        sys.exit(f"[FAIL] series faltando no CSV: {missing}")

    if args.dry_run:
        print("\n[dry-run] Series que serao gravadas:")
        for k in keys:
            bls, name, desc = SERIES_MAP[k]
            s = diff[k]
            print(f"  - {name:55s}")
            print(f"    bls_code={bls}, {len(s.dropna())} obs, "
                  f"{s.dropna().index.min().date()} → {s.dropna().index.max().date()}")
        return

    from opt_utils.database import SQLConnector  # corp-only
    session = SQLConnector(connector="pyodbc")
    try:
        max_desc = max(len(SERIES_MAP[k][2]) for k in keys)
        ok = _preflight(session, max_desc)
        if not ok:
            sys.exit("[FAIL] preflight falhou. Corrija antes de rodar sem --check.")

        if args.check:
            print("\n[check] modo read-only concluido — nada gravado.")
            return

        _migrate_pce_to_current(session)

        if not args.no_confirm:
            resp = input(f"\nConfirma gravacao de {len(keys)} series no SQL? [s/N] ").strip().lower()
            if resp != "s":
                sys.exit("[ABORT] confirmacao negada.")

        for k in keys:
            bls, name, desc = SERIES_MAP[k]
            s = diff[k]
            print(f"\n--- {name} ---")
            print(f"    {len(s.dropna())} obs "
                  f"{s.dropna().index.min().date()} -> {s.dropna().index.max().date()}")
            sidra_to_sql(
                series=s, country="US", subject="Prices", indicator="PCE",
                series_name=name, data_type="NSA", frequency="M",
                description=desc, bls_code=bls,
                session=session, replace=True,
            )
    finally:
        session.close()

    print(f"\n[OK] {len(keys)} series PCE difusao carregadas em "
          f"OPT_Macro_Series_2 / OPT_Macro_Series_Data_2.")


if __name__ == "__main__":
    main()
