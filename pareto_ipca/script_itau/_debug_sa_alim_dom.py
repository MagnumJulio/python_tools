#!/usr/bin/env python
# Diagnostico isolado: roda _try_sa em alim_domicilio (var e idx) com
# traceback completo. Imprime tudo o que precisamos pra entender por que
# o wrapper corp x13_custom esta falhando nessa categoria.
#
# Uso: python script_itau/_debug_sa_alim_dom.py
# Output esperado: 2 blocos (=== VAR SA === e === IDX SA ===) com OK ou
# traceback completo (incluindo o erro do path log E do path aditivo se
# ambos forem tentados).

import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "script_itau"))

from load_pareto_to_sql import _load_csv_long, _try_sa  # noqa: E402

CAT = "alim_domicilio"


def describe(name, s):
    print(f"  {name}: n={len(s)}, range=[{s.min():.4f}, {s.max():.4f}], "
          f"NaN={s.isna().sum()}, "
          f"first={s.index.min().date()}, last={s.index.max().date()}, "
          f"name={s.name!r}, freq={s.index.freq}")


def main():
    var_csv = ROOT / "data" / "ipca_pareto_recon.csv"
    idx_csv = ROOT / "data" / "ipca_pareto_indice.csv"

    print(f"[1] Carregando CSVs:")
    print(f"    var: {var_csv}")
    print(f"    idx: {idx_csv}")
    sv_dict = _load_csv_long(var_csv, "value")
    si_dict = _load_csv_long(idx_csv, "index")

    if CAT not in sv_dict:
        sys.exit(f"[FAIL] {CAT} ausente em {var_csv}")
    if CAT not in si_dict:
        sys.exit(f"[FAIL] {CAT} ausente em {idx_csv}")

    sv = sv_dict[CAT]
    si = si_dict[CAT]
    print(f"\n[2] Describe series:")
    describe("sv (variacao)", sv)
    describe("si (indice)  ", si)

    print(f"\n[3] sv.tail(6):\n{sv.tail(6).round(4).to_string()}")
    print(f"\n[4] si.tail(6):\n{si.tail(6).round(4).to_string()}")

    print("\n" + "=" * 70)
    print("=== VAR SA — _try_sa(sv) ===")
    print("=" * 70)
    try:
        sa_v = _try_sa(sv)
        print(f"\n[OK] var SA computado. Ultimos 3: "
              f"{sa_v.tail(3).round(4).to_dict()}")
    except Exception:
        print("\n[FAIL] var SA — traceback completo:")
        traceback.print_exc()

    print("\n" + "=" * 70)
    print("=== IDX SA — _try_sa(si) ===")
    print("=" * 70)
    try:
        sa_i = _try_sa(si)
        print(f"\n[OK] idx SA computado. Ultimos 3: "
              f"{sa_i.tail(3).round(4).to_dict()}")
    except Exception:
        print("\n[FAIL] idx SA — traceback completo:")
        traceback.print_exc()


if __name__ == "__main__":
    main()
