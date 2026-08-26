# RUNBOOK — atualização rápida IPCA-15 (21 cats, --no-bcb)

Copy-paste sequencial pra rodar no corp. Escopo: **21 categorias específicas** (sem núcleos, sem `nucleo_medio`/`nucleo_dp` — não precisa dos fixes DP/medio). Único risco de SA bugado nesse subset é `servicos` — step 6 cobre.

Tempo esperado end-to-end: **~1-2 min**.

## 0. Pré-requisitos

- Estar dentro do corp (VPN/rede interna) — `opt_utils` disponível
- Working dir = raiz do fork
- CSV atual em `data/` (será sobrescrito pelo step 2)

```bash
cd pareto_ipca15
```

## 1. Rebuild recente do SIDRA (últimos 24 meses)

```bash
Rscript scripts/reconstruct_ipca.R --no-bcb
```
Esperado: `~5s`. Output em `data/ipca15_pareto_recon.csv` + `data/ipca15_pareto_pesos.csv`. Se der erro de rede SIDRA, tentar de novo — SIDRA às vezes engasga.

## 2. Rebase do índice

```bash
Rscript scripts/build_pareto_indice.R
```
Esperado: `<1s`. Output em `data/ipca15_pareto_indice.csv`.

## 3. Dry-run da carga (checa o que vai escrever)

```bash
python script_itau/load_pareto_to_sql.py --only total,alim_e_bebidas,alim_domicilio,alim_fora,habitacao,energia_eletrica,artigos_residencia,vestuario,transportes,passagem_aerea,auto_novo,auto_usado,gasolina,saude,higiene_pessoal,despesas_pessoais,educacao,comunicacao,administrados,industriais,servicos --dry-run
```
Deve listar as **21 categorias** com `var: 174 obs   idx: 174 obs   Weight x2: 174 obs`. Se faltar alguma, checar CSV gerado no step 1.

## 4. Load NSA (var + idx + Weight x2)

```bash
python script_itau/load_pareto_to_sql.py --only total,alim_e_bebidas,alim_domicilio,alim_fora,habitacao,energia_eletrica,artigos_residencia,vestuario,transportes,passagem_aerea,auto_novo,auto_usado,gasolina,saude,higiene_pessoal,despesas_pessoais,educacao,comunicacao,administrados,industriais,servicos
```
Confirmar na prompt (ou `--no-confirm` pra pular). Esperado: `~15-30s`.

## 5. Load SA (X-13 nas 21)

```bash
python script_itau/load_pareto_to_sql.py --only total,alim_e_bebidas,alim_domicilio,alim_fora,habitacao,energia_eletrica,artigos_residencia,vestuario,transportes,passagem_aerea,auto_novo,auto_usado,gasolina,saude,higiene_pessoal,despesas_pessoais,educacao,comunicacao,administrados,industriais,servicos --sa
```
Esperado: `~30-60s` (X-13 é o gargalo). Se X-13 falhar em alguma série, ela cai em passthrough (idx SA = idx NSA) — verificar no log.

## 6. FIX obrigatório — `servicos` idx SA (bug conhecido)

Wrapper corp bugado sobrescreve `servicos` idx SA com TD peak. Corrige recalculando idx SA a partir do var SA gravado no SQL:

```bash
python script_itau/_fix_servicos_idx_sa.py
```
Esperado: `~5-15s`. Só toca a série `IPCA-15: Servicos (Indice) [SA]` — não mexe em NSA nem nas outras 20.

## 7. Sanity check

```bash
python script_itau/inspect_pareto.py --only total,servicos,administrados,industriais,alim_domicilio
```
Confere último ponto (Jul-2026) das 5 macro. Compara mental com print Itaú:
- `total` = 0.06%
- `administrados` ≈ 0.37%
- `alim_domicilio` ≈ -1.14%
- `industriais` ≈ -0.01%
- `servicos` ≈ 0.41%

Se bater → done. Se divergir → rodar step 1 de novo (SIDRA pode ter dado dados truncados).

---

## Rollback / troubleshooting

- **Erro rede SIDRA no step 1**: re-rodar. Se persistir, checar proxy corp (`scripts/proxy_config.R`).
- **X-13 fail em série específica no step 5**: passthrough é aceitável, log diz qual série. Se `servicos` cair em passthrough, step 6 corrige mesmo assim.
- **`--only` não achou alguma cat**: nome errado — categorias válidas listadas em `script_itau/load_pareto_to_sql.py:CATEGORY_LABELS`.
- **SQL row conflict**: `_migrate_ipca15_to_current` roda antes do main loop e normaliza rows antigas — idempotente.

## Categorias NÃO cobertas neste run

Este runbook cobre **21 cats** (macro + grupos IPCA + subitens de interesse). Ficam de fora:
- Núcleos: `nucleo_ex0/ex3/ms/dp/p55/medio/exfe/ex1`, `ex3_serv`, `ex3_ind`
- Decomposições: `livres`, `duraveis`, `semiduraveis`, `ndur_industr`, `comerc`, `ncomerc`
- Alimentos por processamento: `alim_in_natura`, `alim_semi_elab`, `alim_industr`
- Serviços subj/exsubj, difusão

Pra full load, remover `--only` no step 4 e 5. Nesse caso também rodar `_sa_dp_nucleo_medio.R` + `_fix_dp_medio_sa.py` + `_fix_nucleo_medio_sa.py` (fixes DP/medio SA).
