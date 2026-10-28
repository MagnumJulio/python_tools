#!/usr/bin/env python3
# build_alt_measures_cpi.py
#
# Medidas alternativas de inflacao CPI-U pra servir no SQL corp.
#
# Estrategia primaria: fetch das series OFICIAIS (match 100% com Fed):
#   - Cleveland Fed Median CPI       (FRED: MEDCPIM158SFRBCLE)
#   - Cleveland Fed Trimmed-Mean CPI (FRED: TRMMEANCPIM158SFRBCLE)
#   - Atlanta Fed Sticky-Price CPI family (xlsx oficial, 6 series)
#
# Custom (bottom-up proprio, nao existe oficial):
#   - Trimmed Symmetric 25% CPI (corta 25% top + 25% cauda, mean do miolo 50%)
#
# Infra bottom-up (fetch SA/NSA leaves + STL + weighted median/trimmed)
# fica como RECONSTRUCAO DEFENSIVA — util pra validar FRED e pra servir se
# FRED cair, mas nao e a serie primaria entregue ao gestor.
#
# Uso:
#   cd pareto_cpius
#   python scripts/build_alt_measures_cpi.py
#
# Env vars:
#   BLS_API_KEY (so pra o custom bottom-up)
#   CORP_PROXY_URL (opcional — corp only)
#   SKIP_CUSTOM=1 (so entrega as 8 oficiais, pula Trimmed Sym 25%)

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import time
from datetime import date
from pathlib import Path
from urllib.request import Request, urlopen

import numpy as np
import pandas as pd

# TTL default pros caches Fed-source (xlsx/csv pequenos, re-fetch barato).
# Evita o bug "if not path.exists(): download" que travou alt_measures em
# agosto depois do Atlanta/Cleveland terem publicado setembro.
CACHE_TTL_HOURS = int(os.environ.get("CACHE_TTL_HOURS", "24"))


def _cache_fresh(path: Path, ttl_hours: int = CACHE_TTL_HOURS) -> bool:
    """True se arquivo existe E foi atualizado nas ultimas ttl_hours."""
    if not path.exists():
        return False
    age_h = (time.time() - path.stat().st_mtime) / 3600
    return age_h < ttl_hours

ROOT = Path(__file__).resolve().parent.parent
HIER_CSV = ROOT / "data" / "cpi_cpius_subitem_hierarchy.csv"
PESOS_CSV = ROOT / "data" / "cpi_cpius_pesos_annual_subitem.csv"
# Cache isolado: 70 indent-3 nodes do Trim25 custom. Antes era
# cpi_cpius_subitem_sa_raw.csv (compartilhado com build_breadth_cpi.py,
# 177 leaves) — overwrite destruiu os 107 extras do breadth. Separado em
# 2026-10-22.
RAW_OUT = ROOT / "data" / "cpi_cpius_subitem_alt_raw.csv"
OUT_DIR = ROOT / "data"
ATLANTA_XLSX = ROOT / "data" / "raw" / "atlanta" / "stickyprice.xlsx"
OUT_CSV = OUT_DIR / "cpi_cpius_alt_measures.csv"

# Universo esperado — se vier menos que isso, o guard em main() preserva o
# CSV existente em vez de sobrescrever com dado parcial (caso proxy falhe
# em algumas fontes). `SKIP_CUSTOM=1` tira o custom do conjunto esperado.
EXPECTED_MEASURES = {
    "median_cpi", "trimmed_mean_16_cpi",           # Cleveland FRED
    "flexible_cpi", "core_flexible_cpi",           # Atlanta xlsx
    "sticky_cpi", "core_sticky_cpi",
    "sticky_cpi_ex_shelter", "core_sticky_cpi_ex_shelter",
    "trimmed_sym_25_cpi_custom",                   # custom bottom-up BLS
}

BLS_URL = "https://api.bls.gov/publicAPI/v2/timeseries/data/"
BLS_KEY = os.environ.get("BLS_API_KEY", "")
BATCH = 50 if BLS_KEY else 25
YEAR_STRIDE = 20
START_YEAR = 2000

# Proxy: respeita HTTP_PROXY/HTTPS_PROXY do ambiente corp (ja setados).
# CORP_PROXY_URL fica como override opcional. Shell-out curl pq urllib tem
# bug conhecido no CONNECT-auth (407) com proxy Basic-auth do Itau.
_PROXY_URL = (
    os.environ.get("CORP_PROXY_URL")
    or os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    or os.environ.get("HTTP_PROXY")  or os.environ.get("http_proxy")
    or None
)
# Mascara credencial pra log: user:pass@host -> user:***@host
def _mask_proxy(u):
    if not u: return "(none — direct)"
    import re
    return re.sub(r":([^@/]+)@", ":***@", u)
print(f"[proxy] _PROXY_URL = {_mask_proxy(_PROXY_URL)}", flush=True)


def _curl_get(url: str, timeout: int = 60, retries: int = 3) -> bytes:
    """GET com curl (-L follow redirects). Retry em erro de rede. Robusto
    pra FRED que ocasionalmente timeout no urlopen do Python."""
    last_err = None
    for attempt in range(1, retries + 1):
        cmd = ["curl", "-sL", "-f", "--max-time", str(timeout),
               "-A", "Mozilla/5.0"]
        if _PROXY_URL: cmd += ["-x", _PROXY_URL]
        cmd.append(url)
        try:
            r = subprocess.run(cmd, capture_output=True, timeout=timeout + 10)
        except subprocess.TimeoutExpired as e:
            last_err = f"curl subprocess timeout attempt {attempt}"
            continue
        if r.returncode == 0:
            return r.stdout
        last_err = f"curl rc={r.returncode} attempt {attempt}: {r.stderr.decode()[:200]}"
    raise RuntimeError(last_err)


def fetch_fred_csv(fred_id: str) -> pd.Series:
    """FRED CSV publico. Sem key. Usa requests em vez de curl: no corp
    Itau o curl via proxy Basic-auth dava timeout (rc=28) ou SSL (rc=56)
    intermitente, requests respeita trust_env e passa."""
    import requests
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={fred_id}"
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    buf = io.BytesIO(r.content)
    df = pd.read_csv(buf)
    df.columns = ["date", "value"]
    df["date"] = pd.to_datetime(df["date"])
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    return df.set_index("date")["value"].dropna()


def fetch_atlanta_sticky() -> pd.DataFrame:
    """Parse xlsx oficial Atlanta Fed, retorna long df com as 6 series.
    Atlanta NAO publica index level nativo — cada bloco de 4 cols é:
    (MoM decimal, 1-mo annualized %, 3-mo a.r., 12-mo %). O index é
    reconstruido em main() via _chain_index(ann_1mo)."""
    if not _cache_fresh(ATLANTA_XLSX):
        print(f"[atlanta] cache stale/ausente — baixando xlsx oficial...")
        ATLANTA_XLSX.parent.mkdir(parents=True, exist_ok=True)
        url = ("https://www.atlantafed.org/-/media/Project/Atlanta/FRBA/Documents/"
               "datafiles/research/inflationproject/stickprice/stickyprice.xlsx")
        ATLANTA_XLSX.write_bytes(_curl_get(url, timeout=120))

    df = pd.read_excel(ATLANTA_XLSX, sheet_name="Data", header=None)
    SERIES_NAMES = [
        "flexible_cpi",
        "core_flexible_cpi",
        "sticky_cpi",
        "core_sticky_cpi",
        "sticky_cpi_ex_shelter",
        "core_sticky_cpi_ex_shelter",
    ]
    out_rows = []
    for i, name in enumerate(SERIES_NAMES):
        col_1mo  = 1 + i * 4 + 1
        col_12mo = 1 + i * 4 + 3
        s = df.iloc[1:, [0, col_1mo, col_12mo]].copy()
        s.columns = ["date", "ann_1mo", "ann_12mo"]
        s["date"] = pd.to_datetime(s["date"], errors="coerce")
        s = s.dropna(subset=["date"])
        s["ann_1mo"] = pd.to_numeric(s["ann_1mo"], errors="coerce")
        s["ann_12mo"] = pd.to_numeric(s["ann_12mo"], errors="coerce")
        s["measure"] = name
        out_rows.append(s)
    return pd.concat(out_rows, ignore_index=True)


def _chain_index(ann_1mo: pd.Series, base: float = 100.0) -> pd.Series:
    """Converte ann_1mo (% annualized) em indice encadeado.
    idx[0] = base; idx[t] = idx[t-1] * (1 + mom[t]) com
    mom = (1+ann_1mo/100)^(1/12) - 1. NaN em ann_1mo propaga como fator 1."""
    mom = (1 + ann_1mo / 100) ** (1 / 12) - 1
    factor = (1 + mom.fillna(0)).cumprod()
    return base * factor


def _rebase_jan2000(df: pd.DataFrame) -> pd.DataFrame:
    """Rebase value_index pra Jan/2000=100 por measure. Se nao houver obs em
    Jan/2000, usa primeira obs nao-nula como anchor (idx=100 nela)."""
    base_dt = pd.Timestamp("2000-01-01")
    out = []
    for measure, g in df.groupby("measure"):
        g = g.sort_values("date").copy()
        notnull = g.dropna(subset=["value_index"])
        if notnull.empty:
            out.append(g); continue
        hit = notnull[notnull["date"] == base_dt]
        base = float(hit["value_index"].iloc[0]) if not hit.empty else float(notnull["value_index"].iloc[0])
        g["value_index"] = g["value_index"] / base * 100.0
        out.append(g)
    return pd.concat(out, ignore_index=True)


# ----- Custom Trimmed Sym 25% (bottom-up, nao oficial) ----------------------

def _post_bls(payload: dict, timeout: int = 120) -> dict:
    body = json.dumps(payload)
    if _PROXY_URL:
        cmd = ["curl", "-x", _PROXY_URL, "-H", "Content-Type: application/json",
               "-d", body, "-s", "-f", "--max-time", str(timeout), BLS_URL]
        r = subprocess.run(cmd, capture_output=True, timeout=timeout + 10)
        if r.returncode != 0:
            raise RuntimeError(f"curl rc={r.returncode}: {r.stderr.decode()[:300]}")
        return json.loads(r.stdout)
    req = Request(BLS_URL, data=body.encode(), headers={"Content-Type": "application/json"})
    with urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def _fetch_bls(series_ids: list[str], y0: int, y1: int) -> dict[str, pd.Series]:
    payload = {"seriesid": series_ids, "startyear": str(y0), "endyear": str(y1)}
    if BLS_KEY:
        payload["registrationkey"] = BLS_KEY
    data = _post_bls(payload)
    out: dict[str, pd.Series] = {}
    for s in data.get("Results", {}).get("series", []):
        rows = s["data"]
        if not rows:
            out[s["seriesID"]] = pd.Series(dtype=float)
            continue
        d = pd.DataFrame(rows)
        d["date"] = pd.to_datetime(d["year"] + "-" + d["period"].str.replace("M", ""))
        d["value"] = pd.to_numeric(d["value"], errors="coerce")
        out[s["seriesID"]] = d.dropna(subset=["value"]).sort_values("date").set_index("date")["value"]
    return out


def _fetch_leaves(codes: list[str]) -> pd.DataFrame:
    """Fetch SA (CUSR) + fallback NSA (CUUR) pros subitens leaves/indent-3."""
    end_year = date.today().year
    def _batch(ids):
        out = {s: pd.Series(dtype=float) for s in ids}
        for i in range(0, len(ids), BATCH):
            b = ids[i:i + BATCH]
            for y0 in range(START_YEAR, end_year + 1, YEAR_STRIDE):
                y1 = min(y0 + YEAR_STRIDE - 1, end_year)
                try:
                    chunk = _fetch_bls(b, y0, y1)
                except Exception as e:
                    print(f"  [WARN] batch {i//BATCH+1} {y0}-{y1}: {e}")
                    continue
                for sid, s in chunk.items():
                    if s.empty:
                        continue
                    out[sid] = pd.concat([x for x in [out[sid], s] if not x.empty]).sort_index()
                    out[sid] = out[sid][~out[sid].index.duplicated(keep="last")]
        return out

    sa_ids = [f"CUSR0000{c}" for c in codes]
    print(f"[fetch] SA (CUSR): {len(sa_ids)} series...")
    sa = _batch(sa_ids)
    missing = [c for c in codes if sa[f"CUSR0000{c}"].empty]
    print(f"[fetch] SA cobertura: {len(codes)-len(missing)}/{len(codes)}")
    nsa = {}
    if missing:
        print(f"[fetch] NSA fallback (CUUR): {len(missing)}...")
        nsa = _batch([f"CUUR0000{c}" for c in missing])

    rows = []
    for c in codes:
        s = sa[f"CUSR0000{c}"]
        if not s.empty:
            for d, v in s.items():
                rows.append({"date": d, "item_code": c, "sa_flag": "SA", "value_index": v})
        else:
            s = nsa.get(f"CUUR0000{c}", pd.Series(dtype=float))
            for d, v in s.items():
                rows.append({"date": d, "item_code": c, "sa_flag": "NSA", "value_index": v})
    return pd.DataFrame(rows)


def _deseasonalize_nsa(df_idx: pd.DataFrame) -> pd.DataFrame:
    from statsmodels.tsa.seasonal import STL
    out = []
    for code, g in df_idx.groupby("item_code"):
        g = g.sort_values("date").reset_index(drop=True)
        if g["sa_flag"].iloc[0] == "SA" or len(g) < 36:
            out.append(g); continue
        s = pd.Series(g["value_index"].values, index=pd.to_datetime(g["date"]))
        if (s <= 0).any():
            out.append(g); continue
        try:
            res = STL(np.log(s), period=12, robust=True).fit()
            sa = np.exp(res.observed - res.seasonal)
            g2 = g.copy()
            g2["value_index"] = sa.values
            g2["sa_flag"] = "SA_local"
            out.append(g2)
        except Exception:
            out.append(g)
    return pd.concat(out, ignore_index=True)


def compute_custom_trimmed_sym25(hier_year: int = 2025) -> pd.DataFrame:
    """Trimmed symmetric 25% CPI: corta 25% top + 25% cauda por peso
    cumulativo, weighted mean do miolo 50%. Custom (sem FRED benchmark).
    Universe: indent-3 nodes do BLS hierarchy (~70, approx Cleveland
    structure)."""
    hier = pd.read_csv(HIER_CSV)
    pesos = pd.read_csv(PESOS_CSV)

    uni = hier[(hier.year == hier_year) & (hier.indent == 3)]
    codes = sorted(uni.item_code.unique().tolist())
    print(f"[custom] universe indent-3 em {hier_year}: {len(codes)}")

    # Cache guard: so le se arquivo tem conteudo real (nao vazio/corrompido de
    # run anterior falha) E foi atualizado nos ultimos 7 dias. TTL maior que
    # Atlanta/Cleveland porque re-fetch de 70 subitens via BLS leva ~2-3min.
    use_cache = (
        _cache_fresh(RAW_OUT, ttl_hours=24 * 7)
        and RAW_OUT.stat().st_size > 1000      # minimo sanity (header + algumas linhas)
        and os.environ.get("FORCE_FETCH") != "1"
    )
    if use_cache:
        try:
            raw = pd.read_csv(RAW_OUT, parse_dates=["date"])
            if raw.empty or "item_code" not in raw.columns:
                raise ValueError("cache vazio/sem schema esperado")
            print(f"[custom] cache {RAW_OUT.name} ({len(raw)} rows). FORCE_FETCH=1 pra re-baixar")
        except Exception as e:
            print(f"[custom] cache corrompido ({e}) — re-fetch")
            use_cache = False
    if not use_cache:
        raw = _fetch_leaves(codes)
        RAW_OUT.parent.mkdir(parents=True, exist_ok=True)
        raw.to_csv(RAW_OUT, index=False)

    raw = _deseasonalize_nsa(raw)

    df = raw.sort_values(["item_code", "date"]).copy()
    df["mom"] = df.groupby("item_code")["value_index"].pct_change() * 100
    df["ann_mom"] = ((1 + df["mom"] / 100) ** 12 - 1) * 100
    df["year_for_weight"] = df["date"].dt.year - 1
    w = pesos.rename(columns={"year": "year_for_weight", "cpi_u": "weight"})[
        ["year_for_weight", "item_code", "weight"]
    ]
    df = df.merge(w, on=["year_for_weight", "item_code"], how="inner")

    def _trim(g):
        g = g.dropna(subset=["ann_mom"]).sort_values("ann_mom").copy()
        if g.empty: return np.nan
        wtot = g["weight"].sum()
        g["cum"] = g["weight"].cumsum()
        lo_w, hi_w = 0.25 * wtot, 0.75 * wtot
        eff = np.zeros(len(g))
        for i, (_, row) in enumerate(g.iterrows()):
            cp = row["cum"] - row["weight"]
            lo = max(cp, lo_w); hi = min(row["cum"], hi_w)
            if hi > lo: eff[i] = hi - lo
        ws = eff.sum()
        return (eff * g["ann_mom"].values).sum() / ws if ws > 0 else np.nan

    out = df.groupby("date", group_keys=False).apply(_trim).rename("ann_1mo").reset_index()
    out["measure"] = "trimmed_sym_25_cpi_custom"
    out["ann_12mo"] = np.nan
    out["value_index"] = np.nan   # chain centralizado em main() apos consolidacao
    return out[["date", "measure", "value_index", "ann_1mo", "ann_12mo"]]


def fetch_cleveland_cpi_chartdata() -> pd.DataFrame:
    """Cleveland Fed Median CPI + Trimmed Mean CPI direto do CSV publico
    (chartdata, YoY, ~10 anos). Fonte primaria quando FRED esta indisponivel."""
    csv_path = ROOT / "data" / "raw" / "cleveland" / "cpi_mediancpi_chartdata.csv"
    if not _cache_fresh(csv_path):
        print(f"[cleveland] cache stale/ausente — baixando chartdata...")
        url = "https://www.clevelandfed.org/-/media/files/webcharts/mediancpi/mediancpi_chartdata.csv"
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        csv_path.write_bytes(_curl_get(url, timeout=60))
    df = pd.read_csv(csv_path, parse_dates=["date"])
    # cols: date, mediancpi, trimmedmeancpi, cpi, corecpi — valores em % YoY
    out_rows = []
    for col, measure in [("mediancpi", "median_cpi"),
                         ("trimmedmeancpi", "trimmed_mean_16_cpi")]:
        s = df[["date", col]].rename(columns={col: "ann_12mo"}).copy()
        s["measure"] = measure
        s["ann_1mo"] = np.nan   # Cleveland chartdata nao expoe 1-mo ann
        out_rows.append(s[["date", "measure", "ann_1mo", "ann_12mo"]])
    return pd.concat(out_rows, ignore_index=True)


def main() -> None:
    all_rows = []

    # 1a. FRED — Cleveland Median + Trimmed 16%, 1-mo annualized (1983+).
    # FRED e chartdata sao COMPLEMENTARES, nao fallback: FRED entrega ann_1mo,
    # chartdata entrega ann_12mo. Rodamos ambos sempre; se um falhar, o outro
    # cobre sua coluna. Consolidacao vem em (4) via groupby(measure,date).
    print("[1a] FRED Cleveland Median + Trimmed (1-mo annualized)...")
    for mname, fred_id in [("median_cpi", "MEDCPIM158SFRBCLE"),
                           ("trimmed_mean_16_cpi", "TRMMEANCPIM158SFRBCLE")]:
        try:
            s = fetch_fred_csv(fred_id)
            df = s.rename("ann_1mo").reset_index()
            df["measure"] = mname
            df["value_index"] = np.nan   # chain centralizado em (4)
            df["ann_12mo"] = np.nan
            all_rows.append(df[["date", "measure", "value_index", "ann_1mo", "ann_12mo"]])
            print(f"  {mname}: {len(df)} obs 1mo, {df.date.min().date()} -> {df.date.max().date()}")
        except Exception as e:
            print(f"  [FAIL FRED] {mname}: {str(e)[:120]}")

    # 1b. Cleveland chartdata — YoY (~10 anos). Complementa FRED (que so da 1mo).
    print("[1b] Cleveland chartdata (YoY, ~10 anos)...")
    try:
        cle = fetch_cleveland_cpi_chartdata()
        cle["value_index"] = np.nan   # YoY-only, nao contribui pra index
        for m in cle["measure"].unique():
            sub = cle[cle["measure"] == m][["date", "measure", "value_index", "ann_1mo", "ann_12mo"]]
            all_rows.append(sub)
            print(f"  {m}: {len(sub)} obs YoY, {sub.date.min().date()} -> {sub.date.max().date()}")
    except Exception as e:
        print(f"  [FAIL Cleveland] {e}")

    # 2. Atlanta Fed xlsx — 6 series Sticky/Flexible (ann_1mo + ann_12mo)
    print("[2] Atlanta Fed Sticky/Flexible (xlsx oficial)...")
    try:
        at = fetch_atlanta_sticky()
        at["value_index"] = np.nan   # chain centralizado em (4)
        for name in at["measure"].unique():
            sub = at[at["measure"] == name][["date", "measure", "value_index", "ann_1mo", "ann_12mo"]].copy()
            all_rows.append(sub)
            n = len(sub.dropna(subset=["ann_1mo"]))
            print(f"  {name}: {n} obs, {sub.date.min().date()} -> {sub.date.max().date()}")
    except Exception as e:
        print(f"  [FAIL] Atlanta: {e}")

    # 3. Custom bottom-up — Trimmed Sym 25%
    if os.environ.get("SKIP_CUSTOM") != "1":
        print("[3] Custom Trimmed Sym 25% (bottom-up)...")
        try:
            tsm25 = compute_custom_trimmed_sym25()
            all_rows.append(tsm25)
            print(f"  trimmed_sym_25_cpi_custom: {len(tsm25)} obs")
        except Exception as e:
            print(f"  [FAIL] custom: {e}")

    # 4. Consolida + salva
    if not all_rows:
        sys.exit("[FAIL] nenhuma serie obtida — todas as fontes falharam. "
                 "Checar proxy/rede. Nenhum CSV sera gravado.")
    out = pd.concat(all_rows, ignore_index=True)
    # FRED (ann_1mo) + chartdata (ann_12mo) + Atlanta (todos) chegam em linhas
    # separadas pro mesmo (measure, date); colapsa com max (NaN-safe).
    out = (out.groupby(["measure", "date"], as_index=False)
              .agg({"value_index": "max", "ann_1mo": "max", "ann_12mo": "max"}))
    # Proxy MoM SA: inverte anualizacao (todas as fontes publicam ann_1mo SA).
    out["mom_sa"] = ((1 + out["ann_1mo"] / 100) ** (1 / 12) - 1) * 100
    # Para measures sem value_index nativo (Cleveland FRED, custom), encadeia
    # a partir do ann_1mo. Atlanta ja tem index nativo (Dec 1982=100).
    pieces = []
    for measure, g in out.groupby("measure"):
        g = g.sort_values("date").reset_index(drop=True).copy()
        if g["value_index"].isna().all():
            g["value_index"] = _chain_index(g["ann_1mo"]).values
        pieces.append(g)
    out = pd.concat(pieces, ignore_index=True)
    # Rebase todas as series pra Jan/2000=100 pra bater com cpi_cpius_indice.csv.
    # Custom começa 2001-01 → fallback: primeira obs nao-nula = 100.
    out = _rebase_jan2000(out)
    out = out.sort_values(["measure", "date"]).reset_index(drop=True)
    out = out[["date", "measure", "value_index", "ann_1mo", "mom_sa", "ann_12mo"]]

    # Guard: regressao silenciosa (bug que truncou 5660->308 rows em 2026-10-28,
    # proxy senha vencida). 2 modos de falha:
    #  (A) measure ausente: fonte falhou e nao caiu em nenhum cache.
    #  (B) measure presente mas sem ann_1mo: chartdata/cache deu YoY, mas o
    #      chain-source (FRED ann_1mo p/ Cleveland, xlsx p/ Atlanta) morreu —
    #      value_index derivado fica FLAT em 100 (corrupcao silenciosa).
    # Em qualquer dos casos: NAO sobrescreve CSV principal, grava .partial pro
    # debug, exit rc=2 pra Jupyter notar.
    expected = EXPECTED_MEASURES.copy()
    if os.environ.get("SKIP_CUSTOM") == "1":
        expected.discard("trimmed_sym_25_cpi_custom")
    got = set(out["measure"].unique())
    missing = expected - got
    bad_chain = sorted(
        m for m in (expected & got)
        if out[(out["measure"] == m) & out["ann_1mo"].notna()].empty
    )
    if missing or bad_chain:
        if missing:
            print(f"\n[FAIL] {len(missing)}/{len(expected)} measures ausentes: "
                  f"{sorted(missing)}")
        if bad_chain:
            print(f"\n[FAIL] {len(bad_chain)} measures sem ann_1mo (chain gera "
                  f"value_index flat=100): {bad_chain}")
        partial = OUT_CSV.with_suffix(".partial.csv")
        out.to_csv(partial, index=False)
        print(f"  {len(out)} rows salvos em {partial.name} (debug). CSV principal "
              f"{OUT_CSV.name} NAO foi sobrescrito.")
        if OUT_CSV.exists():
            try:
                prev_rows = sum(1 for _ in OUT_CSV.open()) - 1
                print(f"  CSV principal preservado com {prev_rows} rows de run anterior.")
            except Exception:
                pass
        print(f"  Checar proxy/rede nas fontes faltantes e re-rodar.")
        sys.exit(2)

    out.to_csv(OUT_CSV, index=False)
    print(f"\n[OK] {len(out)} rows -> {OUT_CSV.relative_to(ROOT)}")
    print(f"\nSummary por measure:")
    s = out.groupby("measure").agg(
        n_idx=("value_index", lambda x: x.notna().sum()),
        n_1mo=("ann_1mo", lambda x: x.notna().sum()),
        n_12mo=("ann_12mo", lambda x: x.notna().sum()),
        idx_jan2000=("value_index", lambda x: round(x.iloc[(out.loc[x.index, "date"] - pd.Timestamp("2000-01-01")).abs().argmin()], 2) if x.notna().any() else None),
        min_date=("date", "min"),
        max_date=("date", "max"),
    )
    print(s.to_string())


if __name__ == "__main__":
    main()
