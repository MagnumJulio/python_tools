#!/usr/bin/env python3
# build_alt_measures_cpi.py
#
# Medidas alternativas de inflacao CPI-U pra servir no SQL corp.
#
# Estrategia primaria: fetch das series OFICIAIS (match 100% com Fed):
#   - Cleveland Fed Median CPI       (FRED: MEDCPIM158SFRBCLE)
#   - Cleveland Fed Trimmed-Mean CPI (FRED: TRMMEANCPIM158SFRBCLE)
#   - Atlanta Fed Sticky-Price CPI family (FRED rid=313, 6 series; fallback xlsx oficial)
#   ATLANTA_SOURCE=xlsx forca o xlsx (debug)
#
# As medidas BOTTOM-UP proprias (Trimmed Sym 25% custom) moram em
# scripts/build_alt_bottomup_cpi.py + script_itau/load_alt_bottomup_cpi_to_sql.py
# desde 2026-11-05: assim uma falha de FRED/Atlanta nao derruba o bottom-up
# e vice-versa. Este script so entrega as 8 series oficiais Fed.
#
# Uso:
#   cd pareto_cpius
#   python scripts/build_alt_measures_cpi.py
#
# Env vars:
#   CORP_PROXY_URL (opcional — corp only)

from __future__ import annotations

import io
import os
import subprocess
import sys
import time
from pathlib import Path

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
OUT_DIR = ROOT / "data"
ATLANTA_XLSX = ROOT / "data" / "raw" / "atlanta" / "stickyprice.xlsx"
OUT_CSV = OUT_DIR / "cpi_cpius_alt_measures.csv"

# Universo esperado — se vier menos que isso, o guard em main() preserva o
# CSV existente em vez de sobrescrever com dado parcial (caso proxy falhe
# em algumas fontes).
EXPECTED_MEASURES = {
    "median_cpi", "trimmed_mean_16_cpi",           # Cleveland FRED
    "flexible_cpi", "core_flexible_cpi",           # Atlanta FRED/xlsx
    "sticky_cpi", "core_sticky_cpi",
    "sticky_cpi_ex_shelter", "core_sticky_cpi_ex_shelter",
}

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


def _refresh_or_keep(path, url: str, label: str, timeout: int = 60) -> None:
    """Baixa `url` em `path` quando o cache esta stale. Se o download falhar
    (corp bloqueia atlantafed/clevelandfed: curl rc=22) e ja existe um
    arquivo seed/cache, avisa e segue com ele em vez de derrubar o build —
    o seed Fed esta commitado no repo justamente pra isso (commit f147fbf).
    Falha de verdade so quando nao ha arquivo nenhum."""
    import datetime as _dt
    if _cache_fresh(path):
        return
    print(f"[{label}] cache stale/ausente — baixando...")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.write_bytes(_curl_get(url, timeout=timeout))
    except Exception as e:
        if path.exists() and path.stat().st_size > 0:
            age = _dt.datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d")
            print(f"[{label}] [WARN] download falhou ({e}); usando arquivo existente de {age}: {path.name}")
        else:
            raise


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


# As 6 series Sticky/Flexible que o Atlanta Fed publica no FRED (release
# rid=313). Sufixo M158 = "percent change at annual rate" (= coluna
# "1-mo annualized" do xlsx), M159 = "percent change from year ago" (= "12-mo").
ATLANTA_FRED_IDS = {
    "flexible_cpi":               ("FLEXCPIM158SFRBATL",       "FLEXCPIM159SFRBATL"),
    "core_flexible_cpi":          ("COREFLEXCPIM158SFRBATL",   "COREFLEXCPIM159SFRBATL"),
    "sticky_cpi":                 ("STICKCPIM158SFRBATL",      "STICKCPIM159SFRBATL"),
    "core_sticky_cpi":            ("CORESTICKM158SFRBATL",     "CORESTICKM159SFRBATL"),
    "sticky_cpi_ex_shelter":      ("STICKCPIXSHLTRM158SFRBATL", "STICKCPIXSHLTRM159SFRBATL"),
    "core_sticky_cpi_ex_shelter": ("CRESTKCPIXSLTRM158SFRBATL", "CRESTKCPIXSLTRM159SFRBATL"),
}


def fetch_atlanta_sticky_fred() -> pd.DataFrame:
    """Mesmas 6 series do xlsx, mas via FRED (o Atlanta Fed e quem publica
    la). Fonte primaria porque a corp bloqueia atlantafed.org e libera
    fred.stlouisfed.org. Falha em qualquer serie -> levanta, e o caller cai
    pro xlsx."""
    out_rows = []
    for name, (id_1mo, id_12mo) in ATLANTA_FRED_IDS.items():
        s1 = fetch_fred_csv(id_1mo).rename("ann_1mo")
        s12 = fetch_fred_csv(id_12mo).rename("ann_12mo")
        if s1.empty:
            raise RuntimeError(f"FRED {id_1mo} vazio")
        df = pd.concat([s1, s12], axis=1).reset_index().rename(columns={"index": "date"})
        df.columns = ["date", "ann_1mo", "ann_12mo"]
        df["date"] = pd.to_datetime(df["date"]).dt.to_period("M").dt.to_timestamp()
        df["measure"] = name
        out_rows.append(df)
        print(f"  [atlanta/fred] {name}: {len(s1)} obs, ultima {s1.index.max().date()}")
    return pd.concat(out_rows, ignore_index=True)


def fetch_atlanta_sticky() -> pd.DataFrame:
    """6 series Sticky/Flexible do Atlanta Fed, long df (date, ann_1mo,
    ann_12mo, measure). Ordem: FRED (passa no proxy corp) -> xlsx oficial
    (download, ou o seed/cache commitado se o download falhar). O index e
    reconstruido em main() via _chain_index(ann_1mo)."""
    if os.environ.get("ATLANTA_SOURCE", "fred").lower() != "xlsx":
        try:
            return fetch_atlanta_sticky_fred()
        except Exception as e:
            print(f"[atlanta] FRED falhou ({str(e)[:120]}); tentando xlsx oficial...")
    return fetch_atlanta_sticky_xlsx()


def fetch_atlanta_sticky_xlsx() -> pd.DataFrame:
    """Parse xlsx oficial Atlanta Fed. Atlanta NAO publica index level
    nativo — cada bloco de 4 cols é: (MoM decimal, 1-mo annualized %,
    3-mo a.r., 12-mo %)."""
    url = ("https://www.atlantafed.org/-/media/Project/Atlanta/FRBA/Documents/"
           "datafiles/research/inflationproject/stickprice/stickyprice.xlsx")
    _refresh_or_keep(ATLANTA_XLSX, url, "atlanta", timeout=120)

    df = pd.read_excel(ATLANTA_XLSX, sheet_name="Data", header=None)
    SERIES_NAMES = list(ATLANTA_FRED_IDS)   # mesma ordem dos blocos do xlsx
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


def fetch_cleveland_cpi_chartdata() -> pd.DataFrame:
    """Cleveland Fed Median CPI + Trimmed Mean CPI direto do CSV publico
    (chartdata, YoY, ~10 anos). Fonte primaria quando FRED esta indisponivel."""
    csv_path = ROOT / "data" / "raw" / "cleveland" / "cpi_mediancpi_chartdata.csv"
    url = "https://www.clevelandfed.org/-/media/files/webcharts/mediancpi/mediancpi_chartdata.csv"
    _refresh_or_keep(csv_path, url, "cleveland", timeout=60)
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
            df["value_index"] = np.nan   # chain centralizado em (3)
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
    print("[2] Atlanta Fed Sticky/Flexible (FRED, fallback xlsx)...")
    try:
        at = fetch_atlanta_sticky()
        at["value_index"] = np.nan   # chain centralizado em (3)
        for name in at["measure"].unique():
            sub = at[at["measure"] == name][["date", "measure", "value_index", "ann_1mo", "ann_12mo"]].copy()
            all_rows.append(sub)
            n = len(sub.dropna(subset=["ann_1mo"]))
            print(f"  {name}: {n} obs, {sub.date.min().date()} -> {sub.date.max().date()}")
    except Exception as e:
        print(f"  [FAIL] Atlanta: {e}")

    # (o bottom-up Trimmed Sym 25% saiu daqui -> build_alt_bottomup_cpi.py)

    # 3. Consolida + salva
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
    # Nenhuma fonte entrega value_index nativo: encadeia a partir do ann_1mo.
    pieces = []
    for measure, g in out.groupby("measure"):
        g = g.sort_values("date").reset_index(drop=True).copy()
        if g["value_index"].isna().all():
            g["value_index"] = _chain_index(g["ann_1mo"]).values
        pieces.append(g)
    out = pd.concat(pieces, ignore_index=True)
    # Rebase todas as series pra Jan/2000=100 pra bater com cpi_cpius_indice.csv.
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
