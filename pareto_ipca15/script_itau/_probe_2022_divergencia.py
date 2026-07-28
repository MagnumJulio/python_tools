#!/usr/bin/env python
# Diagnostico focado em 2021-2023 pra identificar a fonte da divergencia MS/DP/MA.
import sys
from pathlib import Path
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
VAR_CSV = ROOT / "data" / "ipca15_pareto_recon.csv"

NUCLEOS = [("nucleo_ma", 11426), ("nucleo_ms", 4466), ("nucleo_dp", 16122)]

def fetch_sgs(code):
    url = f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.{code}/dados?formato=json"
    r = requests.get(url, timeout=60); r.raise_for_status()
    df = pd.DataFrame(r.json())
    df["date"] = pd.to_datetime(df["data"], format="%d/%m/%Y")
    df["value"] = df["valor"].astype(float)
    return df.set_index("date")["value"].sort_index()

long_var = pd.read_csv(VAR_CSV)
long_var["date"] = pd.to_datetime(long_var["date"])

print("=" * 70)
print("DIVERGENCIA MENSAL — top 15 piores meses (toda historia)")
print("=" * 70)
for cat, sgs in NUCLEOS:
    ours = long_var[long_var.category_code == cat].set_index("date")["value"].sort_index()
    bcb = fetch_sgs(sgs)
    m = pd.concat([ours.rename("ours"), bcb.rename("bcb")], axis=1, join="inner").dropna()
    m["diff"] = m["ours"] - m["bcb"]
    top = m.reindex(m["diff"].abs().sort_values(ascending=False).index).head(15)
    print(f"\n[{cat}] SGS {sgs}")
    print(f"  {'date':10s} {'ours':>8s} {'bcb':>8s} {'diff':>8s}")
    for d, row in top.iterrows():
        print(f"  {d.strftime('%Y-%m'):10s} {row['ours']:>8.4f} {row['bcb']:>8.4f} {row['diff']:>+8.4f}")

print("\n" + "=" * 70)
print("ZOOM 2021-2023 — todos os meses, lado a lado")
print("=" * 70)
for cat, sgs in NUCLEOS:
    ours = long_var[long_var.category_code == cat].set_index("date")["value"].sort_index()
    bcb = fetch_sgs(sgs)
    m = pd.concat([ours.rename("ours"), bcb.rename("bcb")], axis=1, join="inner").dropna()
    m["diff"] = m["ours"] - m["bcb"]
    m = m[(m.index >= "2021-01-01") & (m.index <= "2023-12-31")]
    print(f"\n[{cat}] SGS {sgs}  — bias 2021-2023: {m['diff'].mean():+.4f}  mean|d|: {m['diff'].abs().mean():.4f}")
    print(f"  {'date':10s} {'ours':>8s} {'bcb':>8s} {'diff':>8s}")
    for d, row in m.iterrows():
        mark = "  <<<" if abs(row['diff']) > 0.15 else ""
        print(f"  {d.strftime('%Y-%m'):10s} {row['ours']:>8.4f} {row['bcb']:>8.4f} {row['diff']:>+8.4f}{mark}")
