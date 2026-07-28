#!/usr/bin/env python
# simulate_pareto_to_sql.py
# Simulacao do load_pareto_to_sql.py SEM tocar em SQL/opt_utils. Usa um
# MockSQLConnector que guarda OPT_Macro_Series_2 e OPT_Macro_Series_Data_2 em
# pandas DataFrames em memoria, imitando exatamente o schema/contrato do
# loader corp. Util pra testar mapping/labels/proveniencia em casa.
#
# Saidas em pareto_ipca/script_itau/sim_output/:
#   OPT_Macro_Series_2.csv  - metadados (1 linha por serie cadastrada)
#   OPT_Macro_Series_Data_2.csv    - long EAV (1 linha por (serie, mes))
#
# Uso:
#   cd pareto_ipca
#   python script_itau/simulate_pareto_to_sql.py             # NSA so
#   python script_itau/simulate_pareto_to_sql.py --only livres,nucleo_ex0
#   python script_itau/simulate_pareto_to_sql.py --preview 20  # imprime primeiras N linhas

import argparse
import sys
from datetime import date
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
VAR_CSV  = ROOT / "data" / "ipca15_pareto_recon.csv"
IDX_CSV  = ROOT / "data" / "ipca15_pareto_indice.csv"
PESO_CSV = ROOT / "data" / "ipca15_pareto_pesos.csv"
OUT_DIR  = Path(__file__).resolve().parent / "sim_output"

CATEGORY_LABELS = {
    "total":           "IPCA-15: Total",
    "administrados":   "IPCA-15: Monitorados",
    "livres":          "IPCA-15: Livres",
    "industriais":     "IPCA-15: Industriais",
    "servicos":        "IPCA-15: Servicos",
    "alim_domicilio":  "IPCA-15: Alimentacao no Domicilio",
    "nucleo_ex0":      "IPCA-15: Nucleo EX0",
    "nucleo_ex3":      "IPCA-15: Nucleo EX3",
    "duraveis":        "IPCA-15: Bens Duraveis",
    "semiduraveis":    "IPCA-15: Bens Semiduraveis",
    "ndur_industr":    "IPCA-15: Bens Nao-Duraveis Industriais",
    "servicos_subj":   "IPCA-15: Servicos Subjacentes (tradicional, c/ alim fora)",
    "servicos_exsubj": "IPCA-15: Servicos Ex-Subjacentes",
    "alim_in_natura":  "IPCA-15: Alimentos In Natura",
    "alim_semi_elab":  "IPCA-15: Alimentos Semi-Elaborados",
    "alim_industr":    "IPCA-15: Alimentos Industrializados",
    "comerc":          "IPCA-15: Comercializaveis",
    "ncomerc":         "IPCA-15: Nao-Comercializaveis",
    "nucleo_ma":       "IPCA-15: Nucleo MA",
    "nucleo_ms":       "IPCA-15: Nucleo MS",
    "nucleo_dp":       "IPCA-15: Nucleo DP",
    # NT_57/Dez-2025
    "nucleo_exfe":     "IPCA-15: Nucleo EX-FE",
    "nucleo_ex1":      "IPCA-15: Nucleo EX1",
    "ex3_serv":        "IPCA-15: Nucleo EX3 Servicos (estrito, ex alim fora)",
    "ex3_ind":         "IPCA-15: Nucleo EX3 Industriais",
    "difusao":         "IPCA-15: Indice de Difusao",
    "nucleo_p55":      "IPCA-15: Nucleo P55 (Percentil 55)",
    "nucleo_medio":    "IPCA-15: Nucleo Medio (media dos 5)",
}

# Namespace IPCA15 estritamente disjunto do IPCA cheio (bls_code, indicator,
# series_name). Mesmo padrao do pareto_ipca — bls_code unico por cat, sem
# sufixo /Index. haver_code fica NULL nos INSERTs novos.
CODE = "IPCA15:{cat}"

SERIES_COLS = ["series_id", "country", "subject", "indicator", "series_name",
               "data_type", "frequency", "description", "haver_code", "bls_code"]
DATA_COLS = ["date", "series_id", "value", "release_date", "vintage_date"]


class MockSQLConnector:
    """Imita o contrato do opt_utils.SQLConnector usado pelo sidra_to_sql:
       - .conn               (passa-se pra pd.read_sql; aqui ignoramos)
       - read_sql / execute_sql / write_sql_table_from_dataframe / close()
       Auto-incrementa series_id como SQL Server faria com IDENTITY."""

    def __init__(self):
        self.tables = {
            "OPT_Macro_Series_2": pd.DataFrame(columns=SERIES_COLS),
            "OPT_Macro_Series_Data_2":   pd.DataFrame(columns=DATA_COLS),
        }
        self._next_id = 1
        self.conn = self  # placeholder pra pd.read_sql(..., self.conn) fora; nao usado

    def _find_series_id(self, country, subject, indicator, series_name, data_type):
        t = self.tables["OPT_Macro_Series_2"]
        m = (t.country == country) & (t.subject == subject) & (t.indicator == indicator) \
            & (t.series_name == series_name) & (t.data_type == data_type)
        return int(t.loc[m, "series_id"].iloc[0]) if m.any() else None

    @staticmethod
    def _append(base: pd.DataFrame, new: pd.DataFrame) -> pd.DataFrame:
        # Evita FutureWarning do pandas em concat com DataFrame totalmente vazio.
        return new.copy() if base.empty else pd.concat([base, new], ignore_index=True)

    def insert_meta(self, row: dict) -> int:
        row = {**row, "series_id": self._next_id}
        self._next_id += 1
        # Reindexa pra SERIES_COLS: colunas ausentes do dict (ex: haver_code)
        # entram como NaN, replicando o comportamento do SQL Server que grava
        # NULL nas colunas nao referenciadas pelo INSERT.
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
        # haver_code fica None (SQL NULL) — nao passamos o campo no dict pra
        # replicar exatamente o INSERT do loader corp. O DataFrame preenche com
        # NaN, equivalente a NULL na tabela real.
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
    df_data = pd.DataFrame({
        "date": s.index.date,
        "series_id": series_id,
        "value": s.values,
        "release_date": today,
        "vintage_date": today,
    })
    session.insert_data(df_data)
    return series_id


def _load_csv_long(path: Path, value_col: str) -> dict[str, pd.Series]:
    if not path.exists():
        sys.exit(f"CSV nao encontrado: {path}. Rode o pipeline R primeiro.")
    df = pd.read_csv(path)
    df["date"] = pd.to_datetime(df["date"])
    out: dict[str, pd.Series] = {}
    for cat, g in df.groupby("category_code"):
        s = g.set_index("date")[value_col].sort_index().astype(float)
        s.name = cat
        out[cat] = s
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", type=str, default=None,
                        help="Lista CSV de category_code (ex: 'livres,nucleo_ex0').")
    parser.add_argument("--preview", type=int, default=10,
                        help="Linhas a imprimir de cada tabela ao fim (default 10).")
    parser.add_argument("--save", action="store_true",
                        help="Salva as 2 tabelas em script_itau/sim_output/*.csv.")
    args = parser.parse_args()

    only = set(args.only.split(",")) if args.only else None

    print(f"[1] Lendo {VAR_CSV.relative_to(ROOT)}...")
    var_series = _load_csv_long(VAR_CSV, "value")
    print(f"    {len(var_series)} categorias")

    print(f"[2] Lendo {IDX_CSV.relative_to(ROOT)}...")
    idx_series = _load_csv_long(IDX_CSV, "index")
    print(f"    {len(idx_series)} categorias")

    print(f"[3] Lendo {PESO_CSV.relative_to(ROOT)} (opcional)...")
    peso_series: dict[str, pd.Series] = {}
    if PESO_CSV.exists():
        peso_series = _load_csv_long(PESO_CSV, "value")
        print(f"    {len(peso_series)} categorias com peso Laspeyres")
    else:
        print("    [WARN] nao encontrado — pesos nao serao carregados. Rode o pipeline R primeiro.")

    cats = sorted(set(var_series) & set(idx_series))
    if only:
        cats = [c for c in cats if c in only]
    missing_label = [c for c in cats if c not in CATEGORY_LABELS]
    if missing_label:
        sys.exit(f"Falta label em CATEGORY_LABELS pra: {missing_label}")

    session = MockSQLConnector()

    for c in cats:
        label = CATEGORY_LABELS[c]
        label_idx = f"{label} (Indice)"
        sv, si = var_series[c], idx_series[c]
        sp = peso_series.get(c)
        bls = CODE.format(cat=c)
        peso_info = f"Weight x2={len(sp):4d}" if sp is not None else "Weight=N/A "
        print(f"  - {label:45s}  var={len(sv):4d}   idx={len(si):4d}   {peso_info}")

        sim_sidra_to_sql(
            series=sv, country="BR", subject="Prices", indicator="IPCA-15",
            series_name=label, data_type="NSA", frequency="M",
            description=f"{label} - Variacao mensal (%) - IPCA-15 recon IBGE-only via NT_57/Dez-2025",
            bls_code=bls,
            session=session,
        )
        sim_sidra_to_sql(
            series=si, country="BR", subject="Prices", indicator="IPCA-15",
            series_name=label_idx, data_type="NSA", frequency="M",
            description=f"{label} - Indice (dez/2012=100) - IPCA-15 recon IBGE-only via NT_57/Dez-2025",
            bls_code=bls,
            session=session,
        )
        if sp is not None:
            # Weight duplicado (sync 2026-07-17): mesmo array de peso gravado
            # 2x — series_name=label (par com var) e series_name=label (Indice)
            # (par com idx). Frontend capta o Weight via casamento de
            # series_name+country+indicator, trocando so o data_type. Ambos
            # compartilham o mesmo bls_code (sync 2026-07-27: 1 code por cat).
            sim_sidra_to_sql(
                series=sp, country="BR", subject="Prices", indicator="IPCA-15",
                series_name=label, data_type="Weight", frequency="M",
                description=f"{label} - Weight mensal (V66 IBGE/SIDRA, Laspeyres) - par com var",
                bls_code=bls,
                session=session,
            )
            sim_sidra_to_sql(
                series=sp, country="BR", subject="Prices", indicator="IPCA-15",
                series_name=label_idx, data_type="Weight", frequency="M",
                description=f"{label} - Weight mensal (V66 IBGE/SIDRA, Laspeyres) - par com idx",
                bls_code=bls,
                session=session,
            )

    meta = session.tables["OPT_Macro_Series_2"]
    data = session.tables["OPT_Macro_Series_Data_2"]

    print("\n" + "=" * 70)
    print(f"OPT_Macro_Series_2 — {len(meta)} séries cadastradas")
    print("=" * 70)
    with pd.option_context("display.max_columns", None, "display.width", 200):
        print(meta.head(args.preview).to_string(index=False))

    print("\n" + "=" * 70)
    print(f"OPT_Macro_Series_Data_2 — {len(data)} linhas (long EAV)")
    print("=" * 70)
    with pd.option_context("display.max_columns", None, "display.width", 200):
        print(data.head(args.preview).to_string(index=False))

    # Sanity: contagens por série
    print("\nContagem por series_id (preview):")
    cnt = data.groupby("series_id").size().rename("n_obs")
    chk = meta.set_index("series_id")[["series_name", "data_type"]].join(cnt)
    print(chk.head(args.preview).to_string())

    if args.save:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        meta.to_csv(OUT_DIR / "OPT_Macro_Series_2.csv", index=False)
        data.to_csv(OUT_DIR / "OPT_Macro_Series_Data_2.csv", index=False)
        print(f"\n[OK] Salvo em {OUT_DIR.relative_to(ROOT)}/")


if __name__ == "__main__":
    main()
