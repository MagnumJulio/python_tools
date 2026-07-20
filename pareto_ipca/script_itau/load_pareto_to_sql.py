#!/usr/bin/env python
# load_pareto_to_sql.py
# Carrega as 28 categorias do pareto_ipca (variacao + indice + peso) na base SQL
# corp (OPT_Macro_Series_2 / OPT_Macro_Series_Data_2), seguindo o mesmo padrao do
# sidra_itau.ipynb. Pre-requisito: pipeline R ja rodou e gerou
# data/ipca_pareto_recon.csv e data/ipca_pareto_indice.csv.
#
# Uso (na maquina corp, com opt_utils disponivel):
#   cd pareto_ipca
#   python script_itau/load_pareto_to_sql.py            # NSA so
#   python script_itau/load_pareto_to_sql.py --sa       # NSA + SA (X-13)
#   python script_itau/load_pareto_to_sql.py --dry-run  # so lista o que faria

from __future__ import annotations

import argparse
import re
import sys
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:
    from opt_utils.database import SQLConnector  # corp-only; import preguicoso em main()

ROOT     = Path(__file__).resolve().parent.parent
VAR_CSV  = ROOT / "data" / "ipca_pareto_recon.csv"
IDX_CSV  = ROOT / "data" / "ipca_pareto_indice.csv"
PESO_CSV = ROOT / "data" / "ipca_pareto_pesos.csv"

# 28 category_code -> nome legivel (mesma estetica do sidra_itau).
# NOTA: ex3_serv (estrito, sem alim_fora) é distinto de servicos_subj (subjacente
# tradicional, COM alim_fora). SGS 29683 do BCB bate com servicos_subj, não ex3_serv.
CATEGORY_LABELS = {
    "total":           "IPCA: Total",
    "administrados":   "IPCA: Monitorados",
    "livres":          "IPCA: Livres",
    "industriais":     "IPCA: Industriais",
    "servicos":        "IPCA: Servicos",
    "alim_domicilio":  "IPCA: Alimentacao no Domicilio",
    "nucleo_ex0":      "IPCA: Nucleo EX0",
    "nucleo_ex3":      "IPCA: Nucleo EX3",
    "duraveis":        "IPCA: Bens Duraveis",
    "semiduraveis":    "IPCA: Bens Semiduraveis",
    "ndur_industr":    "IPCA: Bens Nao-Duraveis Industriais",
    "servicos_subj":   "IPCA: Servicos Subjacentes (tradicional, c/ alim fora)",
    "servicos_exsubj": "IPCA: Servicos Ex-Subjacentes",
    "alim_in_natura":  "IPCA: Alimentos In Natura",
    "alim_semi_elab":  "IPCA: Alimentos Semi-Elaborados",
    "alim_industr":    "IPCA: Alimentos Industrializados",
    "comerc":          "IPCA: Comercializaveis",
    "ncomerc":         "IPCA: Nao-Comercializaveis",
    "nucleo_ma":       "IPCA: Nucleo MA",
    "nucleo_ms":       "IPCA: Nucleo MS",
    "nucleo_dp":       "IPCA: Nucleo DP",
    # NT_57/Dez-2025 — núcleos novos
    "nucleo_exfe":     "IPCA: Nucleo EX-FE",
    "nucleo_ex1":      "IPCA: Nucleo EX1",
    "ex3_serv":        "IPCA: Nucleo EX3 Servicos (estrito, ex alim fora)",
    "ex3_ind":         "IPCA: Nucleo EX3 Industriais",
    "difusao":         "IPCA: Indice de Difusao",
    "nucleo_p55":      "IPCA: Nucleo P55 (Percentil 55)",
    "nucleo_medio":    "IPCA: Nucleo Medio (media dos 5)",
}

# Sync 2026-07-17: codes simplificados gravados em bls_code; haver_code fica
# NULL em tudo que este loader escreve como INSERT novo (nao entra no dict de
# meta). Rows do formato antigo (`haver_code LIKE 'PARETO_IPCA:%'`) sao
# migradas por _migrate_haver_to_bls antes do main loop — la SIM o UPDATE
# desassocia a row do haver_code antigo setando explicitamente NULL. 2 codes
# por cat:
#   IPCA:{cat}         -> lado var/label (var NSA, var SA, Weight-label)
#   IPCA:{cat}/Index   -> lado idx (idx NSA, idx SA, Weight-Index)
CODE_VAR   = "IPCA:{cat}"
CODE_INDEX = "IPCA:{cat}/Index"


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
    """Espelho do sidra_to_sql do sidra_itau.ipynb (limpo).
    Novos INSERTs NAO tocam em haver_code (fica NULL por default do SQL);
    o code novo grava em bls_code."""
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
    # Alinha data ao ultimo dia do mes (convencao Haver corp). CSVs upstream
    # ficam em dia 01; conversao centralizada aqui pra todo write SQL.
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


def _try_sa(series: pd.Series):
    # X-13 e dependencia pesada (corp-only). Importa preguicoso pra nao quebrar
    # o load NSA caso x13as nao esteja disponivel.
    #
    # x13as eh vendored em script_itau/x13as/ (mesmo dir deste script). Tanto
    # o pacote Python (x13_custom) quanto o binario + specs estao la dentro.
    # Resolvemos tudo via __file__ pra funcionar independentemente do cwd.
    script_dir = Path(__file__).resolve().parent
    if str(script_dir) not in sys.path:
        sys.path.insert(0, str(script_dir))
    x13_dir = script_dir / "x13as"
    spec_main = str(x13_dir / "specs" / "Haver_Spec.spc")
    spec_addv = str(x13_dir / "specs" / "Haver_Spec_Add.spc")

    from x13as.x13_custom import x13_arima_analysis as x13_custom
    try:
        s = series.dropna().iloc[-1019:]
        s = s[s.index.year >= 1950]
        sa = x13_custom(s, x12path=str(x13_dir),
                        custom_spec=spec_main, retspec=True)
    except Exception as e:
        if "zero or negative" in str(e).lower() or "Multiplicative" in str(e):
            sa = x13_custom(s, x12path=str(x13_dir),
                            custom_spec=spec_addv, retspec=True)
        else:
            raise
    return sa.seasadj


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


def _preflight(session, max_desc_len: int) -> bool:
    """Roda checagens read-only antes de escrever: conexao, existencia das
    tabelas, coluna bls_code presente, largura da description, e lista series
    pre-existentes tanto no formato novo (bls_code LIKE 'IPCA:%') quanto no
    antigo (haver_code LIKE 'PARETO_IPCA:%', pendentes de migracao)."""
    print("\n[preflight] Validando ambiente SQL...")
    ok = True

    # 1. Conexao + tabelas existem
    for tbl in ("OPT_Macro_Series_2", "OPT_Macro_Series_Data_2"):
        try:
            n = pd.read_sql(f"SELECT COUNT(*) AS n FROM {tbl}", session.conn).iloc[0]["n"]
            print(f"  [OK] {tbl:22s} acessivel ({n} linhas)")
        except Exception as e:
            print(f"  [FAIL] {tbl}: {e}"); ok = False

    # 2. Coluna bls_code existe (necessaria pra sync 2026-07-17)
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

    # 3. Coluna description suporta nosso pior caso
    try:
        col = pd.read_sql(
            """SELECT character_maximum_length AS n
               FROM INFORMATION_SCHEMA.COLUMNS
               WHERE table_name = 'OPT_Macro_Series_2' AND column_name = 'description'""",
            session.conn,
        )
        if col.empty:
            print("  [WARN] description column metadata not found")
        else:
            n = int(col.iloc[0]["n"]) if col.iloc[0]["n"] is not None else -1
            if n == -1:
                print(f"  [OK] description = VARCHAR(MAX) — suporta {max_desc_len} chars")
            elif n >= max_desc_len:
                print(f"  [OK] description = VARCHAR({n}) — suporta {max_desc_len} chars")
            else:
                print(f"  [FAIL] description = VARCHAR({n}), precisa {max_desc_len}"); ok = False
    except Exception as e:
        print(f"  [WARN] nao foi possivel checar tamanho de description: {e}")

    # 4. Series ja cadastradas — dois grupos:
    #    (a) formato NOVO (bls_code LIKE 'IPCA:%') — serao reusadas por series_id
    #    (b) formato ANTIGO (haver_code LIKE 'PARETO_IPCA:%') — pendentes de
    #        migracao (executada logo antes do main loop)
    try:
        df_new = pd.read_sql(
            """SELECT series_id, series_name, data_type, bls_code
               FROM OPT_Macro_Series_2
               WHERE bls_code LIKE 'IPCA:%'
               ORDER BY series_id""",
            session.conn,
        )
        print(f"\n  Series formato NOVO (bls_code LIKE 'IPCA:%'): {len(df_new)}")
        if not df_new.empty:
            with pd.option_context("display.max_colwidth", 60, "display.width", 200):
                print(df_new.head(20).to_string(index=False))

        df_old = pd.read_sql(
            """SELECT series_id, series_name, data_type, haver_code
               FROM OPT_Macro_Series_2
               WHERE haver_code LIKE 'PARETO_IPCA:%'
               ORDER BY series_id""",
            session.conn,
        )
        print(f"\n  Series formato ANTIGO (haver_code LIKE 'PARETO_IPCA:%'): {len(df_old)}")
        if not df_old.empty:
            with pd.option_context("display.max_colwidth", 60, "display.width", 200):
                print(df_old.head(20).to_string(index=False))
            print("  -> serao migradas (haver_code -> NULL, bls_code populado, "
                  "Peso->Weight) antes do main loop.")
    except Exception as e:
        print(f"  [WARN] nao foi possivel listar series: {e}")

    return ok


# Padroes do formato antigo pra descobrir se a linha eh do lado var/label ou
# do lado index. Usado pela migracao. Sha varia por commit, cat varia por serie.
_OLD_INDEX_PATTERN = re.compile(r"^PARETO_IPCA:[^/]+/V63/Index/")


def _migrate_haver_to_bls(session, cats: set[str]) -> int:
    """Encontra series com haver_code no formato antigo (PARETO_IPCA:{cat}/...)
    e migra:
      - haver_code -> NULL (desassocia da string antiga)
      - bls_code   -> novo simplificado (IPCA:{cat} ou IPCA:{cat}/Index)
      - data_type  -> Weight (se antes era Peso)
    Somente linhas cuja categoria aparece em `cats` (evita mexer em ranges
    fora do escopo do run). Retorna quantas linhas atualizou."""
    print("\n[migracao] Procurando series com haver_code no formato antigo...")
    df = pd.read_sql(
        """SELECT series_id, series_name, data_type, haver_code
           FROM OPT_Macro_Series_2
           WHERE haver_code LIKE 'PARETO_IPCA:%'
           ORDER BY series_id""",
        session.conn,
    )
    if df.empty:
        print("  nenhuma serie no formato antigo — nada a migrar.")
        return 0

    n_updated = 0
    for _, row in df.iterrows():
        haver = row["haver_code"]
        cat = haver.split(":", 1)[1].split("/", 1)[0]
        if cat not in cats:
            continue
        is_index_side = bool(_OLD_INDEX_PATTERN.match(haver))
        new_code = (CODE_INDEX if is_index_side else CODE_VAR).format(cat=cat)
        new_dtype = "Weight" if row["data_type"] == "Peso" else row["data_type"]
        session.execute(
            "UPDATE OPT_Macro_Series_2 SET haver_code = NULL, bls_code = ?, "
            "data_type = ? WHERE series_id = ?",
            params=[new_code, new_dtype, int(row["series_id"])],
        )
        n_updated += 1
        print(f"  [UPDATE] id={row['series_id']:5d} {row['series_name']:55s} "
              f"{row['data_type']:6s} -> {new_dtype:6s}  bls_code={new_code}")
    print(f"  {n_updated} series migradas.")
    return n_updated


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sa", action="store_true",
                        help="Tambem gera e grava versao dessazonalizada (X-13).")
    parser.add_argument("--dry-run", action="store_true",
                        help="So lista o que seria feito, sem abrir conexao SQL.")
    parser.add_argument("--check", action="store_true",
                        help="Conecta no SQL e roda preflight read-only (sem escrever).")
    parser.add_argument("--only", type=str, default=None,
                        help="Lista CSV de category_code pra carregar (ex: 'livres,nucleo_ex0').")
    parser.add_argument("--no-confirm", action="store_true",
                        help="Pula confirmacao interativa antes de escrever no SQL.")
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

    if args.dry_run:
        print("\n[dry-run] Seriam carregadas:")
        for c in cats:
            label = CATEGORY_LABELS[c]
            sp = peso_series.get(c)
            peso_info = f"Weight x2: {len(sp)} obs" if sp is not None else "sem Weight"
            print(f"  - {label:45s}  var: {len(var_series[c])} obs   "
                  f"idx: {len(idx_series[c])} obs   {peso_info}")
            print(f"    bls_code (var/label): {CODE_VAR.format(cat=c)}")
            print(f"    bls_code (idx/Index): {CODE_INDEX.format(cat=c)}")
            if args.sa:
                print(f"  - {label + ' (SA)':45s}  var/idx dessazonalizados (X-13)")
        return

    from opt_utils.database import SQLConnector  # import preguicoso (corp-only)
    session = SQLConnector(connector="pyodbc")
    try:
        # Comprimento maximo das descricoes que vamos inserir (audita VARCHAR).
        max_desc = max(
            len(f"{CATEGORY_LABELS[c]} - Variacao mensal (%) - recon IBGE-only via NT_57/Dez-2025")
            for c in cats
        )
        ok = _preflight(session, max_desc)
        if args.check:
            print("\n[--check] preflight only; nada gravado.")
            return
        if not ok:
            sys.exit("\n[ABORT] preflight reprovou. Veja [FAIL] acima.")

        # Migracao: linhas antigas (haver_code LIKE 'PARETO_IPCA:%') sao movidas
        # pro novo esquema (haver_code=NULL, bls_code preenchido, Peso->Weight)
        # antes de qualquer novo write. Idempotente: reruns nao encontram nada.
        _migrate_haver_to_bls(session, set(cats))

        if not args.no_confirm:
            n_peso = sum(1 for c in cats if c in peso_series)
            # Convencao 2026-07-17: peso duplicado (label + label Indice), por
            # isso n_peso × 2. Var+idx multiplicam por 2 se --sa (NSA + SA).
            n_writes = len(cats) * 2 * (2 if args.sa else 1) + n_peso * 2
            resp = input(f"\nConfirma gravacao de ate {n_writes} series no SQL? [s/N] ").strip().lower()
            if resp != "s":
                sys.exit("[ABORT] confirmacao negada.")

        for c in cats:
            label = CATEGORY_LABELS[c]
            label_idx = f"{label} (Indice)"
            sv = var_series[c]
            si = idx_series[c]
            sp = peso_series.get(c)
            bls_var = CODE_VAR.format(cat=c)
            bls_idx = CODE_INDEX.format(cat=c)
            print(f"\n--- {label} ({c}) ---")
            print(f"    var: {len(sv)} obs {sv.index.min().date()} -> {sv.index.max().date()}")
            print(f"    idx: {len(si)} obs (base 100 em dez/2006)")
            if sp is not None:
                print(f"    Weight x2: {len(sp)} obs {sp.index.min().date()} -> {sp.index.max().date()}")

            # 1) Variacao mensal NSA (lado label)
            sidra_to_sql(
                series=sv, country="BR", subject="Prices", indicator="IPCA",
                series_name=label, data_type="NSA", frequency="M",
                description=f"{label} - Variacao mensal (%) - recon IBGE-only via NT_57/Dez-2025",
                bls_code=bls_var,
                session=session, replace=True,
            )
            # 2) Indice NSA (lado Indice)
            sidra_to_sql(
                series=si, country="BR", subject="Prices", indicator="IPCA",
                series_name=label_idx, data_type="NSA", frequency="M",
                description=f"{label} - Indice (dez/2006=100) - recon IBGE-only via NT_57/Dez-2025",
                bls_code=bls_idx,
                session=session, replace=True,
            )
            # 3) Weight duplicado (sync 2026-07-17): grava 2 vezes com o mesmo
            # array de valores, pareado por series_name/bls_code — o frontend
            # capta o peso via casamento de series_name + country + indicator,
            # trocando apenas data_type. Um Weight pareia com o lado label
            # (var), outro com o lado Indice (idx).
            if sp is not None:
                sidra_to_sql(
                    series=sp, country="BR", subject="Prices", indicator="IPCA",
                    series_name=label, data_type="Weight", frequency="M",
                    description=f"{label} - Weight mensal (V66 IBGE/SIDRA, Laspeyres) - par com var",
                    bls_code=bls_var,
                    session=session, replace=True,
                )
                sidra_to_sql(
                    series=sp, country="BR", subject="Prices", indicator="IPCA",
                    series_name=label_idx, data_type="Weight", frequency="M",
                    description=f"{label} - Weight mensal (V66 IBGE/SIDRA, Laspeyres) - par com idx",
                    bls_code=bls_idx,
                    session=session, replace=True,
                )

            if args.sa:
                try:
                    # Idx-first: dessazonaliza o nivel (sempre positivo → log
                    # estavel, ARIMA converge), depois deriva var_SA via
                    # identidade `var[t]=(idx[t]/idx[t-1]-1)·100`. Garante
                    # consistencia interna (var cumulativa = idx) e contorna
                    # falhas de convergencia que afetam series-var com
                    # negativos/outliers (alim_dom, etc.). Alinha com
                    # metodologia BCB/sellsides que dessazonalizam o nivel.
                    si_sa = _try_sa(si)
                    sv_sa = ((si_sa / si_sa.shift(1)) - 1) * 100
                    sv_sa = sv_sa.dropna()
                    sidra_to_sql(
                        series=sv_sa, country="BR", subject="Prices", indicator="IPCA",
                        series_name=label, data_type="SA", frequency="M",
                        description=f"{label} - Variacao mensal (%) - SA derivada do idx_SA (X-13 no nivel)",
                        bls_code=bls_var,
                        session=session, replace=True,
                    )
                    sidra_to_sql(
                        series=si_sa, country="BR", subject="Prices", indicator="IPCA",
                        series_name=label_idx, data_type="SA", frequency="M",
                        description=f"{label} - Indice (dez/2006=100) - dessazonalizada X-13",
                        bls_code=bls_idx,
                        session=session, replace=True,
                    )
                except Exception as e:
                    print(f"    [WARN] SA falhou para {c}: {e}")

    finally:
        session.close()

    n_peso_ok = sum(1 for c in cats if c in peso_series)
    print(f"\n[OK] {len(cats)} categorias carregadas "
          f"(var+idx+{n_peso_ok * 2} Weight (x2)) em "
          f"OPT_Macro_Series_2 / OPT_Macro_Series_Data_2.")


if __name__ == "__main__":
    main()
