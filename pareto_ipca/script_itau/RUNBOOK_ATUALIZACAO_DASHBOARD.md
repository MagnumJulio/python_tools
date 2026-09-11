# RUNBOOK — atualização rápida IPCA (21 cats dashboard)

Copy-paste sequencial pra release day. Espelha o `pareto_ipca15/script_itau/RUNBOOK_ATUALIZACAO_21_CATS.md`, mas pro IPCA cheio. Escopo: **21 categorias específicas do dashboard** (sem núcleos, sem `nucleo_medio`/`nucleo_dp` — não precisa dos fixes DP/medio). Único risco de SA bugado nesse subset é `servicos` — step 6 cobre.

Tempo esperado end-to-end: **~2-3 min** (IPCA cheio tem janela maior que IPCA-15).

## 0. Pré-requisitos

- Estar no corp (VPN/rede interna) — `opt_utils` disponível
- Working dir = raiz do pareto_ipca
- CSV atual em `data/` (será sobrescrito pelo step 1)

```bash
cd pareto_ipca
```

## 1. Rebuild recente do SIDRA (últimos 24 meses)

```bash
Rscript scripts/reconstruct_ipca.R --no-bcb
```
Esperado: `~10-15s`. Output em `data/ipca_pareto_recon.csv` + `data/ipca_pareto_pesos.csv`. `--no-bcb` pula validação vs SGS (evita ruído/timeout em release day se API BCB estiver com problema). Se der erro SIDRA, retentar.

## 2. Rebase do índice

```bash
Rscript scripts/build_pareto_indice.R
```
Esperado: `<5s`. Output em `data/ipca_pareto_indice.csv`. Já traz o fix da difusão (idx = valor natural, sem overflow).

## 3. Dry-run da carga (checa o que vai escrever)

```bash
python script_itau/load_pareto_to_sql.py --only total,alim_e_bebidas,alim_domicilio,alim_fora,habitacao,energia_eletrica,artigos_residencia,vestuario,transportes,passagem_aerea,auto_novo,auto_usado,gasolina,saude,higiene_pessoal,despesas_pessoais,educacao,comunicacao,administrados,industriais,servicos --dry-run
```
Deve listar as **21 categorias** com `idx: 240 obs   Weight: 240 obs`. Se faltar alguma, checar CSV gerado no step 1.

## 4. Load NSA (idx + Weight)

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
Esperado: `~5-15s`. Só toca a série `IPCA: Servicos (Indice) [SA]` — não mexe em NSA nem nas outras 20.

## 7. Sanity check

```sql
-- Confere último ponto (NSA) das 5 macro:
SELECT s.series_name, MAX(d.date) AS last_date, d.value
FROM OPT_Macro_Series_2 s
JOIN OPT_Macro_Series_Data_2 d ON d.series_id = s.series_id
WHERE s.bls_code IN ('IPCA:total','IPCA:servicos','IPCA:administrados','IPCA:industriais','IPCA:alim_domicilio')
  AND s.data_type = 'NSA'
GROUP BY s.series_name, d.value
HAVING MAX(d.date) = (SELECT MAX(date) FROM OPT_Macro_Series_Data_2 d2
                     JOIN OPT_Macro_Series_2 s2 ON s2.series_id = d2.series_id
                     WHERE s2.bls_code LIKE 'IPCA:%');
-- Compara mental com print do release IBGE.
```

Se bater → done. Se divergir → rodar step 1 de novo (SIDRA às vezes retorna dados truncados no minuto do release).

---

## Rollback / troubleshooting

- **Erro rede SIDRA no step 1**: re-rodar. Se persistir, checar proxy corp (`scripts/proxy_config.R`).
- **X-13 fail em série específica no step 5**: passthrough é aceitável, log diz qual série. Se `servicos` cair em passthrough, step 6 corrige mesmo assim.
- **`--only` não achou alguma cat**: nome errado — categorias válidas listadas em `script_itau/load_pareto_to_sql.py:CATEGORY_LABELS`.
- **SQL row conflict**: `_migrate_pareto_to_current` roda antes do main loop e normaliza rows antigas — idempotente.

## Categorias NÃO cobertas neste run

Este runbook cobre **21 cats do dashboard**. Ficam de fora as **23 restantes** (44 total):
- Núcleos: `nucleo_ex0/ex3/ma/ms/dp/p55/medio/exfe/ex1`, `ex3_serv`, `ex3_ind`, `difusao`
- Decomposições: `livres`, `duraveis`, `semiduraveis`, `ndur_industr`, `comerc`, `ncomerc`
- Alimentos por processamento: `alim_in_natura`, `alim_semi_elab`, `alim_industr`
- Serviços subj/exsubj: `servicos_subj`, `servicos_exsubj`

Pra full load, remover `--only` no step 4 e 5. Nesse caso também rodar `_sa_dp_nucleo_medio.R` + `_fix_dp_medio_sa.py` + `_fix_nucleo_medio_sa.py` (fixes DP/medio SA — ver `RUNBOOK.md` Estágio 5.1).
