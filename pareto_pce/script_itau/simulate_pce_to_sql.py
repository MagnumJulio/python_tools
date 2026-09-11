#!/usr/bin/env python
# simulate_pce_to_sql.py
# Simulacao do load_pce_to_sql.py SEM tocar em SQL/opt_utils. Usa um
# MockSQLConnector que guarda OPT_Macro_Series_2 e OPT_Macro_Series_Data_2 em
# pandas DataFrames em memoria, imitando exatamente o schema/contrato do
# loader corp. Util pra testar mapping em casa.
#
# Saidas em pareto_pce/script_itau/sim_output/:
#   OPT_Macro_Series_2.csv       - metadados (5 linhas)
#   OPT_Macro_Series_Data_2.csv  - long EAV
#
# Uso:
#   cd pareto_pce
#   python script_itau/simulate_pce_to_sql.py
#   python script_itau/simulate_pce_to_sql.py --save

import argparse
import sys
from datetime import date
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DIFF_CSV = ROOT / "data" / "pce_diffusion.csv"
OUT_DIR = Path(__file__).resolve().parent / "sim_output"

SERIES_MAP: dict[tuple[str, str], tuple[str, str, str]] = {
    ("Headline", "diffusion_yoy_3pct"): (
        "PCE:diffusion_headline_yoy",
        "PCE: Diffusion Headline (YoY > 3%)",
        "Share of PCE items com YoY > 3%.",
    ),
    ("Headline", "diffusion_6ma_ann_3pct"): (
        "PCE:diffusion_headline_6ma_ann",
        "PCE: Diffusion Headline (6m annualized > 3%)",
        "Share de items com var 6m anualizada > 3%.",
    ),
    ("Goods", "diffusion_yoy_3pct"): (
        "PCE:diffusion_goods_yoy",
        "PCE: Diffusion Goods (YoY > 3%)",
        "Share of PCE Goods items com YoY > 3%.",
    ),
    ("Services", "diffusion_yoy_3pct"): (
        "PCE:diffusion_services_yoy",
        "PCE: Diffusion Services (YoY > 3%)",
        "Share of PCE Services items com YoY > 3%.",
    ),
    ("Goods_ex_cars", "diffusion_yoy_3pct"): (
        "PCE:diffusion_goods_ex_cars_yoy",
        "PCE: Diffusion Goods ex Cars (YoY > 3%)",
        "Share of PCE Goods (ex motor vehicles) com YoY > 3%.",
    ),
}

SERIES_COLS = ["series_id", "country", "subject", "indicator", "series_name",
               "data_type", "frequency", "description", "haver_code", "bls_code"]
DATA_COLS = ["date", "series_id", "value", "release_date", "vintage_date"]


class MockSQLConnector:
    def __init__(self):
        self.tables = {
            "OPT_Macro_Series_2": pd.DataFrame(columns=SERIES_COLS),
            "OPT_Macro_Series_Data_2": pd.DataFrame(columns=DATA_COLS),
        }
        self._next_id = 1
        self.conn = self

    def _find_series_id(self, country, subject, indicator, series_name, data_type):
        t = self.tables["OPT_Macro_Series_2"]
        m = ((t.country == country) & (t.subject == subject)
             & (t.indicator == indicator) & (t.series_name == series_name)
             & (t.data_type == data_type))
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
            "frequency": frequency, "description": description,
            "bls_code": bls_code,
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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--preview", type=int, default=10,
                        help="Linhas a imprimir de cada tabela ao fim (default 10).")
    parser.add_argument("--save", action="store_true",
                        help="Salva as 2 tabelas em script_itau/sim_output/*.csv.")
    args = parser.parse_args()

    print(f"[1] Lendo {DIFF_CSV.relative_to(ROOT)}...")
    diff = _load_diffusion()
    print(f"    {len(diff)} series encontradas")

    missing = [k for k in SERIES_MAP if k not in diff]
    if missing:
        sys.exit(f"[FAIL] series faltando no CSV: {missing}")

    session = MockSQLConnector()
    for k in SERIES_MAP:
        bls, name, desc = SERIES_MAP[k]
        s = diff[k]
        print(f"  - {name:55s}  n={len(s.dropna()):4d}")
        sim_sidra_to_sql(
            series=s, country="US", subject="Prices", indicator="PCE",
            series_name=name, data_type="NSA", frequency="M",
            description=desc, bls_code=bls,
            session=session,
        )

    meta = session.tables["OPT_Macro_Series_2"]
    data = session.tables["OPT_Macro_Series_Data_2"]

    print("\n" + "=" * 70)
    print(f"OPT_Macro_Series_2 — {len(meta)} series cadastradas")
    print("=" * 70)
    with pd.option_context("display.max_columns", None, "display.width", 200,
                            "display.max_colwidth", 50):
        print(meta.to_string(index=False))

    print("\n" + "=" * 70)
    print(f"OPT_Macro_Series_Data_2 — {len(data)} linhas")
    print("=" * 70)
    with pd.option_context("display.max_columns", None, "display.width", 200):
        print(data.head(args.preview).to_string(index=False))
        print("...")
        print(data.tail(args.preview).to_string(index=False))

    print("\nContagem por series_id:")
    cnt = data.groupby("series_id").size().rename("n_obs")
    chk = meta.set_index("series_id")[["series_name", "data_type"]].join(cnt)
    print(chk.to_string())

    if args.save:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        meta.to_csv(OUT_DIR / "OPT_Macro_Series_2.csv", index=False)
        data.to_csv(OUT_DIR / "OPT_Macro_Series_Data_2.csv", index=False)
        print(f"\n[OK] Salvo em {OUT_DIR.relative_to(ROOT)}/")


if __name__ == "__main__":
    main()
