# pareto_ipca — pipeline R IBGE-only para reconstrução de agregações IPCA

Reconstrói, em R, o **IPCA headline (`total`) + 27 séries** derivadas do IPCA que o BCB publica (administrados, livres, industriais, serviços, alimentação no domicílio, núcleos, decomposições por processamento e por comercialização), **100% a partir de IBGE/SIDRA**. BCB SGS é usado apenas em scripts de auditoria pra validar a recon. Objetivo: entregar os números no mesmo dia do release IBGE (BCB só publica D+1) com metodologia única em toda a janela disponível.

**Metodologia base**: BCB NT_57/Dez-2025 ("Núcleos de inflação, séries por exclusão e outras agregações analíticas do IPCA"). É a nota consolidada mais recente publicada pelo BC. Implementação fiel das fórmulas das Seções 2.1.1, 2.2, 2.3, 2.4, 2.6 (apenas EX2 ainda não implementado por exigir listas dos RIs set/2016 e jun/2018).

**Princípio cardinal**: tudo que é servido vem do IBGE. BCB é só pra conferir o que foi montado a partir do IBGE.

## Estrutura

```
pareto_ipca/
├── data/                        # gerada em runtime (não commitada)
│   ├── ipca_pareto_recon.csv    # long: date, category_code, value (variação mensal)
│   └── ipca_pareto_indice.csv   # long: date, category_code, index (base dez/2006=100)
├── scripts/
│   ├── seed_ibge_history.R      # ⭐ caminho principal: stitching T2938+T1419+T7060
│   ├── reconstruct_ipca.R       # core: recon de uma janela via qualquer SIDRA
│   ├── build_pareto_indice.R    # converte variações em número-índice
│   ├── proxy_config.R           # opcional: proxy corporativo (no-op em casa)
│   ├── seed_pareto_history.R    # LEGADO: seed via BCB SGS (substituído)
│   ├── ipca_masks/
│   │   ├── administrados.csv
│   │   ├── classificacao.csv          # POF 2017-18 (377 subitens)
│   │   └── classificacao_extended.csv # POF 2002-03 + 2008-09 + 2017-18 (478)
│   ├── outputs/                 # gerada em runtime (recon + auditoria + validação)
│   └── _audit_*.R / _probe_*.R  # scripts de diagnóstico (não compõem pipeline)
└── script_itau/                 # integração com SQL corp Itaú (padrão EAV)
    ├── sidra_itau.ipynb         # referência: notebook original com sidra_to_sql/OPT_Macro_*
    ├── load_pareto_to_sql.py    # corp-only: carrega no SQL via opt_utils.SQLConnector
    ├── simulate_pareto_to_sql.py# casa: mesma lógica em DataFrames (MockSQLConnector)
    ├── sim_output/              # gerada por --save (CSVs imitando as 2 tabelas SQL)
    └── RUNBOOK.md               # procedimento controlado em 5 estágios pra rodar no corp
```

## Pipeline de produção (ordem)

```bash
cd pareto_ipca
Rscript scripts/seed_ibge_history.R     # 1) stitching IBGE 2006-07 → atual (~50s)
Rscript scripts/build_pareto_indice.R   # 2) número-índice rebased dez/2006=100
```

Atualização incremental (só janela recente, sem rebuild histórico):
```bash
Rscript scripts/reconstruct_ipca.R              # default últimos 24 meses (T7060)
Rscript scripts/build_pareto_indice.R
```

Carga no SQL corp (Itaú, só roda na rede interna com `opt_utils` disponível):
```bash
python script_itau/load_pareto_to_sql.py             # NSA: var + idx das 20 séries
python script_itau/load_pareto_to_sql.py --sa        # adiciona versão SA (X-13)
python script_itau/load_pareto_to_sql.py --dry-run   # só lista o que faria
```
Grava em `OPT_Macro_Series_2` (metadados) + `OPT_Macro_Series_Data_2` (long EAV: `date, series_id, value, release_date, vintage_date`), mesmo padrão do `sidra_itau.ipynb`. Cada categoria vira 4 séries NSA (var, idx, Weight×2); com `--sa`, vira 6 (adiciona var+idx SA). Sync 2026-07-17: **Weight duplicado** — mesmo array gravado 2x com `series_name=label` (par com var) e `series_name="{label} (Indice)"` (par com idx), ambos `data_type="Weight"`. Frontend capta o peso via casamento `series_name+country+indicator`, trocando só `data_type`. Proveniência migrou do campo `haver_code` (formato antigo `PARETO_IPCA:<cat>/V63/RECON-<git-sha>`) pro campo **`bls_code`**; INSERTs novos não setam `haver_code` (o SQL preenche como `NULL` por default). **Sync 2026-07-27** (análogo ao CPI-US 2026-07-20): `bls_code` colapsado pra formato único `IPCA:<cat>` — o sufixo `/Index` foi eliminado. Distinção var-side vs idx-side agora sai só de `series_name` + `data_type`; 1 code por cat compartilhado por todas as 4-6 rows. Migração idempotente rodada antes do main loop (`_migrate_pareto_to_current`) cobre 3 estados coexistentes em prod: (0) ancestral `haver_code LIKE 'PARETO_IPCA:%'`, (1) intermediário `bls_code LIKE 'IPCA:%/Index'`, (2) atual `bls_code = 'IPCA:{cat}'` — o (0) e (1) sofrem `UPDATE` explícito `SET haver_code = NULL, bls_code = <novo colapsado>, data_type = 'Weight' se antes Peso`; (2) é pulado.

Simulação local (sem `opt_utils`/SQL — útil pra testar mapping em casa):
```bash
python script_itau/simulate_pareto_to_sql.py                       # roda todas as cats do CSV
python script_itau/simulate_pareto_to_sql.py --only livres,nucleo_ex0
python script_itau/simulate_pareto_to_sql.py --save                 # CSVs em sim_output/
```
`MockSQLConnector` mantém as 2 tabelas em DataFrames pandas, auto-incrementa `series_id` como SQL Server faria, e imprime preview + contagens. Trocar `MockSQLConnector` por `SQLConnector(connector="pyodbc")` no corp é a única diferença lógica entre os dois scripts. Smoke test full (27 categorias, 21 com Weight): **96 séries, 22 944 linhas** (2026-07-17).

**Política de merge**: `reconstruct_ipca.R` sobrescreve qualquer período coberto pelo run atual e preserva o restante. `seed_ibge_history.R` orquestra 3 chamadas ao recon (uma por tabela SIDRA), cada uma com sua janela e máscara apropriada.

## Stitching das 3 tabelas SIDRA

Três tabelas IBGE/SIDRA expõem V63 (variação mensal) e V66 (peso mensal) por subitem com classificação 315 (geral → grupos → subgrupos → itens → subitens):

| Tabela | POF | Janela | Máscara |
|---|---|---|---|
| T2938 | 2002-2003 | 2006-07 → 2011-12 | `classificacao_extended.csv` |
| T1419 | 2008-2009 | 2012-01 → 2019-12 | `classificacao_extended.csv` |
| T7060 | 2017-2018 | 2020-01 → atual    | `classificacao.csv` |

A `extended` mask inclui 101 subitens extintos em POF 2017-18 (feijão branco, abóbora, chuchu, gelatina, fralda, cabeleireiro, cinema, etc.) — necessária pra cobrir 100% do peso em T2938 e T1419 (sem ela, ficam 5.1–5.3% de peso não-classificado).

**Pré-2006-07**: IBGE não publica V66 (peso por subitem). T655 cobre 1999-08 → 2006-06 só com V63; T1737 vai até 1979 mas só agregados. Sem pesos, Laspeyres é impossível — gap real.

## Cobertura uniforme

Todas as 20 categorias têm **238 observações cobrindo 2006-07 → 2026-04** (atualizável). Metodologia idêntica em toda a janela — nenhuma série tem definição mista por período.

## Validação contra BCB (auditoria, não produção)

`_audit_ibge_vs_bcb.R` compara as **19 séries** que têm SGS BCB ao longo dos ~20 anos. Resultados pós-NT_57 (238 obs por série, 2006-07 → 2026-04):

| Grupo | Séries | mean\|d\| (pp) | Interpretação |
|---|---|---|---|
| Controles primários | alim_dom, industriais, duraveis, livres, **nucleo_ma**, **difusão** | 0.0024–0.0094 | Bate quase exato |
| Núcleos NT_57 | **nucleo_ex1**, **nucleo_exfe**, **ex3_ind**, **nucleo_ms** | 0.0027–0.0085 | Fórmulas NT_57 — bate quase exato |
| Controles secundários | admin, servicos, semidur, **nucleo_ex0/ex3**, **ex3_serv**, **nucleo_dp** | 0.011–0.024 | Diferenças marginais |
| Comerc/Ncomerc | comerc, ncomerc | 0.081, 0.084 | Bias ≈ 0 (simétrico). Piso residual: fronteira C/NC não publicada em detalhe subitem. |

**Núcleos estatísticos — nível ITEM (não subitem).** EE102/2021 nota 2 + NT_57 Sec 2.3-2.4: MA/MS operam a nível ITEM (51 itens, nchar=4). Validado empiricamente: trim 20/80 a nível item vs SGS 11426 — `mean|d|=0.0025pp, max|d|=0.0049pp`. Versão antiga (a nível subitem) tinha `mean|d|≈0.16pp`.

### MS — `mean|d|=0.0085pp` ✓ (NT_57 Sec 2.4 + Tabela 5)

Implementação fiel: 9 ITENS (`MS_ITEMS_SUAV` em `reconstruct_ipca.R:103`) com variação substituída pela **média geométrica 12m** `π_i^12m = 100·[Π(1+π/100)]^(1/12) − 1`, depois trim 20/80 a nível item.

Os 9 itens (Tabela 5 NT_57, estrutura jan/2020-presente): 2201, 2202, 5101, 5104, 7101, 7202, 8101, 8104, 9101.

Antes da migração pra NT_57 (2026-05-26): 28 subitens com média aritmética → `mean|d|=0.066pp, bias=-0.024`. Variantes testadas em `_probe_ms_dp_variantes.R` e `_probe_ms_hipoteses_estruturais.R` (mantidos pra histórico) ficaram travadas em `0.077` antes de descobrir NT_57.

### DP — `mean|d|=0.0174pp` ✓ (NT_57 Sec 2.2)

Sigma rolling 48m terminando em t-1, sobre a DIFERENÇA `(var_item_k − var_IPCA_cheio)`. Antes (sigma global do var_item puro): `mean|d|=0.037`. Warm-up: pros primeiros 47m usa janela expansiva com min 6 obs.

Pequeno resíduo restante (~0.017pp) provavelmente vem de: (1) warm-up incompleto antes de 2010-06; (2) NT_57 menciona "proxies" pras transições POF (Tabelas 2-4) que ainda não implementamos.

`alim_in_natura`, `alim_semi_elab`, `alim_industr`, `ndur_industr`, `servicos_subj`, `servicos_exsubj` **não têm SGS BCB direto** — não entram no audit. As 3 séries de alimentos por processamento são frequentemente atribuídas (erradamente) a SGS 1635/1636/1637, mas esses códigos são na verdade os **grupos 1/2/3 top-level do IPCA** ("Alimentação e bebidas", "Habitação", "Artigos de residência" — provado: diff=0.000, corr=1.000 contra IBGE T7060 categorias 7170/7445/...). Varredura sistemática de 190 códigos SGS plausíveis (ranges 27800-27900, 11400-11440, 4440-4480, 1700-1800, 16100-16140, 28000-28050): **0 hits** com corr > 0.85 contra alim_in/se/ind. Catálogo dadosabertos BCB confirma: BCB simplesmente não publica essas decomposições. Auditoria dessas 6 séries é feita por consistência interna no `reconstruct_ipca.R` (alim_in + alim_se + alim_ind ponderados = alim_dom; subj + exsubj ponderado = serv total).

## Algebra do `reconstruct_ipca.R`

Laspeyres com pesos mensais do próprio IBGE:
```
v_classe  = Σ(w_i × v_i, i ∈ classe)  /  Σ(w_i, i ∈ classe)
p_classe  = Σ(w_i, i ∈ classe)
v_livres  = (v_ipca × Σw - v_admin × p_admin) / p_livres   (controle algébrico)
```
Validação primária: somando todos os subitens com pesos próprios, deve dar o IPCA geral publicado pelo IBGE até erro de arredondamento na 2ª/3ª decimal.

Núcleos estatísticos (MA/MS/DP) usam algoritmos próprios (média truncada 20/80, com suavização 12m em subitens listados pra MS, ou re-pesagem por inverso de volatilidade pra DP) — definições operacionais do BCB documentadas no Relatório de Inflação.

## Convenções dos scripts

- **Auto-cwd**: todo script descobre a raiz do projeto via `--file=` e faz `setwd()`. Funciona de qualquer pasta de invocação.
- **Parametrização do recon**: `reconstruct_ipca.R` aceita env vars `SIDRA_AGG_ID` (tabela) e `MASK_CLASS_PATH_OVR` (máscara) — é o que permite o stitching sem refatorar.
- **Proxy opcional**: `proxy_config.R` é sourceado se existir. Sem o arquivo (rodando em casa) vira no-op.
- **Comentários em português**, terse, com `# Por que:` explicando decisões não-óbvias.
- **Pacotes**: só `httr` e `jsonlite` (base R pra resto). Sem `tidyverse`.

## Índice — base e fallback

`build_pareto_indice.R` tenta rebase nessa ordem:
1. **dez/1993=100** (legado, compat com seed BCB pré-2026-05)
2. **dez/2006=100** (default IBGE-only — primeira dez/ comum a todas as séries)
3. Base 100 no primeiro mês da série (último recurso)

Com o pipeline IBGE-only atual, todas as séries começam em jul/2006, então a base é dez/2006=100.

## Histórico de migração

**2026-05-26** — Implementação NT_57/Dez-2025:
- **MS**: 28 subitens c/ MM aritmética → 9 itens c/ média geométrica (Tabela 5 NT_57). `mean|d|` caiu de 0.066 → 0.0085 (redução 8×).
- **DP**: σ global do var_item → σ rolling 48m de `(var_item − var_ipca)` (Sec 2.2). `mean|d|` caiu de 0.037 → 0.017 (redução 2×).
- **+5 novos núcleos NT_57**: EX-FE (28751), EX1 (16121), EX3 Serv (29683), EX3 Ind (29684), Difusão (21379). Todos com `mean|d|` < 0.025pp.
- **Pendentes**: EX2 (SGS 27838) — exige listas dos núcleos componentes (alim_dom, serv, ind) dos RIs set/2016 + jun/2018. Vetor de agregação NT_57 (`Vetores_NT_57.xlsx`) ainda não auditado.
- **+P55** (SGS 28750, EE102/2021) — percentil 55 ponderado da distribuição cross-section dos subitens. **Núcleo MAIS importante do conjunto novo BCB** (jun/2020): melhor previsor IPCA 12m à frente (REQM 1.74 amostra 2004-19). Bate `mean|d|=0.0000pp` na primeira tentativa.
- **+nucleo_medio** corrigido: média dos 5 do conjunto NOVO (EX0+EX3+MS+DP+**P55**)/5. MA NÃO entra mais (foi substituído pelo P55 em jun/2020). Sem SGS BCB direto. Começa 2007-01 (warm-up DP).
- **ex3_serv** desambiguado: agora é estrito (sem alim_fora), distinto de `servicos_subj` (tradicional, com alim_fora). SGS 29683 bate com servicos_subj (`mean|d|=0.0078pp`), não com ex3_serv estrito.
- Total: 27 séries cobrindo 2006-07 → atual (nucleo_medio: 2007-01 → atual).

**2026-07-14** — Categoria `total` (IPCA headline) exportada:
- `reconstruct_ipca.R` agora exporta `total` (variação = `ipca_oficial` da SIDRA) no `ipca_pareto_recon.csv`. Índice deriva no `build_pareto_indice.R` (dinâmico, pega qualquer categoria nova). Peso = 100 no `ipca_pareto_pesos.csv`.
- Pipeline agora entrega **28 categorias** (headline + 27 agregações).
- `load_pareto_to_sql.py` + `simulate_pareto_to_sql.py`: renomeado `ipca_total` → `total` no `CATEGORY_LABELS`; removido bloco `PESO_ONLY` (agora é categoria completa com var/idx/weight).
- Motivação: `ipca_total` no CSV de pesos era código morto (não estava nem sendo gerado); usuário quer o headline no SQL corp como qualquer outra série do pipeline.

**2026-05-25** — Migração de BCB-seed para IBGE-only:
- **Antes**: `seed_pareto_history.R` baixava 12 séries do BCB SGS pra 1991-01 → 2019-12; `reconstruct_ipca.R` cobria 2020-01 → atual via T7060. 8 séries tinham gap pré-2020 (universo BCB divergente ou sem SGS).
- **Depois**: `seed_ibge_history.R` faz stitching de T2938 + T1419 + T7060, cobrindo 2006-07 → atual com metodologia única pras 20 séries. BCB SGS usado só em auditoria.
- **Trade-off**: perdeu cobertura 1991-01 → 2006-06 (IBGE não publica V66 pré-2006); ganhou consistência metodológica em toda a janela e fim do gap das séries de alimentos por processamento.
- **Seed BCB legado** (`seed_pareto_history.R`) preservado pra comparação retroativa pré-2006 contra BCB, se necessário.

## Scripts de diagnóstico (não-produção)

- `_audit_ibge_vs_bcb.R` — valida as 17 séries com SGS BCB ao longo dos ~20 anos.
- `_audit_8_divergentes.R` — auditoria original que descobriu o problema do universo BCB nos alimentos.
- `_probe_sgs.R` — sonda candidatos a SGS pra ndur_industr / serv_subj / serv_exsubj (conclusão: BCB não publica variação dessas).
- `_probe_sidra_history.R` — sonda metadados das tabelas SIDRA IPCA (descoberta de T2938/T1419 com V66).
- `_probe_subitem_codes.R` — compara códigos de subitem entre POFs.
- `_probe_pof_weight_gap.R` — quantifica % de peso sem classificação por POF (justifica máscara extended).
- `_probe_extended_mask.R` — diff entre máscara base e extended.

## Referências externas

- IBGE SIDRA API v3: `https://servicodados.ibge.gov.br/api/v3/agregados/<TBL>/periodos/<P>/variaveis/<V>?localidades=N1[all]&classificacao=315[all]`
- T7060 (POF 2017-18): variáveis V63 / V66 / V69 / V2265, classificação 315
- BCB API SGS (só auditoria): `https://api.bcb.gov.br/dados/serie/bcdata.sgs.<CODE>/dados?formato=json`
- BCB RI Dez/2019 Tab.5: definição autoritativa das classes (monitorado, alimento_domic, alimento_fora, servico, duravel, semiduravel, nao_duravel_industrial). Citado como `source` na coluna das máscaras.
- BCB WP374 / RI Mar/2014: definição de comerc/ncomerc e alim por grau de processamento (regra IBGE-subitem que adotamos).
- BCB RI Dez/2019 Tab.3: reclassificações C↔NC na migração POF 2008-09→2017-18. Tratamento calibrado empiricamente contra SGS 4447/4448: frutas (1106xxx) → C retroativamente em toda a janela; laticínios/panificados → NC apenas na máscara base (T7060/2020+), pois BCB SGS mantém esses itens em C pré-2020.
