#!/usr/bin/env python
# Mini-script corp-only: reconstroi var SA + idx SA de nucleo_medio a partir
# dos 5 componentes (EX0, EX3, MS, DP, P55) que ja foram dessazonalizados
# com sucesso pelo _try_sa().
#
# Por que: nucleo_medio = mean(EX0, EX3, MS, DP, P55) por definicao (NT_57 +
# EE102/2021). Logo SA(nucleo_medio) ≡ mean(SA(EX0)..SA(P55)). Mais robusto
# que rodar X-13 num agregado derivado (que pode falhar por baixa volatilidade
# ou warnings idiossincraticos do X-13).
#
# Uso: python script_itau/_fix_nucleo_medio_sa.py
# Pre-req: load_pareto_to_sql.py --sa rodado (5 componentes SA no SQL).

import sys
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "script_itau"))

from load_pareto_to_sql import sidra_to_sql, CODE, CATEGORY_LABELS

CAT = "nucleo_medio"
LABEL = CATEGORY_LABELS[CAT]
BLS = CODE.format(cat=CAT)
COMPS = ["nucleo_ex0", "nucleo_ex3", "nucleo_ms", "nucleo_dp", "nucleo_p55"]

from opt_utils.database import SQLConnector

session = SQLConnector(connector="pyodbc")
try:
    # 1) Le var SA dos 5 componentes.
    # Sync 2026-07-27: SA var identificada por (bls_code, data_type, series_name).
    pieces = {}
    for c in COMPS:
        df = pd.read_sql(
            """
            SELECT d.date, d.value
            FROM OPT_Macro_Series_Data_2 d
            JOIN OPT_Macro_Series_2 m ON d.series_id = m.series_id
            WHERE m.bls_code = ? AND m.data_type = 'SA' AND m.series_name = ?
            ORDER BY d.date
            """,
            session.conn,
            params=[CODE.format(cat=c), CATEGORY_LABELS[c]],
        )
        if df.empty:
            sys.exit(f"[FAIL] var SA de {c} nao encontrada no SQL. "
                     "Rode load_pareto_to_sql.py --sa antes.")
        df["date"] = pd.to_datetime(df["date"])
        pieces[c] = df.set_index("date")["value"].astype(float).sort_index()
        print(f"  [OK] {c}: {len(pieces[c])} obs")

    # 2) Var SA do medio = media linha-a-linha dos 5 (so nas datas com os 5 OK)
    wide = pd.DataFrame(pieces)
    wide = wide.dropna(how="any")  # so meses com todos 5 presentes
    var_sa = wide.mean(axis=1).rename(CAT)
    print(f"\n[OK] var SA do {CAT}: {len(var_sa)} obs "
          f"({var_sa.index.min().date()} -> {var_sa.index.max().date()})")

    # 3) Idx SA: idx_sa[t] = idx_sa[t-1] * (1 + var_sa[t]/100), rebase dez/2006=100
    idx_vals = [100.0]
    for v in var_sa.values:
        idx_vals.append(idx_vals[-1] * (1 + v / 100))
    idx_sa = pd.Series(idx_vals[1:], index=var_sa.index)

    ref_date = pd.Timestamp("2006-12-01")
    if ref_date in idx_sa.index:
        ref = float(idx_sa.loc[ref_date])
        idx_sa = idx_sa / ref * 100.0
        print(f"[OK] Rebase dez/2006=100 aplicado (ref pre-rebase={ref:.4f})")
    else:
        # nucleo_medio comeca em 2007-01 por causa do warm-up DP; usa
        # 1o mes disponivel como fallback
        first = idx_sa.iloc[0]
        idx_sa = idx_sa / first * 100.0
        print(f"[WARN] dez/2006 ausente; base 100 em {idx_sa.index.min().date()}")

    print(f"[preview] var_sa.tail():\n{var_sa.tail().to_string()}\n")
    print(f"[preview] idx_sa.tail():\n{idx_sa.tail().to_string()}\n")

    # 4) Grava var SA + idx SA no SQL
    sidra_to_sql(
        series=var_sa, country="BR", subject="Prices", indicator="IPCA",
        series_name=LABEL, data_type="SA", frequency="M",
        description=f"{LABEL} - Variacao mensal (%) - SA via media dos 5 componentes SA",
        bls_code=BLS,
        session=session, replace=True,
    )
    sidra_to_sql(
        series=idx_sa, country="BR", subject="Prices", indicator="IPCA",
        series_name=f"{LABEL} (Indice)", data_type="SA", frequency="M",
        description=f"{LABEL} - Indice (base=100) - SA via media dos 5 componentes SA",
        bls_code=BLS,
        session=session, replace=True,
    )
    print(f"[OK] var SA + idx SA de {CAT} gravados no SQL.")
finally:
    session.close()
