"""Testa variantes de recipe pubtrans_medical vs Haver YoY NSA (ground truth limpo)."""
import pandas as pd, sys
sys.path.insert(0, r'D:/Projetos gerais/Projetos-dev/python_projects/python_tools/pareto_cpius/quick_update')
from update_cpius_lean import build_custom_idx

recon = pd.read_csv(r'D:/Projetos gerais/Projetos-dev/python_projects/python_tools/pareto_cpius/data/cpi_cpius_recon.csv')
pesos = pd.read_csv(r'D:/Projetos gerais/Projetos-dev/python_projects/python_tools/pareto_cpius/data/cpi_cpius_pesos.csv')
recon['date'] = pd.to_datetime(recon['date'])
pesos['date'] = pd.to_datetime(pesos['date'])

idx_nsa = recon[recon['sa_flag']=='NSA'].pivot(index='date', columns='category_code', values='value_index')
peso_wide = pesos.pivot(index='date', columns='category_code', values='value')

variants = {
    "CURRENT (rent+oer+lodging+pubtrans+medical)": {"method":"exclude","base":"core_services",
        "excludes":["rent","oer","lodging_away","public_transportation","medical_services"],"includes":[]},
    "V3 (rent+oer only, sem lodging)": {"method":"exclude","base":"core_services",
        "excludes":["rent","oer","public_transportation","medical_services"],"includes":[]},
    "V5 (rent only, sem oer/lodging)": {"method":"exclude","base":"core_services",
        "excludes":["rent","public_transportation","medical_services"],"includes":[]},
    "V6 (shelter completo - proxy c/ 3 shelter cats)": {"method":"exclude","base":"core_services",
        "excludes":["rent","oer","lodging_away","public_transportation","medical_services"],"includes":[]},
    "V7 (rent+oer+lodging+airline+medical, sem pubtrans)": {"method":"exclude","base":"core_services",
        "excludes":["rent","oer","lodging_away","airline_fares","medical_services"],"includes":[]},
    "V8 (rent+oer+lodging+pubtrans+hosp+phys - medical stricto)": {"method":"exclude","base":"core_services",
        "excludes":["rent","oer","lodging_away","public_transportation","hospital_services","physicians_services"],"includes":[]},
}

# Haver YoY NSA (Nov/25 -> Jun/26)
haver = [3.64, 3.16, 3.52, 2.91, 2.40, 2.53, 2.42, 2.11]
dates = pd.date_range('2025-11-01','2026-06-01', freq='MS')

print(f'{"variant":60s} {"max|d|":>8s} {"mean|d|":>8s} {"ok/N":>6s}')
print('-' * 90)
for name, recipe in variants.items():
    idx = build_custom_idx(recipe, idx_nsa, peso_wide)
    yoy = (idx / idx.shift(12) - 1) * 100
    diffs, ok, n = [], 0, 0
    for d, h in zip(dates, haver):
        try: l = yoy.loc[d]
        except KeyError: l = float('nan')
        if pd.notna(l):
            n += 1
            diff = l - h
            diffs.append(abs(diff))
            if abs(diff) <= 0.05: ok += 1
    maxd = max(diffs) if diffs else float('nan')
    meand = sum(diffs)/len(diffs) if diffs else float('nan')
    print(f'{name:60s} {maxd:>8.3f} {meand:>8.3f} {ok:>3d}/{n}')

# Debug: qual e o peso relativo de cada componente que estamos excluindo?
print('\n=== PESOS Dez/2024 (peso NSA na base core_services) ===')
last_pesos = peso_wide.dropna(how='all').iloc[-1]
cs = last_pesos.get('core_services', float('nan'))
print(f'core_services base weight = {cs:.3f}')
for cat in ['rent','oer','lodging_away','public_transportation','medical_services',
            'airline_fares','hospital_services','physicians_services']:
    w = last_pesos.get(cat, float('nan'))
    pct = w/cs*100 if pd.notna(w) and pd.notna(cs) else float('nan')
    print(f'  {cat:30s} = {w:>7.3f}  ({pct:>5.2f}% of core_services)')
