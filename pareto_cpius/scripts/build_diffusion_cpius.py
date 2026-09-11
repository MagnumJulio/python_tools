#!/usr/bin/env python
# build_diffusion_cpius.py
# Analogo do pareto_pce/scripts/build_diffusion.py, mas pra CPI-U (BLS).
#
# Fetch item-level (177 leaves na hierarquia CPI-U 2025) via BLS API v2.
# Classifica cada leaf em Goods vs Services baseado em prefixo BLS (SE**).
# Flag Cars pros items de motor vehicles (SETA01, SETA02, SETC01, SETC02).
# Calcula share of items com YoY > 3% pros 4 agregados:
#   Headline (yoy + 6ma_ann), Goods (yoy), Services (yoy), Goods_ex_cars (yoy)
#
# BLS API: v2 aceita chave opcional (env BLS_API_KEY). Sem chave, limite 25
# series/request. Com chave, 50 series/request e 500 requests/dia.
#
# Uso:
#   cd pareto_cpius
#   python scripts/build_diffusion_cpius.py

import json
import os
import sys
import time
import urllib.request
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent

# --- Proxy corp ---
# 1. Se `scripts/proxy_config.py` existe, sourceia (le proxy_config.R).
# 2. Le env vars HTTPS_PROXY / HTTP_PROXY (setadas pelo user OU pelo step 1).
# 3. Instala ProxyHandler + ProxyBasicAuthHandler EXPLICITAMENTE — mais
#    robusto que deixar urllib inferir (evita 407 quando parsing de user:pass@
#    no URL nao passa auth pro proxy).
_PROXY_CFG = ROOT / "scripts" / "proxy_config.py"
if _PROXY_CFG.exists():
    exec(_PROXY_CFG.read_text(encoding="utf-8"),
         {"os": os, "__file__": str(_PROXY_CFG)})


def _install_proxy_handler():
    """Le HTTPS_PROXY / HTTP_PROXY do env e instala handlers urllib explicitos.
    Se URL tem user:pass@ embutido, extrai e configura ProxyBasicAuthHandler
    (Basic auth) alem do ProxyHandler."""
    https_url = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    http_url  = os.environ.get("HTTP_PROXY")  or os.environ.get("http_proxy")
    if not (https_url or http_url):
        return  # sem proxy

    def _parse(u):
        if not u:
            return None
        p = urlparse(u)
        bare = f"{p.scheme}://{p.hostname}:{p.port}"
        return bare, p.username, p.password

    proxies = {}
    creds = []
    for scheme, u in [("https", https_url), ("http", http_url)]:
        parsed = _parse(u)
        if parsed:
            bare, user, pw = parsed
            proxies[scheme] = bare
            if user and pw:
                creds.append((bare, user, pw))

    handlers = [urllib.request.ProxyHandler(proxies)]
    if creds:
        pwmgr = urllib.request.HTTPPasswordMgrWithDefaultRealm()
        for bare, user, pw in creds:
            pwmgr.add_password(None, bare, user, pw)
        handlers.append(urllib.request.ProxyBasicAuthHandler(pwmgr))

    opener = urllib.request.build_opener(*handlers)
    urllib.request.install_opener(opener)
    print(f"[PROXY] handler explicito instalado: {list(proxies.keys())} "
          f"({len(creds)} com auth)")


_install_proxy_handler()

HIER_CSV = ROOT / "data" / "cpi_cpius_subitem_hierarchy.csv"
RAW_OUT = ROOT / "data" / "cpiu_item_level_raw.csv"
DIFF_OUT = ROOT / "data" / "cpiu_diffusion.csv"
LEAVES_OUT = ROOT / "data" / "cpiu_leaves_detected.csv"

BLS_URL = "https://api.bls.gov/publicAPI/v2/timeseries/data/"
BLS_KEY = os.environ.get("BLS_API_KEY", "")
BATCH = 50 if BLS_KEY else 25
YEAR_STRIDE = 20  # BLS v2 aceita ate 20 anos por request

# Regras de classificacao Goods vs Services baseadas em prefixo 4-char BLS.
# Refs: BLS CPI hierarchy (SAC = Commodities, SAS = Services). Onde subcat
# eh mista, usa-se sub-prefixo 4-char pra desambiguar.
SERVICES_PREFIXES = {
    # Housing services
    "SEHA",  # Rent of primary residence
    "SEHB",  # Lodging away from home
    "SEHC",  # Owners' equivalent rent (OER)
    "SEHD",  # Tenants' and household insurance
    "SEHF",  # Utilities: electricity, natural gas (services)
    "SEHG",  # Water and sewer and trash collection services
    "SEHP",  # Household services (domestic, gardening, moving, repair)
    # Medical services (SEMF eh drugs = Goods; SEME = health insurance handled by item)
    "SEMC",  # Professional medical services
    "SEMD",  # Hospital and nursing home services
    # Transportation services
    "SETD",  # Vehicle maintenance and repair
    "SETE",  # Motor vehicle insurance
    "SETF",  # Motor vehicle fees
    "SETG",  # Public transportation (airfares, intercity, intracity)
    # Communication / education services
    "SEEB",  # Tuition, K-12, day care
    "SEEC",  # Postage and delivery
    "SEED",  # Telephone services
    # Food away from home
    "SEFV",
    # Personal services
    "SEGC",  # Personal care services (haircuts)
    "SEGD",  # Legal, funeral, laundry, financial services
}

# Explicitly Services items que nao seguem prefix rule (mixed categories):
SERVICES_ITEMS = {
    # Vehicle rental/leasing (SETA is mostly Goods, but 03/04 are services)
    "SETA03",  # Leased cars and trucks
    "SETA04",  # Car and truck rental
    # Recreation subscriptions/services embedded em SERA (mostly Goods)
    "SERA02",  # Cable, satellite, streaming TV
    "SERA04",  # Purchase, subscription, and rental of video
    "SERA06",  # Recorded music and music subscriptions
    # Pet services (SERB01 is Goods pets, SERB02 is Services)
    "SERB02",  # Pet services incl veterinary
    # Photographers (SERD01 goods, SERD02 services)
    "SERD02",  # Photographers and photo processing
    # Club/admissions/lessons (SERF*)
    "SERF01", "SERF02", "SERF03",
    # Internet services (SEEE is mixed - most Goods, this one Service)
    "SEEE03",  # Internet services
    # Health insurance
    "SEME",
}

# Cars (motor vehicles Goods) — flag pra "Goods ex cars"
CAR_ITEMS = {
    "SETA01",  # New vehicles
    "SETA02",  # Used cars and trucks
    "SETC01",  # Tires
    "SETC02",  # Vehicle accessories other than tires
}


def is_service(item_code: str) -> bool:
    if item_code in SERVICES_ITEMS:
        return True
    return item_code[:4] in SERVICES_PREFIXES


def is_car(item_code: str) -> bool:
    return item_code in CAR_ITEMS


def load_leaves() -> pd.DataFrame:
    if not HIER_CSV.exists():
        sys.exit(
            f"[FAIL] {HIER_CSV} nao existe.\n"
            f"Rode a cadeia de bootstrap primeiro (uma vez / anualmente):\n"
            f"  python scripts/parse_historical_ri_subitem.py    # RI subitem parse\n"
            f"  python scripts/build_subitem_hierarchy.py        # hierarquia\n"
            f"Depois pode rodar build_diffusion_cpius.py."
        )
    h = pd.read_csv(HIER_CSV)
    y = h.year.max()
    h = h[(h.year == y) & (h.is_leaf == 1)].copy()
    h["aggregate"] = h.item_code.apply(lambda c: "Services" if is_service(c) else "Goods")
    h["is_car"] = h.item_code.apply(is_car)
    # is_car so vale pra Goods
    h.loc[h["aggregate"] != "Goods", "is_car"] = False
    return h[["item_code", "item_name", "aggregate", "is_car"]].reset_index(drop=True)


def bls_fetch_batch(series_ids: list[str], start_year: int, end_year: int) -> list[dict]:
    payload = {
        "seriesid": series_ids,
        "startyear": str(start_year),
        "endyear": str(end_year),
    }
    if BLS_KEY:
        payload["registrationkey"] = BLS_KEY
    body = json.dumps(payload).encode("utf-8")
    req = Request(BLS_URL, data=body, headers={"Content-Type": "application/json"})
    try:
        with urlopen(req, timeout=120) as r:
            j = json.loads(r.read())
    except URLError as e:
        msg = str(e)
        if "407" in msg or "authentication" in msg.lower():
            sys.exit(
                f"[FAIL] BLS API bloqueada por proxy corp (HTTP 407).\n"
                f"  Soluções (uma das duas):\n"
                f"  1) Set env vars com auth do proxy corp:\n"
                f"     $env:HTTPS_PROXY = 'http://<user>:<pass>@<proxy>:<port>'\n"
                f"     $env:HTTP_PROXY  = 'http://<user>:<pass>@<proxy>:<port>'\n"
                f"  2) Criar {ROOT}/scripts/proxy_config.py com:\n"
                f"     os.environ['HTTPS_PROXY'] = 'http://user:pass@proxy:port'\n"
                f"     os.environ['HTTP_PROXY']  = 'http://user:pass@proxy:port'\n"
                f"  (mesmo padrão do fetch_bls_cpiu.R via scripts/proxy_config.R)"
            )
        raise
    if j.get("status") != "REQUEST_SUCCEEDED":
        raise RuntimeError(f"BLS API erro: {j.get('message', j)}")
    return j["Results"]["series"]


def fetch_all(item_codes: list[str], year_range: tuple[int, int]) -> pd.DataFrame:
    series_ids = [f"CUUR0000{c}" for c in item_codes]
    windows = []
    y0, y1 = year_range
    while y0 <= y1:
        yend = min(y0 + YEAR_STRIDE - 1, y1)
        windows.append((y0, yend))
        y0 = yend + 1

    all_rows: list[dict] = []
    for w0, w1 in windows:
        print(f"[fetch] window {w0}-{w1}...")
        for i in range(0, len(series_ids), BATCH):
            batch = series_ids[i:i + BATCH]
            print(f"  batch {i//BATCH + 1}/{(len(series_ids)-1)//BATCH + 1}"
                  f" ({len(batch)} series)...", flush=True)
            series_result = bls_fetch_batch(batch, w0, w1)
            for s in series_result:
                sid = s["seriesID"]
                item = sid[8:]  # strip CUUR0000
                for d in s.get("data", []):
                    if not d.get("period", "").startswith("M"):
                        continue
                    month = int(d["period"][1:])
                    if month > 12:  # skip M13 (annual)
                        continue
                    year = int(d["year"])
                    val = d.get("value", "")
                    try:
                        v = float(val)
                    except ValueError:
                        continue
                    all_rows.append({
                        "date": pd.Timestamp(year=year, month=month, day=1),
                        "item_code": item,
                        "value": v,
                    })
            time.sleep(0.5)  # cortesia
    return pd.DataFrame(all_rows).sort_values(["item_code", "date"]).reset_index(drop=True)


def compute_diffusion(df: pd.DataFrame, leaves: pd.DataFrame) -> pd.DataFrame:
    lm = df.merge(leaves[["item_code", "aggregate", "is_car"]], on="item_code")
    lm = lm.sort_values(["item_code", "date"])

    lm["yoy"] = lm.groupby("item_code")["value"].pct_change(12) * 100
    m6 = lm.groupby("item_code")["value"].pct_change(6)
    lm["m6_ann"] = ((1 + m6) ** 2 - 1) * 100

    def diffusion(rows: pd.DataFrame, col: str) -> pd.Series:
        return rows.groupby("date").apply(
            lambda g: (g[col] > 3).sum() / g[col].notna().sum() * 100
            if g[col].notna().any() else float("nan"),
            include_groups=False,
        )

    out_rows = []

    def add(rows, col, agg, metric):
        s = diffusion(rows, col).rename("value").reset_index()
        s["aggregate"] = agg
        s["metric"] = metric
        out_rows.append(s)

    add(lm, "yoy", "Headline", "diffusion_yoy_3pct")
    add(lm, "m6_ann", "Headline", "diffusion_6ma_ann_3pct")
    add(lm[lm["aggregate"] == "Goods"], "yoy", "Goods", "diffusion_yoy_3pct")
    add(lm[lm["aggregate"] == "Services"], "yoy", "Services", "diffusion_yoy_3pct")
    add(lm[(lm["aggregate"] == "Goods") & (~lm.is_car)], "yoy", "Goods_ex_cars",
        "diffusion_yoy_3pct")

    out = pd.concat(out_rows, ignore_index=True)[
        ["date", "aggregate", "metric", "value"]
    ]
    return out.sort_values(["metric", "aggregate", "date"]).reset_index(drop=True)


def main():
    print("[1] Classificando leaves CPI-U...")
    leaves = load_leaves()
    n_g = int((leaves["aggregate"] == "Goods").sum())
    n_s = int((leaves["aggregate"] == "Services").sum())
    n_car = int(leaves.is_car.sum())
    print(f"  Goods={n_g}, Services={n_s}, Total={n_g + n_s}, Cars={n_car}")
    leaves.to_csv(LEAVES_OUT, index=False)
    print(f"  [OK] leaves gravados em {LEAVES_OUT.relative_to(ROOT)}")

    print(f"\n[2] Fetching BLS item-level data (2001-2026)...")
    print(f"  API key: {'sim (batch 50)' if BLS_KEY else 'nao (batch 25)'}")
    df = fetch_all(leaves.item_code.tolist(), (2001, 2026))
    df.to_csv(RAW_OUT, index=False)
    print(f"  [OK] {len(df)} rows em {RAW_OUT.relative_to(ROOT)}")

    print(f"\n[3] Computando difusao...")
    out = compute_diffusion(df, leaves)
    out.to_csv(DIFF_OUT, index=False)
    print(f"  [OK] {len(out)} rows em {DIFF_OUT.relative_to(ROOT)}")

    print(f"\n[preview] Ultimos 3 meses:")
    for m in out.metric.unique():
        sub = out[out.metric == m].sort_values("date").tail(6)
        pv = sub.pivot(index="date", columns="aggregate", values="value")
        print(f"\n== {m} ==")
        print(pv.tail(3).round(2).to_string())


if __name__ == "__main__":
    main()
