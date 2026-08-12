"""Diff YoY NSA lean vs Haver — isola SA vintage vs recipe bug pra pubtrans_medical."""
import pandas as pd

recon = pd.read_csv(r'D:/Projetos gerais/Projetos-dev/python_projects/python_tools/pareto_cpius/data/cpi_cpius_recon.csv')
custom = pd.read_csv(r'D:/Projetos gerais/Projetos-dev/python_projects/python_tools/pareto_cpius/data/cpi_cpius_custom.csv')
recon['date'] = pd.to_datetime(recon['date'])
custom['date'] = pd.to_datetime(custom['date'])
df = pd.concat([recon, custom], ignore_index=True)
df = df[df['sa_flag'] == 'NSA']

# Precisamos value_index NSA pra calcular YoY = idx_t / idx_{t-12} - 1
idx = df.pivot_table(index='date', columns='category_code', values='value_index')
yoy = (idx / idx.shift(12) - 1) * 100

# Haver YoY NSA
mapping = {
    'Headline CPI':                                                                'all_items',
    'CPI ex. Food & energy':                                                       'core',
    'goods ex food & energy':                                                      'core_goods',
    'services ex food & energy':                                                   'core_services',
    'core services ex-rent of shelter':                                            'supercore_powell_old',
    'core services ex-shelter plus lodging':                                       'supercore_powell_old',
    'core services ex-shelter':                                                    'core_services_ex_shelter',
    'food':                                                                        'food',
    'energy':                                                                      'energy',
    'core services ex rent of shelter, public transportation & medical services':  'core_services_ex_shelter_pubtrans_medical',
}
haver = {
    'Headline CPI':                                [None,None,None,None,None, 3.81, 4.25, 3.53],
    'CPI ex. Food & energy':                       [None,None,None,None,None, 2.75, 2.85, 2.59],
    'goods ex food & energy':                      [None,None,None,None,None, 1.13, 1.06, 0.82],
    'services ex food & energy':                   [None,None,None,None,None, 3.27, 3.42, 3.16],
    'core services ex-rent of shelter':            [None,None,None,None,None, 3.38, 3.66, 3.17],
    'core services ex-shelter plus lodging':       [None,None,None,None,None, 3.29, 3.58, 3.10],
    'core services ex-shelter':                    [None,None,None,None,None, 3.22, 3.49, 3.00],
    'food':                                        [None,None,None,None,None, 3.18, 3.08, 3.01],
    'energy':                                      [None,None,None,None,None,17.87,23.54,15.70],
    'core services ex rent of shelter, public transportation & medical services':
                                                   [3.64,3.16,3.52,2.91,2.40, 2.53, 2.42, 2.11],
}
dates = pd.date_range('2025-11-01', '2026-06-01', freq='MS')

print(f"{'series':50s} {'max|d|':>7s} {'mean|d|':>8s} {'ok/N':>7s}")
print('-' * 78)
for hlabel, lean_cat in mapping.items():
    if lean_cat not in yoy.columns:
        print(f'{hlabel:50s}  MISSING lean cat: {lean_cat}')
        continue
    hvals = haver[hlabel]
    diffs, ok, valid = [], 0, 0
    for d, h in zip(dates, hvals):
        if h is None: continue
        try: l = yoy.loc[d, lean_cat]
        except KeyError: l = float('nan')
        if pd.notna(l):
            valid += 1
            diff = l - h
            diffs.append(abs(diff))
            if abs(diff) <= 0.05: ok += 1
    maxd = max(diffs) if diffs else float('nan')
    meand = sum(diffs)/len(diffs) if diffs else float('nan')
    print(f'{hlabel:50s} {maxd:>7.3f} {meand:>8.3f} {ok:>3d}/{valid:<3d}  [{lean_cat}]')

print('\n\n=== DETAIL pubtrans_medical (a serie que divergiu no MoM SA) ===')
lean_cat = 'core_services_ex_shelter_pubtrans_medical'
hvals = haver['core services ex rent of shelter, public transportation & medical services']
print(f'  date       haver   lean    diff pp')
for d, h in zip(dates, hvals):
    if h is None: continue
    try: l = yoy.loc[d, lean_cat]
    except KeyError: l = float('nan')
    diff = l - h if pd.notna(l) else float('nan')
    mark = ''
    if pd.isna(l): mark = '  [NaN]'
    elif abs(diff) > 0.05: mark = '  <-- MISMATCH'
    elif abs(diff) > 0.02: mark = '  warn'
    lval = f'{l:+.3f}' if pd.notna(l) else '   nan'
    dval = f'{diff:+.3f}' if pd.notna(diff) else '   nan'
    print(f'  {d:%Y-%m}  {h:+.3f}  {lval}  {dval}{mark}')
