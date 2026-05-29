#!/usr/bin/env python
# Mini-script corp-only: valida nossa SA contra series SA do Haver ja carregadas
# no SQL corp. Sempre normaliza pra MoM antes de comparar (mesmo se a serie
# Haver for indice nivel). Computa mean|d|, max|d|, corr nos ultimos N meses.
#
# Pre-req: load_pareto_to_sql.py --sa rodado (+ workarounds servicos/dp/medio
#          se aplicavel). Haver SA ja no SQL.
#
# Uso:
#   python script_itau/_validate_sa_vs_haver.py                  # roda comparacao
#   python script_itau/_validate_sa_vs_haver.py --window 60      # janela 60m
#
# Editar MAPPING abaixo. Cada entry e (haver_series_id, "var" | "idx"):
#   - "var" = serie ja em variacao mensal (%); compara direto
#   - "idx" = serie em nivel de indice; deriva MoM antes de comparar

import sys
import argparse
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "script_itau"))

# ============================================================================
# MAPPING: nossa_categoria  ->  (haver_series_id, "var" ou "idx")
# ----------------------------------------------------------------------------
# Os 11 IDs sao IPCA grupos top-level (NAO batem conceito-a-conceito com
# nossas 27 analiticas — Haver "Food and Beverages" inclui alim fora de casa;
# nosso alim_domicilio nao). Mas serve pra testar a mecanica da comparacao.
# Marcacao "idx" pra todos ate confirmar; se Haver guardar var direto, troca.
# ============================================================================
MAPPING: dict[str, tuple[int, str]] = {
    # nossa_cat:           (haver_id, kind)   # Haver label
    "alim_domicilio":      (5037, "idx"),     # IPCA: Food and Beverages
    # "administrados":      (XXXX, "idx"),    # IPCA: Monitored Prices SA
    # "livres":             (XXXX, "idx"),    # IPCA: Free Prices SA
    # "servicos":           (XXXX, "idx"),    # IPCA: Services SA
    # "industriais":        (XXXX, "idx"),    # IPCA: Industrial Goods SA
    # "nucleo_medio":       (XXXX, "idx"),    # IPCA: Core - Mean SA
    # "nucleo_ma":          (XXXX, "idx"),    # IPCA: Core - Trimmed Mean SA
    # "nucleo_ms":          (XXXX, "idx"),    # IPCA: Core - Smoothed SA
    # "nucleo_dp":          (XXXX, "idx"),    # IPCA: Core - Double Weight SA
    # "nucleo_p55":         (XXXX, "idx"),    # IPCA: Core - P55 SA
}


def _to_month_start(s: pd.Series) -> pd.Series:
    """Normaliza qualquer date (dia 01, fim do mes, qualquer) pra MS uniforme."""
    s = s.copy()
    s.index = pd.to_datetime(s.index).to_period("M").to_timestamp()
    return s.sort_index()


def _to_mom(s: pd.Series, kind: str) -> pd.Series:
    """Se kind=='idx', deriva MoM% via pct change. Se 'var', retorna como esta.
    Heuristica de seguranca: se kind nao especificado mas mean(abs) > 10,
    assume indice (escala 100+) e converte."""
    if kind == "idx" or (kind == "auto" and s.abs().mean() > 10):
        return ((s / s.shift(1)) - 1) * 100
    return s


def fetch_haver(session, series_id: int) -> pd.Series | None:
    df = pd.read_sql(
        """
        SELECT date, value FROM OPT_Macro_Series_Data_2
        WHERE series_id = ? ORDER BY date
        """,
        session.conn, params=[series_id],
    )
    if df.empty:
        return None
    df["date"] = pd.to_datetime(df["date"])
    s = df.set_index("date")["value"].astype(float)
    return _to_month_start(s)


def fetch_our_sa(session, cat: str) -> pd.Series | None:
    df = pd.read_sql(
        """
        SELECT d.date, d.value
        FROM OPT_Macro_Series_Data_2 d
        JOIN OPT_Macro_Series_2 m ON d.series_id = m.series_id
        WHERE m.haver_code LIKE ?
        ORDER BY d.date
        """,
        session.conn, params=[f"PARETO_IPCA:{cat}/V63/RECON-%/SA"],
    )
    if df.empty:
        return None
    df["date"] = pd.to_datetime(df["date"])
    s = df.set_index("date")["value"].astype(float)
    return _to_month_start(s)


def compare(ours: pd.Series, theirs_mom: pd.Series, window: int) -> dict | None:
    merged = pd.concat({"ours": ours, "haver": theirs_mom}, axis=1).dropna()
    if merged.empty:
        return None
    sub = merged.tail(window)
    d = sub["ours"] - sub["haver"]
    return {
        "n_overlap": len(merged),
        "n_window": len(sub),
        "first": merged.index.min(),
        "last": merged.index.max(),
        "mean_abs_d": d.abs().mean(),
        "max_abs_d": d.abs().max(),
        "bias": d.mean(),
        "corr": sub["ours"].corr(sub["haver"]),
        "last_12_diff": d.tail(12).round(3).to_dict(),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--window", type=int, default=24,
                    help="Janela em meses pra metricas (default 24)")
    args = ap.parse_args()

    if not MAPPING:
        sys.exit("[INFO] MAPPING vazio — edite o dict no topo do script.")

    from opt_utils.database import SQLConnector
    session = SQLConnector(connector="pyodbc")

    try:
        print(f"COMPARAÇÃO MoM SA — janela últimos {args.window} meses")
        print("=" * 78)

        rows = []
        for cat, (hid, kind) in MAPPING.items():
            ours = fetch_our_sa(session, cat)
            haver_raw = fetch_haver(session, hid)

            if ours is None:
                print(f"[SKIP] {cat}: nossa SA nao encontrada.")
                continue
            if haver_raw is None:
                print(f"[SKIP] {cat} ↔ {hid}: Haver vazio.")
                continue

            # Normaliza Haver pra MoM se for indice
            haver_mom = _to_mom(haver_raw, kind)
            sample = haver_raw.tail(3).round(2).to_dict()
            print(f"\n[{cat} ↔ haver {hid}, kind={kind}]")
            print(f"  haver raw (ultimos 3): {sample}")

            res = compare(ours, haver_mom, args.window)
            if res is None:
                print(f"  [SKIP] zero overlap.")
                continue

            rows.append({
                "categoria": cat,
                "haver_id": hid,
                "n_overlap": res["n_overlap"],
                "window": res["n_window"],
                "mean|d| (pp)": round(res["mean_abs_d"], 4),
                "max|d| (pp)": round(res["max_abs_d"], 4),
                "bias (pp)": round(res["bias"], 4),
                "corr": round(res["corr"], 4),
            })
            print(f"  overlap {res['n_overlap']} obs "
                  f"({res['first'].date()} → {res['last'].date()})")
            print(f"  janela {res['n_window']}m: "
                  f"mean|d|={res['mean_abs_d']:.4f}, "
                  f"max|d|={res['max_abs_d']:.4f}, "
                  f"bias={res['bias']:+.4f}, corr={res['corr']:.4f}")
            print(f"  ultimos 12 diffs (ours-haver): {res['last_12_diff']}")

        if rows:
            print("\n" + "=" * 78)
            print("TABELA MARKDOWN")
            print("=" * 78)
            df_out = pd.DataFrame(rows)
            print(df_out.to_markdown(index=False))
    finally:
        session.close()


if __name__ == "__main__":
    main()
