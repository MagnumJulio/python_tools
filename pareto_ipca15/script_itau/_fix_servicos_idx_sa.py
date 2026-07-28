#!/usr/bin/env python
# Mini-script corp-only: reconstroi indice SA de IPCA Servicos a partir da
# variacao SA (que ja esta no SQL apos load_pareto_to_sql.py --sa).
#
# Por que: _try_sa() falha pro indice nivel de servicos com warning
# "trading day peak" (TD effects fortes em servicos). Var SA passa OK.
# Workaround analitico: idx_sa[t] = idx_sa[t-1] * (1 + var_sa[t]/100),
# rebaseado em dez/2006=100 igual o NSA.
#
# Uso: python script_itau/_fix_servicos_idx_sa.py
# Pre-req: load_pareto_to_sql.py --sa ja rodado (var SA de servicos no SQL).
# Pre-req 2: meta legada "IPCA: Servicos (Indice)" data_type='SA' nao deve
# existir (vai colidir com upsert por chave natural — mesmo bug ja conhecido).

import sys
import subprocess
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "script_itau"))

from load_pareto_to_sql import sidra_to_sql, SIDRA_CODE_IDX, CATEGORY_LABELS


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True
        ).strip()
    except Exception:
        return "nogit"


CAT = "servicos"
LABEL = CATEGORY_LABELS[CAT]
sha = _git_sha()

from opt_utils.database import SQLConnector

session = SQLConnector(connector="pyodbc")
try:
    df = pd.read_sql(
        """
        SELECT d.date, d.value
        FROM OPT_Macro_Series_Data_2 d
        JOIN OPT_Macro_Series_2 m ON d.series_id = m.series_id
        WHERE m.haver_code LIKE 'PARETO_IPCA:servicos/V63/RECON-%/SA'
        ORDER BY d.date
        """,
        session.conn,
    )
    if df.empty:
        sys.exit("[FAIL] Var SA de servicos nao encontrada no SQL. "
                 "Rode load_pareto_to_sql.py --sa antes.")

    df["date"] = pd.to_datetime(df["date"])
    var_sa = df.set_index("date")["value"].astype(float).sort_index()
    print(f"[OK] var SA de {CAT}: {len(var_sa)} obs "
          f"({var_sa.index.min().date()} -> {var_sa.index.max().date()})")

    # idx_sa[t] = idx_sa[t-1] * (1 + var_sa[t]/100); base 100 no 1o mes
    idx_vals = [100.0]
    for v in var_sa.values:
        idx_vals.append(idx_vals[-1] * (1 + v / 100))
    idx_sa = pd.Series(idx_vals[1:], index=var_sa.index,
                       name=f"{LABEL} (Indice)")

    # Rebase dez/2006=100 (mesma base do NSA — ipca15_pareto_indice.csv).
    ref_date = pd.Timestamp("2006-12-01")
    if ref_date in idx_sa.index:
        ref = float(idx_sa.loc[ref_date])
        idx_sa = idx_sa / ref * 100.0
        print(f"[OK] Rebase dez/2006=100 aplicado (ref pre-rebase={ref:.4f})")
    else:
        print(f"[WARN] dez/2006 ausente; manteve base 100 em "
              f"{idx_sa.index.min().date()}")

    print(f"[preview] idx_sa.tail():\n{idx_sa.tail().to_string()}\n")

    sidra_to_sql(
        series=idx_sa, country="BR", subject="Prices", indicator="IPCA",
        series_name=f"{LABEL} (Indice)", data_type="SA", frequency="M",
        description=f"{LABEL} - Indice (dez/2006=100) - SA reconstruido via var SA",
        haver_code=SIDRA_CODE_IDX.format(cat=CAT, sha=sha) + "/SA",
        session=session, replace=True,
    )
    print(f"[OK] Indice SA de {CAT} gravado no SQL.")
finally:
    session.close()
