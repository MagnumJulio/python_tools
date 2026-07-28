#!/usr/bin/env python3
# _probe_sgs_ipca15.py — sonda sistematica de SGS BCB pra IPCA-15.
#
# Estratégia: pra cada categoria (headline + 26 breakdowns), fetcha nossa
# recon IBGE (ipca15_pareto_recon.csv) e testa uma bateria de SGS candidatos
# via BCB API. Ranqueia por (corr, -mean|d|). Reporta best match por cat.
#
# Ranges baseados em: SGS IPCA cheio conhecidos + blocos adjacentes (BCB
# geralmente numera IPCA cheio + IPCA-15 em ranges próximos).

import csv, json, os, sys, time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

ROOT = os.path.dirname(os.path.abspath(__file__))
RECON = os.path.join(ROOT, "data", "ipca15_pareto_recon.csv")
OUT   = os.path.join(ROOT, "_probe_sgs_ipca15.out")

def fetch(sgs, retries=2):
    url = f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.{sgs}/dados?formato=json"
    for a in range(retries + 1):
        try:
            req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urlopen(req, timeout=30) as r:
                if r.status != 200:
                    return None
                txt = r.read().decode("utf-8")
                if not txt or txt[0] != "[":
                    return None
                data = json.loads(txt)
                if not data:
                    return None
                out = {}
                for d in data:
                    try:
                        dd = d["data"]
                        dt = f"{dd[6:10]}-{dd[3:5]}-{dd[0:2]}"
                        vv = float(d["valor"])
                        out[dt] = vv
                    except (KeyError, ValueError):
                        continue
                return out
        except (HTTPError, URLError, TimeoutError):
            if a < retries:
                time.sleep(1 + a)
            continue
        except Exception:
            return None
    return None

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
    mean_a = sum(a) / n
    mean_b = sum(b) / n
    var_a = sum((x - mean_a) ** 2 for x in a) / n
    var_b = sum((x - mean_b) ** 2 for x in b) / n
    if var_a < 1e-12 or var_b < 1e-12:
        return None
    cov = sum((a[i] - mean_a) * (b[i] - mean_b) for i in range(n)) / n
    corr = cov / (var_a ** 0.5 * var_b ** 0.5)
    diffs = [a[i] - b[i] for i in range(n)]
    mean_abs = sum(abs(d) for d in diffs) / n
    max_abs = max(abs(d) for d in diffs)
    bias = sum(diffs) / n
    return dict(n=n, ini=keys[0][:7], fim=keys[-1][:7],
                corr=corr, mean_abs=mean_abs, max_abs=max_abs, bias=bias)

# Candidatos por categoria. Estratégia:
# - Ranges já sabidos onde ficam séries IPCA-15 (7477-7484, 27860-27920).
# - Adjacentes aos IPCA cheio conhecidos (+/-1, +/-2).
# - Blocos NT_57 novos (28700-28800, 29680-29690).
BROAD_SCAN = list(range(27800, 27930)) + list(range(28700, 28800)) + \
             list(range(11420, 11440)) + list(range(16118, 16135)) + \
             list(range(29680, 29700)) + list(range(4440, 4510)) + \
             list(range(10840, 10850)) + list(range(21376, 21385)) + \
             [7478, 7477, 7479, 7480, 7481, 7482, 7483, 7484,
              1635, 1636, 1637, 1638, 1639, 1640]

def main():
    if not os.path.exists(RECON):
        print(f"ERR: recon nao encontrado: {RECON}", file=sys.stderr)
        sys.exit(1)
    ours = load_recon()

    cats_to_test = sorted(ours.keys())
    print(f"[cfg] cats={len(cats_to_test)} candidatos={len(BROAD_SCAN)}", flush=True)

    # Baixa todos os SGS candidatos com pool concorrente (I/O-bound; BCB
    # aguenta ~16 conexoes simultaneas sem 429).
    cache = {}
    uniq = list(dict.fromkeys(BROAD_SCAN))
    done = 0
    with ThreadPoolExecutor(max_workers=16) as ex:
        futs = {ex.submit(fetch, s): s for s in uniq}
        for fut in as_completed(futs):
            s = futs[fut]
            try:
                cache[s] = fut.result()
            except Exception:
                cache[s] = None
            done += 1
            if done % 30 == 0:
                print(f"  [fetch {done}/{len(uniq)}]", flush=True)

    valid = {s: d for s, d in cache.items() if d and len(d) >= 24}
    print(f"[cfg] SGS validos (>=24 obs): {len(valid)}", flush=True)

    results = {}
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("cat,sgs,n,ini,fim,corr,mean_abs,max_abs,bias,tag\n")
        for cat in cats_to_test:
            our_d = ours[cat]
            if len(our_d) < 24:
                continue
            scored = []
            for sgs, their_d in valid.items():
                s = score(our_d, their_d)
                if s is None: continue
                scored.append((sgs, s))
            # Sort by corr desc, then mean_abs asc.
            scored.sort(key=lambda x: (-x[1]["corr"], x[1]["mean_abs"]))
            top = scored[:5]
            best = scored[0] if scored else None
            for sgs, s in top:
                tag = ""
                if s["corr"] > 0.99 and s["mean_abs"] < 0.05: tag = "MATCH"
                elif s["corr"] > 0.95: tag = "PROX"
                f.write(f"{cat},{sgs},{s['n']},{s['ini']},{s['fim']},"
                        f"{s['corr']:.5f},{s['mean_abs']:.5f},"
                        f"{s['max_abs']:.5f},{s['bias']:+.5f},{tag}\n")
            if best:
                results[cat] = best
                sgs, s = best
                tag = ""
                if s["corr"] > 0.99 and s["mean_abs"] < 0.05: tag = " <-- MATCH"
                elif s["corr"] > 0.95: tag = " <-- prox"
                print(f"  {cat:20s} SGS {sgs:5d}  corr={s['corr']:.4f}  "
                      f"mean|d|={s['mean_abs']:.4f}  n={s['n']:3d}{tag}",
                      flush=True)
            else:
                print(f"  {cat:20s} SEM CANDIDATO", flush=True)

    print(f"\n[out] {OUT}", flush=True)
    print("\n===== RESUMO (só MATCH corr>0.99 mean|d|<0.05pp) =====")
    for cat, (sgs, s) in sorted(results.items()):
        if s["corr"] > 0.99 and s["mean_abs"] < 0.05:
            print(f"  {cat:20s} = {sgs}   corr={s['corr']:.4f}  mean|d|={s['mean_abs']:.4f}")

if __name__ == "__main__":
    main()
