#!/usr/bin/env python
# Mini-script corp-only: grava SA de nucleo_dp + nucleo_medio (var + idx) no
# SQL a partir do CSV produzido pelo R `seasonal` (path alternativo ao
# wrapper corp x13_custom, que esta bugado pra essas 2 series com
# 'NoneType' object has no attribute 'startswith').
#
# Pre-req 1: Rscript scripts/_sa_dp_nucleo_medio.R rodado, produzindo
#            data/ipca15_pareto_sa_dp_medio.csv (long: date, category_code,
#            var_sa, idx_sa).
# Pre-req 2: load_pareto_to_sql.py NSA rodado (DP + nucleo_medio NSA no SQL).
#
# Uso: python script_itau/_fix_dp_medio_sa.py

import sys
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "script_itau"))

from load_pareto_to_sql import sidra_to_sql, CODE, CATEGORY_LABELS

SA_CSV = ROOT / "data" / "ipca15_pareto_sa_dp_medio.csv"
if not SA_CSV.exists():
    sys.exit(f"[FAIL] {SA_CSV} nao existe. Rode antes:\n"
             "  Rscript scripts/_sa_dp_nucleo_medio.R")

df = pd.read_csv(SA_CSV)
df["date"] = pd.to_datetime(df["date"])

from opt_utils.database import SQLConnector

session = SQLConnector(connector="pyodbc")
try:
    for cat in ["nucleo_dp", "nucleo_medio"]:
        sub = df[df["category_code"] == cat].sort_values("date").set_index("date")
        if sub.empty:
            print(f"[SKIP] {cat} ausente no CSV.")
            continue

        # var_sa tem NA no 1o mes (pct change). Remove pro write.
        var_sa = sub["var_sa"].dropna().astype(float).rename(cat)
        idx_sa = sub["idx_sa"].astype(float).rename(f"{cat} (Indice)")

        label = CATEGORY_LABELS[cat]
        bls = CODE.format(cat=cat)
        print(f"\n[{cat}] var SA: {len(var_sa)} obs "
              f"({var_sa.index.min().date()} -> {var_sa.index.max().date()})")
        print(f"[{cat}] idx SA: {len(idx_sa)} obs "
              f"({idx_sa.index.min().date()} -> {idx_sa.index.max().date()})")

        sidra_to_sql(
            series=var_sa, country="BR", subject="Prices", indicator="IPCA-15",
            series_name=label, data_type="SA", frequency="M",
            description=f"{label} - Variacao mensal (%) - SA via R seasonal "
                        "(workaround do wrapper x13_custom corp)",
            bls_code=bls,
            session=session, replace=True,
        )
        sidra_to_sql(
            series=idx_sa, country="BR", subject="Prices", indicator="IPCA-15",
            series_name=f"{label} (Indice)", data_type="SA", frequency="M",
            description=f"{label} - Indice (dez/2012=100) - SA via R seasonal",
            bls_code=bls,
            session=session, replace=True,
        )
        print(f"[OK] {cat} var+idx SA gravados no SQL.")
finally:
    session.close()
