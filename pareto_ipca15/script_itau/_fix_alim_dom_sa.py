#!/usr/bin/env python
# Mini-script corp-only: SA de alim_domicilio (var + idx) via idx-first.
#
# Por que: _try_sa(sv) falha porque var alim_dom tem negativos (log nega) E
# o aditivo nao converge (ARIMA (0 2 2) maxiter reached). Mas _try_sa(si)
# passa OK (idx sempre positivo → log estavel; warning TD peak nao e fatal).
#
# Workaround: dessazonaliza so o idx via wrapper corp (preserva regressores
# de calendario do Haver_Spec.spc — metodologia BCB). Deriva var_SA do
# idx_SA via identidade matematica `var[t] = (idx[t]/idx[t-1] - 1)·100`.
# Consistencia interna garantida (var cumulativa = idx exato).
#
# Pre-req: load_pareto_to_sql.py rodou (NSA gravado, mas SA falhou na var).
# Uso: python script_itau/_fix_alim_dom_sa.py

import sys
import subprocess
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "script_itau"))

from load_pareto_to_sql import (
    sidra_to_sql, _try_sa, _load_csv_long,
    SIDRA_CODE_VAR, SIDRA_CODE_IDX, CATEGORY_LABELS,
)


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True
        ).strip()
    except Exception:
        return "nogit"


CAT = "alim_domicilio"
LABEL = CATEGORY_LABELS[CAT]
sha = _git_sha()

from opt_utils.database import SQLConnector

session = SQLConnector(connector="pyodbc")
try:
    # 1) Le NSA idx do CSV (mais simples que SQL — sem dedup issues)
    idx_csv = ROOT / "data" / "ipca15_pareto_indice.csv"
    si_dict = _load_csv_long(idx_csv, "index")
    if CAT not in si_dict:
        sys.exit(f"[FAIL] {CAT} ausente em {idx_csv}")
    si = si_dict[CAT]
    print(f"[1] NSA idx de {CAT}: {len(si)} obs "
          f"({si.index.min().date()} -> {si.index.max().date()})")

    # 2) Dessazonaliza idx via wrapper corp (path que funciona)
    print(f"\n[2] Rodando _try_sa(si) — wrapper corp x13_custom...")
    si_sa = _try_sa(si).rename(f"{LABEL} (Indice)")
    print(f"    [OK] idx SA: {len(si_sa)} obs. Ultimos 3: "
          f"{si_sa.tail(3).round(4).to_dict()}")

    # 3) Deriva var_SA via pct change
    sv_sa = ((si_sa / si_sa.shift(1)) - 1) * 100
    sv_sa = sv_sa.dropna().rename(LABEL).astype(float)
    print(f"\n[3] var SA derivada: {len(sv_sa)} obs. Ultimos 3: "
          f"{sv_sa.tail(3).round(4).to_dict()}")

    # 4) Grava var SA + idx SA no SQL
    print(f"\n[4] Gravando no SQL...")
    sidra_to_sql(
        series=sv_sa, country="BR", subject="Prices", indicator="IPCA",
        series_name=LABEL, data_type="SA", frequency="M",
        description=f"{LABEL} - Variacao mensal (%) - SA derivada do idx_SA "
                    "(workaround: var path nao converge no aditivo)",
        haver_code=SIDRA_CODE_VAR.format(cat=CAT, sha=sha) + "/SA",
        session=session, replace=True,
    )
    sidra_to_sql(
        series=si_sa.astype(float), country="BR", subject="Prices", indicator="IPCA",
        series_name=f"{LABEL} (Indice)", data_type="SA", frequency="M",
        description=f"{LABEL} - Indice (dez/2006=100) - SA via x13_custom corp "
                    "(Haver_Spec.spc com regressores de calendario BCB)",
        haver_code=SIDRA_CODE_IDX.format(cat=CAT, sha=sha) + "/SA",
        session=session, replace=True,
    )
    print(f"[OK] var SA + idx SA de {CAT} gravados no SQL.")
finally:
    session.close()
