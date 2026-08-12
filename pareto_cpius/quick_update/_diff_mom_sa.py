"""Diff MoM SA lean pipeline vs Haver reference (from tabelas_cpi_macroitau.xlsx)."""
import pandas as pd

recon = pd.read_csv(r'D:/Projetos gerais/Projetos-dev/python_projects/python_tools/pareto_cpius/data/cpi_cpius_recon.csv')
custom = pd.read_csv(r'D:/Projetos gerais/Projetos-dev/python_projects/python_tools/pareto_cpius/data/cpi_cpius_custom.csv')
recon['date'] = pd.to_datetime(recon['date'])
custom['date'] = pd.to_datetime(custom['date'])
df = pd.concat([recon, custom], ignore_index=True)
df = df[df['sa_flag'] == 'SA']
df = df[(df['date'] >= '2025-07-01') & (df['date'] <= '2026-06-01')]

mapping = {
    'Headline CPI': 'all_items',
    'CPI ex. Food & energy': 'core',
    'goods ex food & energy': 'core_goods',
    'services ex. energy': 'core_services',
    'core services ex-rents of shelter': 'supercore_powell_old',
    'core services ex-shelter plus lodging away': 'supercore_powell_old',
    'core services ex-shelter': 'core_services_ex_shelter',
    'food': 'food',
    'energy': 'energy',
    'core cpi ex oer': 'core_ex_oer',
    'cpi ex oer': 'cpi_ex_oer',
    'core services ex rent of shelter, public transportation & medical services': 'core_services_ex_shelter_pubtrans_medical',
    'super super core': 'super_super_core',
    'core services ex volatiles': 'core_services_ex_volatiles',
}
haver = {
    'Headline CPI':                              [0.23, 0.35, 0.30, 0.11, 0.13, 0.30, 0.17, 0.27, 0.87, 0.64, 0.47, -0.42],
    'CPI ex. Food & energy':                     [0.31, 0.31, 0.22, 0.09, 0.09, 0.23, 0.30, 0.22, 0.20, 0.38, 0.21, -0.02],
    'goods ex food & energy':                    [0.21, 0.22, 0.20, 0.03, 0.03, 0.03, 0.04, 0.08, 0.11, 0.003, -0.11, -0.09],
    'services ex. energy':                       [0.35, 0.32, 0.23, 0.10, 0.10, 0.27, 0.39, 0.27, 0.23, 0.50, 0.29, 0.03],
    'core services ex-rents of shelter':         [0.46, 0.31, 0.31, 0.05, 0.05, 0.23, 0.59, 0.35, 0.18, 0.45, 0.27, -0.20],
    'core services ex-shelter plus lodging away':[0.44, 0.31, 0.30, 0.05, 0.05, 0.22, 0.59, 0.35, 0.17, 0.46, 0.27, -0.21],
    'core services ex-shelter': [0.52, 0.21, 0.27, 0.08, 0.08, 0.12, 0.63, 0.32, 0.17, 0.35, 0.26, -0.09],
    'food':                                      [0.12, 0.42, 0.22, 0.04, 0.04, 0.66, 0.19, 0.39, -0.01, 0.50, 0.16, 0.21],
    'energy':                                    [-0.62, 0.69, 1.43, 0.70, 0.70, 0.34, -1.47, 0.63, 10.87, 3.81, 3.88, -5.71],
    'core cpi ex oer':                           [0.33, 0.30, 0.25, 0.05, 0.08, 0.20, 0.33, 0.21, 0.16, 0.31, 0.17, -0.14],
    'cpi ex oer':                                [0.21, 0.35, 0.34, 0.01, 0.22, 0.29, 0.15, 0.28, 1.06, 0.68, 0.53, -0.64],
    'core services ex rent of shelter, public transportation & medical services': [0.27, 0.14, 0.20, float('nan'), 0.46, -0.27, 0.48, 0.24, 0.04, 0.32, 0.13, -0.21],
    'super super core':                          [0.31, 0.12, 0.22, float('nan'), 0.40, -0.14, 0.43, 0.14, 0.10, 0.33, 0.00, -0.08],
    'core services ex volatiles':                [0.25, 0.30, 0.20, float('nan'), 0.30, 0.20, 0.29, 0.20, 0.21, 0.52, 0.21, 0.05],
}
dates = pd.date_range('2025-07-01', '2026-06-01', freq='MS')
lean = df.pivot_table(index='date', columns='category_code', values='value_var_mm')

print(f"{'series':50s} {'max|d|':>7s} {'mean|d|':>8s} {'ok/N':>7s}")
print('-' * 78)
for hlabel, lean_cat in mapping.items():
    if lean_cat not in lean.columns:
        print(f'{hlabel:50s}  MISSING lean cat: {lean_cat}')
        continue
    haver_vals = haver[hlabel]
    diffs = []
    valid = 0
    ok = 0
    for d, h in zip(dates, haver_vals):
        try:
            l = lean.loc[d, lean_cat]
        except KeyError:
            l = float('nan')
        if pd.notna(l):
            valid += 1
            diff = l - h
            diffs.append(abs(diff))
            if abs(diff) <= 0.05:
                ok += 1
    maxd = max(diffs) if diffs else float('nan')
    meand = sum(diffs) / len(diffs) if diffs else float('nan')
    print(f'{hlabel:50s} {maxd:>7.3f} {meand:>8.3f} {ok:>3d}/{valid:<3d}  [{lean_cat}]')

print('\n\n=== DETAIL per series ===')
for hlabel, lean_cat in mapping.items():
    if lean_cat not in lean.columns:
        continue
    haver_vals = haver[hlabel]
    print(f'\n{hlabel} -> {lean_cat}')
    print(f'  date       haver   lean    diff pp')
    for d, h in zip(dates, haver_vals):
        try:
            l = lean.loc[d, lean_cat]
        except KeyError:
            l = float('nan')
        diff = l - h if pd.notna(l) else float('nan')
        mark = ''
        if pd.isna(l):
            mark = '  [NaN - shutdown gap?]'
        elif abs(diff) > 0.05:
            mark = '  <-- MISMATCH'
        elif abs(diff) > 0.02:
            mark = '  warn'
        lval = f'{l:+.3f}' if pd.notna(l) else '   nan'
        dval = f'{diff:+.3f}' if pd.notna(diff) else '   nan'
        print(f'  {d:%Y-%m}  {h:+.3f}  {lval}  {dval}{mark}')
