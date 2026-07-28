#!/usr/bin/env python3
# _probe_score.py — lê _probe_cache/*.json (fetchado via _probe_fetch.sh)
# e ranqueia SGS candidatos por corr vs data/ipca15_pareto_recon.csv.
# Saida: _probe_sgs_ipca15.out (top5 por cat) + stdout com best matches.

import csv, json, os, sys
from collections import defaultdict

ROOT  = os.path.dirname(os.path.abspath(__file__))
RECON = os.path.join(ROOT, "data", "ipca15_pareto_recon.csv")
CACHE = os.path.join(ROOT, "_probe_cache")
OUT   = os.path.join(ROOT, "_probe_sgs_ipca15.out")

def load_cache():
    series = {}
    for fn in os.listdir(CACHE):
        if not fn.endswith(".json"): continue
        sgs = int(fn[:-5])
        try:
            with open(os.path.join(CACHE, fn), encoding="utf-8") as f:
                d = json.load(f)
        except Exception:
            continue
        if not isinstance(d, list) or not d: continue
        s = {}
        for row in d:
            try:
                dd = row["data"]
                dt = f"{dd[6:10]}-{dd[3:5]}-{dd[0:2]}"
                s[dt] = float(row["valor"])
            except (KeyError, ValueError, TypeError):
                continue
        if len(s) >= 24:
            series[sgs] = s
    return series

def load_recon():
    by_cat = defaultdict(dict)
    with open(RECON, encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            by_cat[row["category_code"]][row["date"]] = float(row["value"])
    return by_cat

def score(ours, theirs):
    keys = sorted(set(ours) & set(theirs))
    if len(keys) < 24:
        return None
    a = [ours[k] for k in keys]
    b = [theirs[k] for k in keys]
    n = len(a)
    ma = sum(a)/n; mb = sum(b)/n
    va = sum((x-ma)**2 for x in a)/n
    vb = sum((x-mb)**2 for x in b)/n
    if va < 1e-12 or vb < 1e-12:
        return None
    cov = sum((a[i]-ma)*(b[i]-mb) for i in range(n))/n
    corr = cov / (va**0.5 * vb**0.5)
    diffs = [a[i]-b[i] for i in range(n)]
    return dict(n=n, ini=keys[0][:7], fim=keys[-1][:7],
                corr=corr, mean_abs=sum(abs(d) for d in diffs)/n,
                max_abs=max(abs(d) for d in diffs),
                bias=sum(diffs)/n)

def main():
    cache = load_cache()
    ours  = load_recon()
    print(f"[cache] {len(cache)} SGS validos", flush=True)
    print(f"[recon] {len(ours)} categorias", flush=True)

    results = {}
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("cat,sgs,n,ini,fim,corr,mean_abs,max_abs,bias,tag\n")
        for cat in sorted(ours.keys()):
            our_d = ours[cat]
            if len(our_d) < 24: continue
            scored = []
            for sgs, their_d in cache.items():
                s = score(our_d, their_d)
                if s is None: continue
                scored.append((sgs, s))
            scored.sort(key=lambda x: (-x[1]["corr"], x[1]["mean_abs"]))
            top = scored[:5]
            for sgs, s in top:
                tag = ""
                if s["corr"] > 0.99 and s["mean_abs"] < 0.05: tag = "MATCH"
                elif s["corr"] > 0.95: tag = "PROX"
                f.write(f"{cat},{sgs},{s['n']},{s['ini']},{s['fim']},"
                        f"{s['corr']:.5f},{s['mean_abs']:.5f},"
                        f"{s['max_abs']:.5f},{s['bias']:+.5f},{tag}\n")
            if top:
                sgs, s = top[0]
                results[cat] = (sgs, s)
                tag = ""
                if s["corr"] > 0.99 and s["mean_abs"] < 0.05: tag = " <-- MATCH"
                elif s["corr"] > 0.95: tag = " <-- prox"
                print(f"  {cat:20s} SGS {sgs:5d}  corr={s['corr']:+.4f}  "
                      f"mean|d|={s['mean_abs']:.4f}  n={s['n']:3d}{tag}",
                      flush=True)
            else:
                print(f"  {cat:20s} SEM CANDIDATO", flush=True)

    print(f"\n[out] {OUT}", flush=True)
    print("\n===== MATCH (corr>0.99 & mean|d|<0.05pp) =====")
    for cat, (sgs, s) in sorted(results.items()):
        if s["corr"] > 0.99 and s["mean_abs"] < 0.05:
            print(f"  {cat:20s} = {sgs}   corr={s['corr']:.4f}  mean|d|={s['mean_abs']:.4f}")
    print("\n===== PROX (0.90 < corr < 0.99) =====")
    for cat, (sgs, s) in sorted(results.items()):
        if 0.90 < s["corr"] <= 0.99:
            print(f"  {cat:20s} ~ {sgs}   corr={s['corr']:.4f}  mean|d|={s['mean_abs']:.4f}")
    print("\n===== SEM MATCH FORTE =====")
    for cat, (sgs, s) in sorted(results.items()):
        if s["corr"] <= 0.90:
            print(f"  {cat:20s} (best={sgs} corr={s['corr']:.4f})")

if __name__ == "__main__":
    main()
