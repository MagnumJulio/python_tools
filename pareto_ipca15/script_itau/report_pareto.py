#!/usr/bin/env python
# report_pareto.py
# Relatorio automatico das series PARETO IPCA: ultimo release, peso e MAE vs BCB.
# Deterministico para series conhecidas. Avisa sobre intervencao de agente
# se surgir categoria nao mapeada nos CSVs de dados.
#
# MAE computado contra BCB SGS via API BCB; usa janela de sobreposicao
# entre os CSVs PARETO e as series SGS.
#
# Uso:
#   cd pareto_ipca
#   python script_itau/report_pareto.py
#   python script_itau/report_pareto.py --window 60   # ultimos N meses
#   python script_itau/report_pareto.py --cached       # usa ipca_validacao_bcb.csv local

import argparse
import sys
from pathlib import Path
from datetime import date

import pandas as pd

try:
    import requests
except ImportError:
    requests = None

ROOT    = Path(__file__).resolve().parent.parent
VAR_CSV = ROOT / "data" / "ipca15_pareto_recon.csv"
PESO_CSV = ROOT / "data" / "ipca15_pareto_pesos.csv"
CACHED_VAL_CSV = ROOT / "scripts" / "outputs" / "ipca_validacao_bcb.csv"

# Mapeamento deterministico: category_code → SGS BCB
SGS_MAP = {
    "administrados":   4449,
    "livres":          11428,
    "industriais":     27863,
    "servicos":        10844,
    "alim_domicilio":  27864,
    "nucleo_ex0":      11427,
    "nucleo_ex3":      27839,
    "duraveis":        10843,
    "semiduraveis":    10842,
    "servicos_subj":   29683,
    "comerc":          4447,
    "ncomerc":         4448,
    "nucleo_ma":       11426,
    "nucleo_ms":       4466,
    "nucleo_dp":       16122,
    "nucleo_exfe":     28751,
    "nucleo_ex1":      16121,
    "ex3_ind":         29684,
    "difusao":         21379,
    "nucleo_p55":      28750,
}

# Series sem par BCB — documentadas, nao e erro
NO_SGS = {
    "ndur_industr":      "sem SGS BCB (SGS 10841 = bens nao-duráveis, universo diferente)",
    "servicos_exsubj":   "sem SGS BCB direto",
    "alim_in_natura":    "BCB nao publica (varredura 190 SGS: 0 hits)",
    "alim_semi_elab":    "BCB nao publica (varredura 190 SGS: 0 hits)",
    "alim_industr":      "BCB nao publica (varredura 190 SGS: 0 hits)",
    "ex3_serv":          "SGS 29683 = servicos_subj (c/ alim_fora), nao ex3_serv estrito (MAE=0.10 vs 0.024 do serv_subj)",
    "nucleo_medio":      "sem SGS BCB (media dos 5 nucleos, calculada internamente)",
}

CATEGORY_LABELS = {
    "administrados":   "Monitorados",
    "livres":          "Livres",
    "industriais":     "Industriais",
    "servicos":        "Servicos",
    "alim_domicilio":  "Alim. Domicilio",
    "nucleo_ex0":      "Nucleo EX0",
    "nucleo_ex3":      "Nucleo EX3",
    "duraveis":        "Bens Duraveis",
    "semiduraveis":    "Bens Semiduraveis",
    "ndur_industr":    "ND Industriais",
    "servicos_subj":   "Serv. Subjacentes",
    "servicos_exsubj": "Serv. Ex-Subj.",
    "alim_in_natura":  "Alim. In Natura",
    "alim_semi_elab":  "Alim. Semi-Elab.",
    "alim_industr":    "Alim. Industr.",
    "comerc":          "Comercializaveis",
    "ncomerc":         "Nao-Comercializaveis",
    "nucleo_ma":       "Nucleo MA",
    "nucleo_ms":       "Nucleo MS",
    "nucleo_dp":       "Nucleo DP",
    "nucleo_exfe":     "Nucleo EX-FE",
    "nucleo_ex1":      "Nucleo EX1",
    "ex3_serv":        "EX3 Servicos",
    "ex3_ind":         "EX3 Industriais",
    "difusao":         "Difusao",
    "nucleo_p55":      "Nucleo P55",
    "nucleo_medio":    "Nucleo Medio",
}

# Grupos para organizar a saida
GROUPS = [
    ("Agregacoes primarias BCB",
     ["administrados", "livres", "industriais", "servicos", "alim_domicilio"]),
    ("Durabilidade",
     ["duraveis", "semiduraveis", "ndur_industr"]),
    ("Comercializabilidade",
     ["comerc", "ncomerc"]),
    ("Servicos",
     ["servicos_subj", "servicos_exsubj"]),
    ("Alimentos por processamento",
     ["alim_in_natura", "alim_semi_elab", "alim_industr"]),
    ("Nucleos por exclusao",
     ["nucleo_ex0", "nucleo_ex1", "nucleo_exfe", "nucleo_ex3", "ex3_serv", "ex3_ind"]),
    ("Nucleos estatisticos",
     ["nucleo_ma", "nucleo_ms", "nucleo_dp", "nucleo_p55", "nucleo_medio"]),
    ("Difusao",
     ["difusao"]),
]


def _fetch_bcb_sgs(code: int, window_months: int | None = None) -> pd.Series:
    if requests is None:
        raise ImportError("requests nao instalado: pip install requests")
    url = f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.{code}/dados?formato=json"
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    data = r.json()
    def _safe_float(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return float("nan")

    s = pd.Series(
        {pd.to_datetime(d["data"], dayfirst=True): _safe_float(d["valor"]) for d in data},
        dtype=float,
    )
    s.index = pd.to_datetime(s.index) + pd.offsets.MonthEnd(0)
    s = s.sort_index()
    if window_months:
        s = s.iloc[-window_months:]
    return s


def _load_pareto(path: Path, value_col: str) -> dict[str, pd.Series]:
    if not path.exists():
        return {}
    df = pd.read_csv(path)
    df["date"] = pd.to_datetime(df["date"]) + pd.offsets.MonthEnd(0)
    out = {}
    for cat, g in df.groupby("category_code"):
        s = g.set_index("date")[value_col].sort_index().astype(float)
        out[cat] = s
    return out


def _mae(s1: pd.Series, s2: pd.Series) -> tuple[float, int]:
    common = s1.index.intersection(s2.index)
    if len(common) == 0:
        return float("nan"), 0
    diff = (s1.loc[common] - s2.loc[common]).dropna()
    return diff.abs().mean(), len(diff)


def _cached_mae(cat: str, val_df: pd.DataFrame) -> tuple[float, int] | None:
    col = f"diff_{cat}"
    # Handle naming mismatches
    aliases = {
        "alim_domicilio": "diff_alim_dom",
        "duraveis": "diff_duravel",
        "semiduraveis": "diff_semidur",
        "nucleo_ex0": "diff_nucleo_ex0",
        "nucleo_ex3": "diff_nucleo_ex3",
        "servicos_subj": "diff_serv_subj",
        "servicos": "diff_serv",
        "nucleo_ma": "diff_nucleo_ma",
        "nucleo_ms": "diff_nucleo_ms",
        "nucleo_dp": "diff_nucleo_dp",
        "nucleo_exfe": "diff_nucleo_exfe",
        "nucleo_ex1": "diff_nucleo_ex1",
        "ex3_ind":   "diff_ex3_ind",
        "ex3_serv":  "diff_ex3_serv",
        "difusao":   "diff_difusao",
        "nucleo_p55": "diff_nucleo_p55",
    }
    col = aliases.get(cat, f"diff_{cat}")
    if col not in val_df.columns:
        return None
    s = val_df[col].dropna()
    return s.abs().mean(), len(s)


def main():
    parser = argparse.ArgumentParser(description="Relatorio PARETO IPCA")
    parser.add_argument("--window", type=int, default=None,
                        help="Ultimos N meses para calculo do MAE (default: todos)")
    parser.add_argument("--cached", action="store_true",
                        help="Usa ipca_validacao_bcb.csv local ao inves de buscar BCB")
    args = parser.parse_args()

    print(f"[1] Lendo {VAR_CSV.relative_to(ROOT)}...")
    var_data = _load_pareto(VAR_CSV, "value")
    if not var_data:
        sys.exit(f"CSV nao encontrado: {VAR_CSV}. Rode o pipeline R primeiro.")

    print(f"[2] Lendo {PESO_CSV.relative_to(ROOT)}...")
    peso_data = _load_pareto(PESO_CSV, "value")

    # Detecta categorias novas (nao mapeadas) — pede intervencao de agente
    all_known = set(SGS_MAP) | set(NO_SGS)
    new_cats = set(var_data) - all_known
    for cat in sorted(new_cats):
        print(f"\n⚠️  NOVA SERIE DETECTADA: '{cat}'")
        print(f"   Nao consta em SGS_MAP nem NO_SGS de report_pareto.py.")
        print(f"   NECESSARIA INTERVENCAO DE AGENTE: verificar SGS BCB e atualizar mapeamento.")

    # Carrega MAE
    val_df = None
    if args.cached and CACHED_VAL_CSV.exists():
        print(f"[3] Usando cache: {CACHED_VAL_CSV.relative_to(ROOT)}")
        val_df = pd.read_csv(CACHED_VAL_CSV)
    elif not args.cached and requests is not None:
        print("[3] Buscando dados BCB SGS via API...")
    else:
        print("[3] requests nao disponivel e --cached nao especificado; MAE indisponivel.")

    today = date.today().strftime("%Y-%m-%d")
    print(f"\n{'='*80}")
    print(f" PARETO IPCA — Relatorio de series  ({today})")
    print(f"{'='*80}")
    print(f"{'Serie':<28} {'Ultimo':>8} {'Var':>7} {'Peso':>7}  {'MAE BCB':>9}  {'N':>5}  SGS")
    print(f"{'-'*80}")

    for group_name, cats in GROUPS:
        print(f"\n{group_name}:")
        for cat in cats:
            if cat not in var_data:
                continue
            sv = var_data[cat]
            last_date = sv.index.max()
            last_val  = sv.iloc[-1]
            last_peso = peso_data.get(cat)
            peso_str  = f"{last_peso.iloc[-1]:.2f}" if last_peso is not None else "  N/A"

            # MAE
            if cat in NO_SGS:
                mae_str = "   N/A"
                n_str   = "     "
                sgs_str = NO_SGS[cat]
            elif cat in SGS_MAP:
                sgs_code = SGS_MAP[cat]
                mae_val = None
                n_obs   = 0
                if val_df is not None:
                    result = _cached_mae(cat, val_df)
                    if result:
                        mae_val, n_obs = result
                elif requests is not None:
                    try:
                        bcb_s = _fetch_bcb_sgs(sgs_code, args.window)
                        pareto_s = sv.copy()
                        pareto_s.index = pareto_s.index + pd.offsets.MonthEnd(0)
                        if args.window:
                            pareto_s = pareto_s.iloc[-args.window:]
                        mae_val, n_obs = _mae(pareto_s, bcb_s)
                    except Exception as e:
                        mae_val = float("nan")
                        n_obs = 0
                mae_str = f"{mae_val:.4f}" if mae_val is not None and not (mae_val != mae_val) else "  err "
                n_str   = str(n_obs)
                sgs_str = str(sgs_code)
            else:
                mae_str = "  ???  "
                n_str   = ""
                sgs_str = "INTERV.AGENTE"

            label = CATEGORY_LABELS.get(cat, cat)
            print(
                f"  {label:<26} {last_date.strftime('%Y-%m'):>8} "
                f"{last_val:>7.3f} {peso_str:>7}  {mae_str:>9}  {n_str:>5}  {sgs_str}"
            )

    print(f"\n{'='*80}")
    if val_df is not None:
        first_p = val_df.iloc[0].get("periodo", "?")
        last_p  = val_df.iloc[-1].get("periodo", "?")
        print(f"MAE computado sobre janela: {first_p} → {last_p} (cache local)")
    elif requests is not None and not args.cached:
        print("MAE computado sobre sobreposicao PARETO x BCB SGS (via API BCB).")
    print(f"Peso = peso Laspeyres do mes mais recente disponivel.")
    print(f"Para MAE historico completo: rode _audit_ibge_vs_bcb.R e use --cached.")


if __name__ == "__main__":
    main()
