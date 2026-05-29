#!/usr/bin/env python
# Mini-script corp-only: valida nossa SA contra series SA do Haver ja carregadas
# no SQL corp. Compara MoM SA mes a mes, computa mean|d|, max|d|, corr nos
# ultimos N meses, e imprime tabela markdown pronta pra colar em relatorio.
#
# Pre-req: load_pareto_to_sql.py --sa rodado (+ mini-scripts de workaround
#          pra servicos/dp/medio se aplicavel). Haver series ja no SQL.
#
# Uso:
#   python script_itau/_validate_sa_vs_haver.py                # roda comparacao
#   python script_itau/_validate_sa_vs_haver.py --probe        # so probe meta
#   python script_itau/_validate_sa_vs_haver.py --window 60    # janela 60m
#
# Editar MAPPING abaixo conforme descobrir quais Haver series_ids batem com
# quais categorias nossas. Lista atual sao os 9 grupos IPCA + Extended +
# series user-fornecidas — provavelmente nenhuma bate conceito-a-conceito,
# mas serve pra testar o pipeline da comparacao.

import sys
import argparse
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "script_itau"))

# ============================================================================
# MAPPING: nossa_categoria  ->  Haver series_id
# ----------------------------------------------------------------------------
# Edite essa dict conforme descobrir os Haver series_ids certos.
# Os 11 abaixo sao os que o usuario forneceu — sao IPCA grupos top-level
# (Alimentacao, Habitacao, etc.) que NAO batem com nossas 27 categorias
# analiticas. Serve pra testar o pipeline; troque pelos certos depois.
# ============================================================================
MAPPING = {
    # nossa_cat:           haver_series_id  # Haver label (Itau)
    # --- exemplo (provavelmente NAO bate conceito) ---
    "alim_domicilio":      5037,   # IPCA: Food and Beverages (grupo 1, superset)
    # Adicione/edite outras conforme descobrir matches reais:
    # "administrados":      <id>,  # IPCA: Monitored Prices SA
    # "livres":             <id>,  # IPCA: Free Prices SA
    # "servicos":           <id>,  # IPCA: Services SA
    # "industriais":        <id>,  # IPCA: Industrial Goods SA
    # "nucleo_medio":       <id>,  # IPCA: Core - Mean SA
    # "nucleo_ma":          <id>,  # IPCA: Core - Trimmed Mean SA
    # "nucleo_ms":          <id>,  # IPCA: Core - Smoothed Trimmed Mean SA
    # "nucleo_dp":          <id>,  # IPCA: Core - Double Weight SA
    # "nucleo_p55":         <id>,  # IPCA: Core - P55 SA
}

# Lista completa que o usuario forneceu (probe-only — pra inspecionar metadata)
PROBE_IDS = [5036, 5037, 5038, 5039, 5040, 5041, 5042, 5043, 5045, 5046, 5047]


def probe_metadata(session, ids):
    """Lista series_name, data_type, frequency, description dos series_ids dados."""
    qs = ",".join("?" * len(ids))
    df = pd.read_sql(
        f"""
        SELECT series_id, series_name, data_type, frequency, description, haver_code
        FROM OPT_Macro_Series_2
        WHERE series_id IN ({qs})
        ORDER BY series_id
        """,
        session.conn, params=ids,
    )
    return df


def fetch_series(session, series_id):
    """Le serie pivotada (date -> value) pelo series_id."""
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
    # Normaliza pro dia 1 do mes (Haver pode estar no fim do mes)
    df["date"] = df["date"] - pd.offsets.MonthBegin(1) + pd.offsets.MonthBegin(1)
    df["date"] = df["date"].dt.to_period("M").dt.to_timestamp()
    return df.set_index("date")["value"].astype(float).sort_index()


def fetch_our_sa(session, cat):
    """Le var SA nossa do SQL filtrando por haver_code PARETO_IPCA:<cat>/V63/RECON-%/SA."""
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
    df["date"] = df["date"].dt.to_period("M").dt.to_timestamp()
    return df.set_index("date")["value"].astype(float).sort_index()


def compare(ours, theirs, window):
    """Alinha por data, calcula mean|d|, max|d|, corr nos ultimos `window` meses."""
    merged = pd.concat({"ours": ours, "haver": theirs}, axis=1).dropna()
    if merged.empty:
        return None
    sub = merged.tail(window)
    d = sub["ours"] - sub["haver"]
    return {
        "n_overlap": len(merged),
        "n_window": len(sub),
        "first_overlap": merged.index.min(),
        "last_overlap": merged.index.max(),
        "mean_abs_d": d.abs().mean(),
        "max_abs_d": d.abs().max(),
        "bias": d.mean(),
        "corr": sub["ours"].corr(sub["haver"]),
        "last_12_diff": d.tail(12).round(3).to_dict(),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", action="store_true",
                    help="So imprime metadata dos series_ids PROBE_IDS; nao compara")
    ap.add_argument("--window", type=int, default=24,
                    help="Janela em meses pra metricas (default 24)")
    args = ap.parse_args()

    from opt_utils.database import SQLConnector
    session = SQLConnector(connector="pyodbc")

    try:
        print("=" * 78)
        print("PROBE — metadata das series Haver fornecidas")
        print("=" * 78)
        meta = probe_metadata(session, PROBE_IDS)
        print(meta.to_string(index=False))
        print()

        if args.probe:
            print("[--probe] saindo sem comparar.")
            return

        if not MAPPING:
            print("[INFO] MAPPING vazio — edite o dict no topo do script com "
                  "{nossa_cat: haver_series_id} e rode de novo.")
            return

        print("=" * 78)
        print(f"COMPARAÇÃO — janela últimos {args.window} meses")
        print("=" * 78)

        rows = []
        for cat, hid in MAPPING.items():
            ours = fetch_our_sa(session, cat)
            theirs = fetch_series(session, hid)
            if ours is None:
                print(f"[SKIP] {cat}: nossa SA nao encontrada no SQL "
                      f"(haver_code LIKE 'PARETO_IPCA:{cat}/V63/RECON-%/SA')")
                continue
            if theirs is None:
                print(f"[SKIP] {cat} ↔ haver {hid}: Haver vazio.")
                continue
            res = compare(ours, theirs, args.window)
            if res is None:
                print(f"[SKIP] {cat} ↔ haver {hid}: zero overlap de datas.")
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
            print(f"\n[{cat} ↔ haver {hid}] overlap {res['n_overlap']} obs "
                  f"({res['first_overlap'].date()} → {res['last_overlap'].date()})")
            print(f"  janela {res['n_window']}m: "
                  f"mean|d|={res['mean_abs_d']:.4f}, max|d|={res['max_abs_d']:.4f}, "
                  f"bias={res['bias']:+.4f}, corr={res['corr']:.4f}")
            print(f"  ultimos 12 diffs (ours-haver): {res['last_12_diff']}")

        if rows:
            print("\n" + "=" * 78)
            print("TABELA MARKDOWN (pra colar em relatorio)")
            print("=" * 78)
            df_out = pd.DataFrame(rows)
            print(df_out.to_markdown(index=False))
    finally:
        session.close()


if __name__ == "__main__":
    main()
