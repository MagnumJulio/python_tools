#!/usr/bin/env python
# simulate_oer_regional_to_sql.py
# Simulacao do load_oer_regional_to_sql.py SEM tocar em SQL/opt_utils. Mesmo
# MockSQLConnector do simulate_cpius_to_sql.py — grava OPT_Macro_Series_2 e
# OPT_Macro_Series_Data_2 em DataFrames em memoria. Util pra testar
# mapping/labels em casa antes de ir pro corp.
#
# Pre-requisito: pipeline R ja rodou:
#   cd pareto_cpius
#   Rscript scripts/fetch_bls_oer_regional.R
#
# Uso:
#   cd pareto_cpius
#   python script_itau/simulate_oer_regional_to_sql.py             # 4 regions (sem US)
#   python script_itau/simulate_oer_regional_to_sql.py --include-us # 5 series (com US)
#   python script_itau/simulate_oer_regional_to_sql.py --save       # grava CSVs

import argparse
import sys
from datetime import date
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
IDX_CSV = ROOT / "data" / "cpi_cpius_oer_regional_indice.csv"
MAP_CSV = ROOT / "scripts" / "bls_maps" / "cpiu_oer_regional.csv"
OUT_DIR = Path(__file__).resolve().parent / "sim_output"

# Namespace dedicado pra OER regional. Nao reusa CPIUS:{cat} do loader
# principal pra: (a) evitar colisao com CPIUS:oer (US headline ja no SQL),
# (b) desacoplar migration idempotente de cada loader. LIKE 'CPIUS:%' nao
# casa com 'CPIUS_OER:%' pq ':' != '_'.
CODE = "CPIUS_OER:{area}"

SERIES_COLS = ["series_id", "country", "subject", "indicator", "series_name",
               "data_type", "frequency", "description", "haver_code", "bls_code"]
DATA_COLS = ["date", "series_id", "value", "release_date", "vintage_date"]


class MockSQLConnector:
    """Imita contrato do opt_utils.SQLConnector; auto-incrementa series_id."""

    def __init__(self):
        self.tables = {
            "OPT_Macro_Series_2":      pd.DataFrame(columns=SERIES_COLS),
            "OPT_Macro_Series_Data_2": pd.DataFrame(columns=DATA_COLS),
        }
        self._next_id = 1
        self.conn = self

    def _find_series_id(self, country, subject, indicator, series_name, data_type):
        t = self.tables["OPT_Macro_Series_2"]
        m = (t.country == country) & (t.subject == subject) & (t.indicator == indicator) \
            & (t.series_name == series_name) & (t.data_type == data_type)
        return int(t.loc[m, "series_id"].iloc[0]) if m.any() else None

    @staticmethod
    def _append(base: pd.DataFrame, new: pd.DataFrame) -> pd.DataFrame:
        return new.copy() if base.empty else pd.concat([base, new], ignore_index=True)

    def insert_meta(self, row: dict) -> int:
        row = {**row, "series_id": self._next_id}
        self._next_id += 1
        df_new = pd.DataFrame([row]).reindex(columns=SERIES_COLS)
        self.tables["OPT_Macro_Series_2"] = self._append(
            self.tables["OPT_Macro_Series_2"], df_new
        )
        return row["series_id"]

    def delete_data(self, series_id: int):
        t = self.tables["OPT_Macro_Series_Data_2"]
        self.tables["OPT_Macro_Series_Data_2"] = t[t.series_id != series_id].reset_index(drop=True)

    def insert_data(self, df: pd.DataFrame):
        self.tables["OPT_Macro_Series_Data_2"] = self._append(
            self.tables["OPT_Macro_Series_Data_2"], df[DATA_COLS]
        )

    def close(self):
        pass


def sim_sidra_to_sql(
    series: pd.Series,
    country: str, subject: str, indicator: str,
    series_name: str, data_type: str, frequency: str,
    description: str, bls_code: str,
    session: MockSQLConnector, replace: bool = True,
) -> int:
    series_id = session._find_series_id(country, subject, indicator, series_name, data_type)
    if series_id is None:
        series_id = session.insert_meta({
            "country": country, "subject": subject, "indicator": indicator,
            "series_name": series_name, "data_type": data_type,
            "frequency": frequency, "description": description, "bls_code": bls_code,
        })

    if replace:
        session.delete_data(series_id)

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
    session.insert_data(df_data)
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
    """Convencao: 'CPI-U: OER - <area_label> (Index)'. Sufixo '(Index)' mantem
    o padrao visual do loader principal (que usa pra parear idx vs Weight)."""
    return f"CPI-U: OER - {area_label} (Index)"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", type=str, default=None,
                        help="Lista CSV de area_code (ex: 'northeast,south').")
    parser.add_argument("--include-us", action="store_true",
                        help="Inclui US (area_code=us) na simulacao. Default: skipa "
                             "pq ja existe no SQL via CPIUS:oer do loader principal.")
    parser.add_argument("--preview", type=int, default=10,
                        help="Linhas a imprimir de cada tabela (default 10).")
    parser.add_argument("--save", action="store_true",
                        help="Salva as 2 tabelas em script_itau/sim_output/*.csv.")
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

    session = MockSQLConnector()

    for area in areas:
        meta = amap[area]
        series_name = _series_name(meta["area_label"])
        bls_code = CODE.format(area=area)
        si = series_by_area[area]
        desc = (
            f"CPI-U OER (Owners' Equivalent Rent of Residences) - {meta['area_label']} "
            f"- Indice NSA (base nativa DEZ 1982=100, rebased jan/2000=100 pra "
            f"comparabilidade) - BLS API v2 ({meta['series_id']})"
        )
        print(f"  - {series_name:60s} obs={len(si):4d} ({si.index.min().date()} -> {si.index.max().date()})  bls_code={bls_code}")
        sim_sidra_to_sql(
            series=si, country="US", subject="Prices", indicator="CPI",
            series_name=series_name, data_type="NSA", frequency="M",
            description=desc, bls_code=bls_code,
            session=session,
        )

    meta_df = session.tables["OPT_Macro_Series_2"]
    data_df = session.tables["OPT_Macro_Series_Data_2"]

    print("\n" + "=" * 70)
    print(f"OPT_Macro_Series_2 - {len(meta_df)} series cadastradas")
    print("=" * 70)
    with pd.option_context("display.max_columns", None, "display.width", 220):
        print(meta_df.head(args.preview).to_string(index=False))

    print("\n" + "=" * 70)
    print(f"OPT_Macro_Series_Data_2 - {len(data_df)} linhas (long EAV)")
    print("=" * 70)
    with pd.option_context("display.max_columns", None, "display.width", 220):
        print(data_df.head(args.preview).to_string(index=False))

    print("\nContagem por series_id:")
    cnt = data_df.groupby("series_id").size().rename("n_obs")
    chk = meta_df.set_index("series_id")[["series_name", "data_type"]].join(cnt)
    print(chk.to_string())

    if args.save:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        meta_df.to_csv(OUT_DIR / "OPT_Macro_Series_2_oer_regional.csv", index=False)
        data_df.to_csv(OUT_DIR / "OPT_Macro_Series_Data_2_oer_regional.csv", index=False)
        print(f"\n[OK] Salvo em {OUT_DIR.relative_to(ROOT)}/")


if __name__ == "__main__":
    main()
