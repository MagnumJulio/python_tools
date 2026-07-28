# pareto_ipca15 — pipeline R IBGE-only para reconstrução de agregações IPCA-15

Fork do `pareto_ipca` para o **IPCA-15** (preview de meio de mês do IPCA, publicado ~dia 24 do mês de referência — adianta o IPCA cheio). Reconstrói o **headline (`total`) + 43 séries** derivadas (administrados, livres, industriais, serviços, alimentação no domicílio, núcleos, decomposições por processamento e por comercialização + os 9 grupos IPCA G1-G9 + alim_fora SG12, higiene_pessoal SG63, energia_eletrica I2202, passagem_aerea/auto_novo/auto_usado subitens), **100% a partir de IBGE/SIDRA**. Grupos e subgrupos/itens/subitens específicos são extraídos direto do SIDRA (não recon Laspeyres) — IBGE publica esses agregados prontos via `classificacao=315[all]`. Objetivo: entregar os números no mesmo dia do release IBGE.

**Metodologia base**: mesma NT_57/Dez-2025 do IPCA cheio — as fórmulas (Laspeyres com pesos mensais, MA/MS/DP, EX0/EX3/EX1/EX-FE, P55, difusão) são idênticas; muda só a fonte SIDRA (tabelas IPCA-15 em vez das do IPCA cheio).

**Princípio cardinal**: tudo que é servido vem do IBGE. BCB é só pra conferir — e **o BCB só publica IPCA-15 como SGS pro headline (código 7478)**. Nenhum breakdown do IPCA-15 (admin, livres, industr, serv, núcleos, …) tem código SGS dedicado. Descoberto por sondagem sistemática 2026-07-27 (`_probe_score.py` sobre ~230 SGS candidatos): único MATCH forte é `total`=7478 (corr=1.0000, mean|d|=0.00pp); demais candidatos são SGS do IPCA CHEIO com corr 0.75-0.96 (gap metodológico IPCA-15 vs IPCA cheio, não código IPCA-15). Portanto o `reconstruct_ipca.R` seção [5] só valida `total` vs SGS 7478 — o gap-diagnóstico contra SGS de IPCA cheio fica em `_audit_ibge_vs_bcb.R`, rodado sob demanda fora do pipeline.

## Estrutura

```
pareto_ipca15/
├── data/                        # gerada em runtime (não commitada)
│   ├── ipca15_pareto_recon.csv    # long: date, category_code, value (variação mensal)
│   ├── ipca15_pareto_indice.csv   # long: date, category_code, index (base dez/2012=100)
│   └── ipca15_pareto_pesos.csv    # long: date, category_code, value (peso Laspeyres)
├── scripts/
│   ├── seed_ibge_history.R      # ⭐ caminho principal: stitching T1705+T7062
│   ├── reconstruct_ipca.R       # core: recon de uma janela via qualquer SIDRA
│   ├── build_pareto_indice.R    # converte variações em número-índice
│   ├── proxy_config.R           # opcional: proxy corporativo (no-op em casa)
│   ├── seed_pareto_history.R    # LEGADO (herdado): seed via BCB SGS (SGS de IPCA cheio; NÃO usar sem remapping)
│   ├── ipca_masks/
│   │   ├── administrados.csv
│   │   ├── classificacao.csv          # POF 2017-18 (377 subitens)
│   │   └── classificacao_extended.csv # POF 2002-03 + 2008-09 + 2017-18 (478)
│   ├── outputs/                 # gerada em runtime (recon + auditoria + validação)
│   └── _audit_*.R / _probe_*.R  # scripts de diagnóstico (não compõem pipeline; SGS ainda de IPCA cheio)
└── script_itau/                 # integração com SQL corp Itaú (padrão EAV)
    ├── sidra_itau.ipynb         # referência: notebook original com sidra_to_sql/OPT_Macro_*
    ├── load_pareto_to_sql.py    # corp-only: carrega no SQL via opt_utils.SQLConnector
    ├── simulate_pareto_to_sql.py# casa: mesma lógica em DataFrames (MockSQLConnector)
    ├── sim_output/              # gerada por --save (CSVs imitando as 2 tabelas SQL)
    └── RUNBOOK.md               # procedimento controlado em 6 estágios pra rodar no corp
```

## Pipeline de produção (ordem)

```bash
cd pareto_ipca15
Rscript scripts/seed_ibge_history.R            # 1) stitching IBGE 2012-02 → atual (~40s)
Rscript scripts/build_pareto_indice.R          # 2) número-índice rebased dez/2012=100
```

Atualização incremental (só janela recente, sem rebuild histórico):
```bash
Rscript scripts/reconstruct_ipca.R             # default últimos 24 meses (T7062), SEM BCB
Rscript scripts/build_pareto_indice.R
```

Carga no SQL corp (Itaú, só roda na rede interna com `opt_utils` disponível):
```bash
python script_itau/load_pareto_to_sql.py             # NSA: var + idx das séries
python script_itau/load_pareto_to_sql.py --sa        # adiciona versão SA (X-13)
python script_itau/load_pareto_to_sql.py --dry-run   # só lista o que faria
```
Grava em `OPT_Macro_Series_2` (metadados) + `OPT_Macro_Series_Data_2` (long EAV: `date, series_id, value, release_date, vintage_date`). Cada categoria vira 4 séries NSA (var, idx, Weight×2); com `--sa`, vira 6 (adiciona var+idx SA). Weight duplicado: mesmo array gravado 2× com `series_name=label` (par com var) e `series_name="{label} (Indice)"` (par com idx), ambos `data_type="Weight"`. Frontend capta o peso via casamento `series_name+country+indicator`.

**Namespace disjunto do IPCA cheio**: `bls_code='IPCA15:{cat}'`, `indicator='IPCA-15'`, `series_name='IPCA-15: {label}'`. Não há risco de colisão com rows do `pareto_ipca` no mesmo SQL. Migração `_migrate_ipca15_to_current` filtra estritamente por `IPCA15:%`/`PARETO_IPCA15:%` — nunca toca IPCA cheio.

Simulação local (sem `opt_utils`/SQL — útil pra testar mapping em casa):
```bash
python script_itau/simulate_pareto_to_sql.py                       # roda todas as cats do CSV
python script_itau/simulate_pareto_to_sql.py --only livres,nucleo_ex0
python script_itau/simulate_pareto_to_sql.py --save                 # CSVs em sim_output/
```
Trocar `MockSQLConnector` por `SQLConnector(connector="pyodbc")` no corp é a única diferença lógica entre os dois scripts.

**Política de merge**: `reconstruct_ipca.R` sobrescreve qualquer período coberto pelo run atual e preserva o restante. `seed_ibge_history.R` orquestra 2 chamadas ao recon (uma por tabela SIDRA IPCA-15), cada uma com sua janela e máscara apropriada.

## Stitching das 2 tabelas SIDRA IPCA-15

Duas tabelas IBGE/SIDRA expõem V63 (variação mensal) e V66 (peso mensal) por subitem com classificação 315 no universo IPCA-15:

| Tabela | POF | Janela | Máscara |
|---|---|---|---|
| T1705 | 2008-2009 | 2012-02 → 2020-01 | `classificacao_extended.csv` |
| T7062 | 2017-2018 | 2020-02 → atual    | `classificacao.csv` |

A `extended` mask inclui subitens extintos em POF 2017-18 (feijão branco, abóbora, chuchu, gelatina, fralda, cabeleireiro, cinema, etc.) — necessária pra cobrir 100% do peso em T1705.

**Pré-2012-02**: IBGE **não publica V66 IPCA-15 por subitem**. T3065 é só headline histórico do IPCA-15 (sem classificação 315). Sem pesos, Laspeyres é impossível — gap real, não há como reconstruir. Diferente do IPCA cheio (que cobre 2006-07 → atual via T2938+T1419+T7060), o IPCA-15 tem janela mais curta.

## Cobertura

Todas as categorias começam **2012-02** (T1705). Base do índice: **dez/2012=100** (primeira dez/ comum na janela IPCA-15). `nucleo_medio` começa alguns meses depois (warm-up DP 6m).

## Validação contra BCB

**Único SGS IPCA-15 no BCB**: 7478 (headline). Sonda 2026-07-27 confirmou que breakdowns do IPCA-15 não têm código SGS público.

- `reconstruct_ipca.R` seção [5] valida `total` vs SGS 7478 — mean|d| ~0.00pp esperado. É a única checagem BCB do pipeline principal.
- `_audit_ibge_vs_bcb.R` é opcional / sob demanda: repete [A] o headline vs SGS 7478 e ainda faz [B] diagnóstico do gap (breakdowns nossos vs SGS IPCA cheio — mean|d| ~0.1-0.4pp esperado, NÃO é erro da recon). Não faz parte do pipeline de produção.
- **Rotina de atualização roda muda por default** (sem fetch BCB). Pra validar sob demanda passe `--with-bcb` (ou rode `_audit_ibge_vs_bcb.R`, que sempre faz o headline check).

## Algebra do `reconstruct_ipca.R`

Laspeyres com pesos mensais do próprio IBGE:
```
v_classe  = Σ(w_i × v_i, i ∈ classe)  /  Σ(w_i, i ∈ classe)
p_classe  = Σ(w_i, i ∈ classe)
v_livres  = (v_ipca15 × Σw - v_admin × p_admin) / p_livres   (controle algébrico)
```
Validação primária: somando todos os subitens com pesos próprios, deve dar o IPCA-15 geral publicado pelo IBGE até erro de arredondamento na 2ª/3ª decimal.

Núcleos estatísticos (MA/MS/DP) usam algoritmos próprios (média truncada 20/80, com suavização 12m em subitens listados pra MS, ou re-pesagem por inverso de volatilidade pra DP) — as mesmas definições operacionais do BCB da NT_57.

## Convenções dos scripts

- **Auto-cwd**: todo script descobre a raiz do projeto via `--file=` e faz `setwd()`. Funciona de qualquer pasta de invocação.
- **Parametrização do recon**: `reconstruct_ipca.R` aceita env vars `SIDRA_AGG_ID` (tabela) e `MASK_CLASS_PATH_OVR` (máscara). Default da tabela mudou pra **T7062** (analog IPCA-15 do T7060).
- **Proxy opcional**: `proxy_config.R` é sourceado se existir. Sem o arquivo (rodando em casa) vira no-op.
- **Comentários em português**, terse, com `# Por que:` explicando decisões não-óbvias.
- **Pacotes**: só `httr` e `jsonlite` (base R pra resto). Sem `tidyverse`.

## Índice — base

`build_pareto_indice.R` faz rebase em **dez/2012=100** (primeira dez/ comum a todas as séries IPCA-15, dado que T1705 começa fev/2012). Se por algum motivo falhar, mantém base 100 no primeiro mês.

## Diferenças versus `pareto_ipca` (referência do fork)

| Item | pareto_ipca (IPCA cheio) | pareto_ipca15 |
|---|---|---|
| Tabelas SIDRA | T2938 + T1419 + T7060 | T1705 + T7062 |
| Janela | 2006-07 → atual | 2012-02 → atual |
| Base do índice | dez/2006=100 | dez/2012=100 |
| `bls_code` | `IPCA:{cat}` | `IPCA15:{cat}` |
| `indicator` SQL | `IPCA` | `IPCA-15` |
| `series_name` prefixo | `IPCA: ` | `IPCA-15: ` |
| Auditoria BCB | ativa (SGS breakdown mapeados) | só headline vs SGS 7478; breakdowns viram diagnóstico do gap vs IPCA cheio |
| Publicação IBGE | ~dia 8-10 do mês seguinte | ~dia 24 do mês de referência |

## Referências externas

- IBGE SIDRA API v3: `https://servicodados.ibge.gov.br/api/v3/agregados/<TBL>/periodos/<P>/variaveis/<V>?localidades=N1[all]&classificacao=315[all]`
- T1705 / T7062 (IPCA-15): variáveis V63 / V66, classificação 315
- BCB API SGS: `https://api.bcb.gov.br/dados/serie/bcdata.sgs.<CODE>/dados?formato=json` (único IPCA-15: `7478` = headline)
