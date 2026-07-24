#!/usr/bin/env python3
# Por que: fetch batched dos indices CUUR<code> das folhas subitem-level da
# hierarquia BLS Table 1 (2020+). NSA-only — BLS nao publica SA a nivel
# subitem (X-13 tem que rodar no corp via opt_utils).
#
# Input: data/cpi_cpius_subitem_hierarchy.csv
# Output: data/cpi_cpius_recon_subitem_raw.csv (long: date, item_code, cpi_u)
import csv
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IN_CSV = ROOT / "data" / "cpi_cpius_subitem_hierarchy.csv"
OUT_CSV = ROOT / "data" / "cpi_cpius_recon_subitem_raw.csv"

BLS_API_URL = "https://api.bls.gov/publicAPI/v2/timeseries/data/"
START_YEAR = 2019   # precisa Dec/2019 como anchor pro Laspeyres Dez
END_YEAR = 2026


def fetch_batched(series_ids, start_year, end_year, api_key=None):
    max_per_batch = 50 if api_key else 25
    max_years = 20 if api_key else 10

    windows = []
    y0 = start_year
    while y0 <= end_year:
        y1 = min(y0 + max_years - 1, end_year)
        windows.append((y0, y1))
        y0 = y1 + 1

    print(f"[fetch] {len(series_ids)} series x {len(windows)} janela(s) x batches de {max_per_batch}")
    print(f"        (API key {'ON' if api_key else 'OFF'})")

    accum = {sid: {} for sid in series_ids}
    total = len(windows) * ((len(series_ids) + max_per_batch - 1) // max_per_batch)
    b_ix = 0
    for (yw0, yw1) in windows:
        for i in range(0, len(series_ids), max_per_batch):
            b_ix += 1
            batch = series_ids[i:i + max_per_batch]
            payload = {
                "seriesid": batch,
                "startyear": str(yw0),
                "endyear": str(yw1),
            }
            if api_key:
                payload["registrationkey"] = api_key
            t_req = time.monotonic()
            print(f"  batch {b_ix}/{total} [{yw0}-{yw1}] POST {len(batch)} ids...", end=" ", flush=True)
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                BLS_API_URL, data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=120) as r:
                j = json.loads(r.read().decode("utf-8"))
            if j.get("status") != "REQUEST_SUCCEEDED":
                raise RuntimeError(f"[BLS] {j.get('status')}: {j.get('message')}")
            n_new = 0
            n_empty = 0
            for s in j["Results"]["series"]:
                sid = s["seriesID"]
                if not s["data"]:
                    n_empty += 1
                    continue
                for pt in s["data"]:
                    if pt["period"] == "M13":
                        continue
                    y = int(pt["year"])
                    m = int(pt["period"][1:])
                    try:
                        accum[sid][(y, m)] = float(pt["value"])
                        n_new += 1
                    except (ValueError, TypeError):
                        continue
            print(f"done in {time.monotonic()-t_req:.1f}s (+{n_new} obs, {n_empty} empty)")

    return accum


def load_leaves():
    leaves = set()
    for r in csv.DictReader(open(IN_CSV, encoding="utf-8")):
        if r["is_leaf"] == "1":
            leaves.add(r["item_code"])
    return sorted(leaves)


def main():
    api_key = os.environ.get("BLS_API_KEY", "").strip() or None

    leaves = load_leaves()
    print(f"[input] {len(leaves)} folhas subitem")

    series_ids = [f"CUUR0000{code}" for code in leaves]
    accum = fetch_batched(series_ids, START_YEAR, END_YEAR, api_key)

    # Emite long CSV
    rows = []
    empty_sids = []
    for sid, obs in accum.items():
        if not obs:
            empty_sids.append(sid)
            continue
        code = sid[len("CUUR0000"):]
        for (y, m), v in sorted(obs.items()):
            rows.append({
                "date": f"{y:04d}-{m:02d}-01",
                "item_code": code,
                "cpi_u_nsa": v,
            })

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["date", "item_code", "cpi_u_nsa"])
        w.writeheader()
        w.writerows(rows)

    codes_with_data = len(accum) - len(empty_sids)
    print(f"\n[out] {OUT_CSV}: {len(rows)} linhas ({codes_with_data}/{len(series_ids)} codes com dados)")
    if empty_sids:
        print(f"[WARN] sem dados: {len(empty_sids)} series (primeiras 10: {empty_sids[:10]})")


if __name__ == "__main__":
    main()
