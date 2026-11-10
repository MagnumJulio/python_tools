#!/usr/bin/env python3
# build_alt_bottomup_cpi.py
#
# Medidas alternativas de inflacao CPI-U construidas BOTTOM-UP pelo Itau
# (nao existe serie oficial Fed pra elas). Separado de
# build_alt_measures_cpi.py em 2026-11-05 pra que:
#   - um problema em FRED/Atlanta/Cleveland nao derrube o bottom-up, e
#   - um problema na API do BLS nao derrube as series oficiais Fed.
# Cada par build+load sobe pro SQL independente do outro.
#
# Medidas:
#   - trimmed_sym_25_cpi_custom: Trimmed Symmetric 25% (corta 25% do topo +
#     25% da cauda por peso cumulativo, media ponderada do miolo 50%). Nao
#     existe oficial — Cleveland so publica Median e Trim 16%.
#   - median_cpi_proxy: Weighted 50th percentile (proxy do Cleveland Median).
#   - trimmed_mean_16_cpi_proxy: Trimmed Sym 16% (8+8%, def Cleveland Trim 16).
#   - *_goods_proxy / *_services_proxy pros 2 acima: mesma metodologia
#     restringindo o universo ao bucket. Fed nao decompoe — sem oficial pra
#     comparar G/S (igual pacote PCE).
#
#   Universe: ~70 subitens indent-3 da hierarquia BLS; SA do BLS (CUSR)
#   com fallback NSA (CUUR) dessazonalizado via STL. Classificacao G/S
#   reusa prefixos de scripts/build_diffusion_cpius.py (SE** rule) + manual
#   pros 4 SA** no universe (SAF11/SAF116=Goods, SAH21/SAE21=Services).
#
# Entrada:  data/cpi_cpius_subitem_hierarchy.csv, data/cpi_cpius_pesos_annual_subitem.csv
# Cache:    data/cpi_cpius_subitem_alt_raw.csv (7 dias; FORCE_FETCH=1 re-baixa)
# Saida:    data/cpi_cpius_alt_bottomup.csv — mesmas colunas do alt_measures:
#           date, measure, value_index, ann_1mo, mom_sa, ann_12mo
#           (value_index encadeado do ann_1mo e rebaseado Jan/2000=100)
#
# Uso:
#   cd pareto_cpius
#   python scripts/build_alt_bottomup_cpi.py
#   python script_itau/load_alt_bottomup_cpi_to_sql.py --no-confirm
#
# Env vars:
#   BLS_API_KEY   (recomendado: batch de 50 series e mais cota diaria)
#   CORP_PROXY_URL (opcional — override do HTTPS_PROXY do ambiente corp)
#   FORCE_FETCH=1 (ignora o cache de 7 dias dos subitens)

from __future__ import annotations

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

ROOT = Path(__file__).resolve().parent.parent
HIER_CSV = ROOT / "data" / "cpi_cpius_subitem_hierarchy.csv"
PESOS_CSV = ROOT / "data" / "cpi_cpius_pesos_annual_subitem.csv"
# Cache isolado dos ~70 indent-3 nodes (separado do breadth desde 2026-10-22).
RAW_OUT = ROOT / "data" / "cpi_cpius_subitem_alt_raw.csv"
OUT_CSV = ROOT / "data" / "cpi_cpius_alt_bottomup.csv"
RAW_TTL_HOURS = 24 * 7   # re-fetch de 70 subitens via BLS leva ~2-3 min

EXPECTED_MEASURES = {
    "trimmed_sym_25_cpi_custom",
    "median_cpi_proxy", "median_cpi_goods_proxy", "median_cpi_services_proxy",
    "trimmed_mean_16_cpi_proxy", "trimmed_mean_16_cpi_goods_proxy",
    "trimmed_mean_16_cpi_services_proxy",
}

# Classificacao Goods/Services. SE** codes usam prefix rule espelhada do
# scripts/build_diffusion_cpius.py (fonte de verdade da classificacao a
# nivel de leaf). Os 4 SA** no universe indent-3 sao aggregates que nao
# entram naquela regra — mapeio explicito aqui pelo peso dominante:
#   SAF11  = Food at home                    -> Goods
#   SAF116 = Alcoholic beverages             -> Goods
#   SAH21  = Household energy (elec+gas+oil) -> Services (elec+gas dominam)
#   SAE21  = Info & information processing   -> Services (communication dom.)
SERVICES_PREFIXES_SE = {
    "SEHA", "SEHB", "SEHC", "SEHD", "SEHF", "SEHG", "SEHP",
    "SEMC", "SEMD",
    "SETD", "SETE", "SETF", "SETG",
    "SEEB", "SEEC", "SEED",
    "SEFV",
    "SEGC", "SEGD",
}
# Items que violam a regra SE** → Services. Espelha SERVICES_ITEMS do
# build_diffusion_cpius.py restrito ao universe indent-3.
SERVICES_SE_ITEMS_EXPLICIT = {
    "SERA02", "SERA04", "SERA06",   # cable/satellite, video sub, music sub
    "SERB02",                        # pet services
    "SERD02",                        # photo processing
    "SERF01", "SERF02", "SERF03",   # clubs, admissions, lessons
    "SEME",                          # health insurance
}
SA_EXPLICIT_BUCKET = {
    "SAF11":  "Goods",
    "SAF116": "Goods",
    "SAH21":  "Services",
    "SAE21":  "Services",
}


def classify_bucket(item_code: str) -> str:
    """'Goods' ou 'Services' pra cada node do universo bottom-up."""
    if item_code in SA_EXPLICIT_BUCKET:
        return SA_EXPLICIT_BUCKET[item_code]
    if item_code in SERVICES_SE_ITEMS_EXPLICIT:
        return "Services"
    if item_code[:4] in SERVICES_PREFIXES_SE:
        return "Services"
    return "Goods"

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


def _mask_proxy(u):
    if not u: return "(none — direct)"
    import re
    return re.sub(r":([^@/]+)@", ":***@", u)


print(f"[proxy] _PROXY_URL = {_mask_proxy(_PROXY_URL)}", flush=True)


def _cache_fresh(path: Path, ttl_hours: int) -> bool:
    """True se arquivo existe E foi atualizado nas ultimas ttl_hours."""
    if not path.exists():
        return False
    age_h = (time.time() - path.stat().st_mtime) / 3600
    return age_h < ttl_hours


# ----- BLS fetch dos subitens ----------------------------------------------

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
    """Fetch SA (CUSR) + fallback NSA (CUUR) pros subitens indent-3."""
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
    """STL (log, robust) nos subitens que so existem NSA. Precisa de >=36 obs."""
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


def load_subitems(codes: list[str]) -> pd.DataFrame:
    """Subitens SA (cache de 7 dias ou fetch BLS), ja dessazonalizados."""
    use_cache = (
        _cache_fresh(RAW_OUT, RAW_TTL_HOURS)
        and RAW_OUT.stat().st_size > 1000      # minimo sanity (header + algumas linhas)
        and os.environ.get("FORCE_FETCH") != "1"
    )
    raw = None
    if use_cache:
        try:
            raw = pd.read_csv(RAW_OUT, parse_dates=["date"])
            if raw.empty or "item_code" not in raw.columns:
                raise ValueError("cache vazio/sem schema esperado")
            print(f"[bottom-up] cache {RAW_OUT.name} ({len(raw)} rows). FORCE_FETCH=1 pra re-baixar")
        except Exception as e:
            print(f"[bottom-up] cache corrompido ({e}) — re-fetch")
            raw = None
    if raw is None:
        raw = _fetch_leaves(codes)
        if raw.empty:
            raise RuntimeError("BLS nao devolveu nenhum subitem (API fora / proxy / cota). "
                               "Cache anterior, se existir, foi preservado.")
        RAW_OUT.parent.mkdir(parents=True, exist_ok=True)
        raw.to_csv(RAW_OUT, index=False)
    return _deseasonalize_nsa(raw)


# ----- Medidas -------------------------------------------------------------

def _reindex_monthly_by(df: pd.DataFrame, group_col: str) -> pd.DataFrame:
    """Reindexa cada grupo pra grade mensal completa (MS freq), NaN em buracos.
    Por que: pct_change() opera por linha adjacente. Com o gap Oct-2025 do
    shutdown BLS, Nov-25 ficaria comparando com Sep-25 (2 meses) como se fosse
    1 mes. Reindexando, Oct-25 vira NaN e Nov-25 pct_change contra Oct-25 NaN
    propaga como NaN — correto."""
    if df.empty: return df
    out = []
    for g, part in df.groupby(group_col):
        part = part.set_index("date").sort_index()
        full = pd.date_range(part.index.min(), part.index.max(), freq="MS")
        part = part.reindex(full).rename_axis("date").reset_index()
        part[group_col] = g
        out.append(part)
    return pd.concat(out, ignore_index=True)


def _reindex_monthly(df: pd.DataFrame) -> pd.DataFrame:
    """Reindex mensal sem grupo (1 serie). Versao scalar do helper acima."""
    if df.empty: return df
    s = df.set_index("date").sort_index()
    full = pd.date_range(s.index.min(), s.index.max(), freq="MS")
    return s.reindex(full).rename_axis("date").reset_index()


def _prep_panel(raw: pd.DataFrame, pesos: pd.DataFrame,
                codes_filter: set[str] | None = None) -> pd.DataFrame:
    """Cria o painel (date, item_code, ann_mom, weight) merge subitens × peso
    anual (ano t-1). `codes_filter` restringe o universo (Goods/Services).
    Reindex monthly complete garante pct_change em intervalo mensal real."""
    df = raw.sort_values(["item_code", "date"]).copy()
    if codes_filter is not None:
        df = df[df["item_code"].isin(codes_filter)]
    df = _reindex_monthly_by(df, group_col="item_code")
    # fill_method=None: pct_change nao pode forward-fill o NaN de Oct-25 pq
    # isso faria Nov-25 comparar silenciosamente com Sep-25 (2 meses) como
    # se fosse 1 mes. Com None, pct_change(NaN) = NaN — gap propaga correto.
    df["mom"] = df.groupby("item_code")["value_index"].pct_change(fill_method=None) * 100
    df["ann_mom"] = ((1 + df["mom"] / 100) ** 12 - 1) * 100
    df["year_for_weight"] = df["date"].dt.year - 1
    w = pesos.rename(columns={"year": "year_for_weight", "cpi_u": "weight"})[
        ["year_for_weight", "item_code", "weight"]
    ]
    df = df.merge(w, on=["year_for_weight", "item_code"], how="inner")
    return df.dropna(subset=["ann_mom"])


def _weighted_trim_mean_month(g: pd.DataFrame, trim_low: float,
                              trim_high: float) -> float:
    """Media ponderada aparada; items que straddleiam a boundary contribuem
    com peso efetivo proporcional ao overlap (padrao Cleveland/Dallas)."""
    g = g.sort_values("ann_mom")
    if g.empty: return np.nan
    wtot = float(g["weight"].sum())
    cum = g["weight"].cumsum().values
    cum_prev = cum - g["weight"].values
    lo, hi = trim_low * wtot, (1.0 - trim_high) * wtot
    eff = np.maximum(0.0, np.minimum(cum, hi) - np.maximum(cum_prev, lo))
    ws = eff.sum()
    return float((eff * g["ann_mom"].values).sum() / ws) if ws > 0 else np.nan


def _weighted_median_month(g: pd.DataFrame) -> float:
    """Weighted 50th percentile (same algo do pareto_pce/scripts/
    build_alt_measures_pce_proxy.py)."""
    g = g.sort_values("ann_mom")
    if g.empty: return np.nan
    cum = g["weight"].cumsum().values
    threshold = g["weight"].sum() / 2.0
    i = int(np.searchsorted(cum, threshold, side="left"))
    i = min(i, len(g) - 1)
    return float(g["ann_mom"].iloc[i])


def compute_trimmed_sym25(raw: pd.DataFrame, pesos: pd.DataFrame) -> pd.DataFrame:
    """Trim Sym 25%: universo total, corte 25% em cada cauda (miolo 50%)."""
    df = _prep_panel(raw, pesos)
    out = (df.groupby("date", group_keys=False)
             .apply(lambda g: _weighted_trim_mean_month(g, 0.25, 0.25))
             .rename("ann_1mo").reset_index())
    out["measure"] = "trimmed_sym_25_cpi_custom"
    return out[["date", "measure", "ann_1mo"]]


def compute_proxy_measures(raw: pd.DataFrame, pesos: pd.DataFrame,
                           scope: str, codes_filter: set[str] | None) -> pd.DataFrame:
    """Gera median + trim16 pro scope. scope in {'headline','goods','services'}
    controla o sufixo das measures (`_goods`/`_services`). codes_filter
    restringe o universo (None = headline, todos 70)."""
    assert scope in {"headline", "goods", "services"}
    df = _prep_panel(raw, pesos, codes_filter=codes_filter)
    suffix = "" if scope == "headline" else f"_{scope}"
    rows = []
    for d, g in df.groupby("date"):
        med = _weighted_median_month(g)
        t16 = _weighted_trim_mean_month(g, 0.08, 0.08)
        rows.append({"date": d, f"median_cpi{suffix}_proxy": med,
                     f"trimmed_mean_16_cpi{suffix}_proxy": t16})
    wide = pd.DataFrame(rows)
    long = wide.melt(id_vars=["date"], var_name="measure", value_name="ann_1mo")
    return long.sort_values(["measure", "date"]).reset_index(drop=True)


# ----- Consolidacao (mesmo formato do build_alt_measures_cpi.py) -----------

def _chain_index(ann_1mo: pd.Series, base: float = 100.0) -> pd.Series:
    """ann_1mo (% anualizado) -> indice encadeado. NaN vira fator 1."""
    mom = (1 + ann_1mo / 100) ** (1 / 12) - 1
    factor = (1 + mom.fillna(0)).cumprod()
    return base * factor


def _rebase_jan2000(df: pd.DataFrame) -> pd.DataFrame:
    """Rebase value_index pra Jan/2000=100 por measure; sem obs em Jan/2000
    (custom comeca em 2001-01) usa a primeira obs nao-nula como ancora."""
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


def consolidate(measures: list[pd.DataFrame]) -> pd.DataFrame:
    """Chain + YoY. Reindex mensal completo por measure pra que pct_change(12)
    e shift(12) opere em 12 meses calendario reais (nao 12 linhas). Gap do
    shutdown Oct-2025: ann_1mo vira NaN; chain carrega indice (fillna(0))
    pra nao quebrar o nivel; YoY dos 12 meses em que t-12 cai no gap vira
    NaN explicito (semanticamente nao comparavel vs mes ausente)."""
    out = pd.concat(measures, ignore_index=True)
    pieces = []
    for measure, g in out.groupby("measure"):
        g = _reindex_monthly(g.drop(columns=["measure"]))
        g["measure"] = measure
        g["mom_sa"] = ((1 + g["ann_1mo"] / 100) ** (1 / 12) - 1) * 100
        g["value_index"] = _chain_index(g["ann_1mo"]).values
        g["ann_12mo"] = g["value_index"].pct_change(12, fill_method=None) * 100
        # Anula YoY tanto no proprio mes de gap (idx foi carried via fillna(0),
        # YoY so refletiria o acumulado pre-gap) quanto no mes t cujo t-12 cai
        # no gap (idx[t-12] carried → comparacao reporta crescimento de 13+ meses
        # como se fosse YoY). Cobre os 12 meses pos-gap de contaminacao.
        bad_yoy = g["ann_1mo"].isna() | g["ann_1mo"].shift(12).isna()
        g["ann_12mo"] = g["ann_12mo"].where(~bad_yoy)
        pieces.append(g)
    out = _rebase_jan2000(pd.concat(pieces, ignore_index=True))
    out = out.sort_values(["measure", "date"]).reset_index(drop=True)
    return out[["date", "measure", "value_index", "ann_1mo", "mom_sa", "ann_12mo"]]


def main(hier_year: int = 2025) -> None:
    for p in (HIER_CSV, PESOS_CSV):
        if not p.exists():
            sys.exit(f"[FAIL] {p.relative_to(ROOT)} nao existe. Rode antes "
                     f"scripts/fetch_bls_pesos.R e scripts/build_subitem_hierarchy.py.")
    hier = pd.read_csv(HIER_CSV)
    pesos = pd.read_csv(PESOS_CSV)
    uni = hier[(hier.year == hier_year) & (hier.indent == 3)]
    codes = sorted(uni.item_code.unique().tolist())
    if not codes:
        sys.exit(f"[FAIL] hierarquia sem nodes indent-3 em {hier_year}. "
                 f"Checar {HIER_CSV.name} (ou atualizar hier_year).")
    goods_codes    = {c for c in codes if classify_bucket(c) == "Goods"}
    services_codes = {c for c in codes if classify_bucket(c) == "Services"}
    print(f"[bottom-up] universe indent-3 em {hier_year}: {len(codes)} subitens "
          f"(Goods {len(goods_codes)}, Services {len(services_codes)})")

    print("[1] Subitens BLS (SA + fallback NSA/STL)...")
    raw = load_subitems(codes)

    print("[2] Medidas...")
    measures = []

    # 2a. Trim Sym 25% custom (headline only — contratado desde 2026-10).
    try:
        tsm25 = compute_trimmed_sym25(raw, pesos)
        measures.append(tsm25)
        print(f"  trimmed_sym_25_cpi_custom: {len(tsm25)} obs, "
              f"{tsm25.date.min().date()} -> {tsm25.date.max().date()}")
    except Exception as e:
        print(f"  [FAIL] trimmed_sym_25_cpi_custom: {e}")

    # 2b. Median + Trim 16 proxy (headline + goods + services). Padrao PCE
    # proxy — 6 novas series.
    for scope, flt in (("headline", None),
                       ("goods", goods_codes),
                       ("services", services_codes)):
        try:
            prox = compute_proxy_measures(raw, pesos, scope=scope, codes_filter=flt)
            measures.append(prox)
            got = sorted(prox["measure"].unique())
            print(f"  scope={scope}: {got}")
        except Exception as e:
            print(f"  [FAIL] scope={scope}: {e}")

    print("[3] Consolida...")
    out = consolidate(measures) if measures else pd.DataFrame(columns=["measure", "ann_1mo"])
    got = set(out["measure"].unique())
    missing = EXPECTED_MEASURES - got
    bad_chain = sorted(m for m in (EXPECTED_MEASURES & got)
                       if out[(out["measure"] == m) & out["ann_1mo"].notna()].empty)
    if missing or bad_chain:
        # Nao sobrescreve o CSV principal com dado parcial; a carga seguinte
        # continua usando o resultado do ultimo build bom.
        if missing:
            print(f"\n[FAIL] measures ausentes: {sorted(missing)}")
        if bad_chain:
            print(f"\n[FAIL] measures sem ann_1mo (indice ficaria flat=100): {bad_chain}")
        if not out.empty:
            partial = OUT_CSV.with_suffix(".partial.csv")
            out.to_csv(partial, index=False)
            print(f"  {len(out)} rows salvos em {partial.name} (debug).")
        print(f"  CSV principal {OUT_CSV.name} NAO foi sobrescrito.")
        sys.exit(2)

    out.to_csv(OUT_CSV, index=False)
    print(f"\n[OK] {len(out)} rows -> {OUT_CSV.relative_to(ROOT)}")
    print("\nSummary por measure:")
    s = out.groupby("measure").agg(
        n_idx=("value_index", lambda x: x.notna().sum()),
        n_1mo=("ann_1mo", lambda x: x.notna().sum()),
        n_12mo=("ann_12mo", lambda x: x.notna().sum()),
        min_date=("date", "min"),
        max_date=("date", "max"),
    )
    print(s.to_string())


if __name__ == "__main__":
    main()
