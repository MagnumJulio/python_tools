"""Testa variantes do recipe pubtrans_medical vs Haver pra ver qual definicao bate."""
import pandas as pd
import sys
sys.path.insert(0, r'D:/Projetos gerais/Projetos-dev/python_projects/python_tools/pareto_cpius/quick_update')
from update_cpius_lean import build_custom_idx

# Carrega dados wide: index=date, cols=base cats
recon = pd.read_csv(r'D:/Projetos gerais/Projetos-dev/python_projects/python_tools/pareto_cpius/data/cpi_cpius_recon.csv')
pesos = pd.read_csv(r'D:/Projetos gerais/Projetos-dev/python_projects/python_tools/pareto_cpius/data/cpi_cpius_pesos.csv')
recon['date'] = pd.to_datetime(recon['date'])
pesos['date'] = pd.to_datetime(pesos['date'])

idx_sa = recon[recon['sa_flag']=='SA'].pivot(index='date', columns='category_code', values='value_index')
peso_wide = pesos.pivot(index='date', columns='category_code', values='value')

# Recipes candidatas
variants = {
    "current (SETG+SAM2)": {"method":"exclude","base":"core_services",
        "excludes":["rent","oer","lodging_away","public_transportation","medical_services"],"includes":[]},
    "V1: swap SETG->SETG01(airline)": {"method":"exclude","base":"core_services",
        "excludes":["rent","oer","lodging_away","airline_fares","medical_services"],"includes":[]},
    "V2: add motor_vehicle_insur": {"method":"exclude","base":"core_services",
        "excludes":["rent","oer","lodging_away","public_transportation","medical_services","motor_vehicle_insur"],"includes":[]},
    "V3: NO lodging_away (rent+oer only)": {"method":"exclude","base":"core_services",
        "excludes":["rent","oer","public_transportation","medical_services"],"includes":[]},
    "V4: SETG + hospital+phys only": {"method":"exclude","base":"core_services",
        "excludes":["rent","oer","lodging_away","public_transportation","hospital_services","physicians_services"],"includes":[]},
}

# Haver reference
haver = [0.27, 0.14, 0.20, float('nan'), 0.46, -0.27, 0.48, 0.24, 0.04, 0.32, 0.13, -0.21]
dates = pd.date_range('2025-07-01','2026-06-01', freq='MS')

# Compute each variant
print(f'{"variant":45s} {"max|d|":>8s} {"mean|d|":>8s} {"ok/N":>6s}')
print('-' * 75)
for name, recipe in variants.items():
    idx = build_custom_idx(recipe, idx_sa, peso_wide)
    mom = idx.pct_change() * 100
    diffs, ok, n = [], 0, 0
    for d, h in zip(dates, haver):
        if pd.isna(h): continue
        try: l = mom.loc[d]
        except KeyError: l = float('nan')
        if pd.notna(l):
            n += 1
            diff = l - h
            diffs.append(abs(diff))
            if abs(diff) <= 0.05: ok += 1
    maxd = max(diffs) if diffs else float('nan')
    meand = sum(diffs)/len(diffs) if diffs else float('nan')
    print(f'{name:45s} {maxd:>8.3f} {meand:>8.3f} {ok:>3d}/{n}')

# Detail winner
print('\n\n=== DETAIL current recipe (baseline) ===')
recipe = variants["current (SETG+SAM2)"]
idx = build_custom_idx(recipe, idx_sa, peso_wide)
mom = idx.pct_change() * 100
for d, h in zip(dates, haver):
    if pd.isna(h): continue
    try: l = mom.loc[d]
    except KeyError: l = float('nan')
    diff = l - h if pd.notna(l) else float('nan')
    lval = f'{l:+.3f}' if pd.notna(l) else '   nan'
    dval = f'{diff:+.3f}' if pd.notna(diff) else '   nan'
    print(f'  {d:%Y-%m}  haver={h:+.3f}  lean={lval}  diff={dval}')
