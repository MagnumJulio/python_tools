#!/usr/bin/env python3
# Por que: valida recon bottom-up vs CUUR<agg> publicado pelo BLS.
# Pra cada categoria reconstruida, calcula mean|d|(var_mm).
import csv
import json
import os
import time
import urllib.request
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).resolve().parents[1]
RECON_CSV = ROOT / "data" / "cpi_cpius_recon_bottomup.csv"
MAP_CSV = ROOT / "scripts" / "bls_maps" / "cpiu_table_1.csv"

BLS_API_URL = "https://api.bls.gov/publicAPI/v2/timeseries/data/"


def fetch_bls(series_ids, start_year=2019, end_year=2026, api_key=None):
    max_per_batch = 50 if api_key else 25
    accum = {sid: {} for sid in series_ids}
    for i in range(0, len(series_ids), max_per_batch):
        batch = series_ids[i:i+max_per_batch]
        payload = {"seriesid": batch, "startyear": str(start_year), "endyear": str(end_year)}
        if api_key:
            payload["registrationkey"] = api_key
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(BLS_API_URL, data=data,
            headers={"Content-Type": "application/json"}, method="POST")
        t0 = time.monotonic()
        with urllib.request.urlopen(req, timeout=120) as r:
            j = json.loads(r.read().decode("utf-8"))
        if j.get("status") != "REQUEST_SUCCEEDED":
            raise RuntimeError(f"[BLS] {j.get('status')}: {j.get('message')}")
        for s in j["Results"]["series"]:
            sid = s["seriesID"]
            for pt in s["data"]:
                if pt["period"] == "M13":
                    continue
                y = int(pt["year"]); m = int(pt["period"][1:])
                try:
                    accum[sid][(y, m)] = float(pt["value"])
                except (ValueError, TypeError):
                    continue
        print(f"  batch {i//max_per_batch+1}: {len(batch)} ids in {time.monotonic()-t0:.1f}s")
    return accum


def main():
    # Load recon
    recon_by_cat = defaultdict(dict)  # cat -> {(y,m): index}
    for r in csv.DictReader(open(RECON_CSV, encoding="utf-8")):
        y, mo, _ = r["date"].split("-")
        recon_by_cat[r["category_code"]][(int(y), int(mo))] = float(r["index_nsa"])

    # Load cat -> item_code
    cats = {r["category_code"]: r["item_code"] for r in csv.DictReader(open(MAP_CSV, encoding="utf-8"))}

    # Fetch published aggregates for cats we reconstructed
    to_fetch = [cats[c] for c in recon_by_cat.keys() if c in cats]
    print(f"[fetch] {len(to_fetch)} agregados CUUR")
    api_key = os.environ.get("BLS_API_KEY", "").strip() or None
    series_ids = [f"CUUR0000{ic}" for ic in to_fetch]
    published = fetch_bls(series_ids, api_key=api_key)

    # Compare var_mm
    print(f"\n{'cat':<25} {'nobs':>5} {'mean|d_mm|':>11} {'max|d_mm|':>10} {'mean|d_yoy|':>12}")
    print("-" * 68)
    results = []
    for cat, item_code in cats.items():
        if cat not in recon_by_cat:
            continue
        sid = f"CUUR0000{item_code}"
        pub = published.get(sid, {})
        rec = recon_by_cat[cat]
        common_months = sorted(set(rec.keys()) & set(pub.keys()))
        if len(common_months) < 12:
            continue
        # var_mm
        diffs_mm = []
        for i, m in enumerate(common_months):
            if i == 0: continue
            prev = common_months[i-1]
            r_var = (rec[m] / rec[prev] - 1) * 100 if rec[prev] else None
            p_var = (pub[m] / pub[prev] - 1) * 100 if pub[prev] else None
            if r_var is None or p_var is None: continue
            diffs_mm.append(abs(r_var - p_var))
        # var_yoy
        diffs_yoy = []
        for m in common_months:
            y, mo = m
            m_lag = (y-1, mo)
            if m_lag in rec and m_lag in pub and rec[m_lag] and pub[m_lag]:
                r_yoy = (rec[m] / rec[m_lag] - 1) * 100
                p_yoy = (pub[m] / pub[m_lag] - 1) * 100
                diffs_yoy.append(abs(r_yoy - p_yoy))
        mean_mm = sum(diffs_mm)/len(diffs_mm) if diffs_mm else 0
        max_mm = max(diffs_mm) if diffs_mm else 0
        mean_yoy = sum(diffs_yoy)/len(diffs_yoy) if diffs_yoy else 0
        results.append((cat, len(diffs_mm), mean_mm, max_mm, mean_yoy))

    results.sort(key=lambda x: -x[2])  # ordena por pior mean|d_mm|
    for r in results:
        print(f"{r[0]:<25} {r[1]:>5} {r[2]:>11.4f} {r[3]:>10.4f} {r[4]:>12.4f}")


if __name__ == "__main__":
    main()
