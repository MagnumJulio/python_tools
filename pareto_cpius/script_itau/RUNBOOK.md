# RUNBOOK — carga do pareto_cpius no SQL Itaú

Procedimento controlado, em 4 estágios, com pontos de parada explícitos.
Cada estágio é independente — se algo der errado, dá pra parar e investigar
sem ter sujado o banco.

## Sync local ↔ máquina corp (deltas conhecidos)

Projeto novo (criado 2026-07-14). Nenhum delta conhecido entre esta cópia
local e a máquina corp — a corp ainda **não tem** este projeto. A migração
inicial é one-way (local → corp) copiando o diretório inteiro.

| Delta | Estado local | Estado corp | Aplicado em |
|---|---|---|---|
| Projeto inteiro | ✅ MVP entregue (fetcher + build + simulate + load) | ⚠️ **não existe ainda** — precisa ser copiado | — |
| `data_type="Weight"` (era `"Peso"`) | ✅ sync 2026-07-17 | ✅ idem | 2026-07-17 |
| Headline `all_items` peso = 100.0 constante | ✅ sync 2026-07-17 (sobrescreve renorm ~99.9997) | ✅ idem | 2026-07-17 |
| Campo `bls_code` (era `haver_code`) | ✅ sync 2026-07-17-b — INSERTs novos gravam em `bls_code`, `haver_code` fica `NULL` | precisa ALTER TABLE `ADD bls_code VARCHAR(255) NULL` se ainda não tiver | 2026-07-17-b |
| Só idx + Weight (var NSA/SA removido) | ✅ sync 2026-07-20 — var deixou de ser gravado; SQL só recebe idx NSA + idx SA + Weight | ⚠️ rows de var pré-existentes viram orphan; cleanup manual sob pedido | 2026-07-20 |
| `bls_code` sem sufixo `/Index` | ✅ sync 2026-07-20 — colapsado pra único `CPIUS:{cat}`; distinção idx vs Weight sai de `series_name`+`data_type` | migração automática normaliza rows antigas | 2026-07-20 |
| Weight 1× (não mais 2×) | ✅ sync 2026-07-20 — como var sumiu, Weight só precisa parear com o idx via `series_name=f"{label} (Index)"` | rows antigas de Weight-label ficam orphan | 2026-07-20 |
| `indicator="CPI"` (era `"CPI-U"`) | ✅ sync 2026-07-20 | migração automática atualiza rows antigas | 2026-07-20 |
| Migração idempotente (`_migrate_cpius_to_current`) | ✅ roda antes do main loop; normaliza `haver_code`→NULL, `bls_code` sem sufixo, `indicator`=CPI, `data_type`=Weight | ⚠️ rodar 1x no corp se já houver rows CPIUS; próximos runs viram no-op | 2026-07-20 |
| Pesos (BLS Table 6, time-varying) | ✅ fase 2 entregue (RI Dez 2000-2025 + ajuste implícito BLS) | ⏳ precisa da migração inicial | — |
| SA nativa BLS (sem X-13) | ✅ já é assim (`data_type='SA'` vem direto de CUSR0000<item>) | idem quando migrar | — |
| Agregações custom (Laspeyres) | ✅ entregue 2026-07-16 (8 recipes: core_ex_oer, super_super_core, supercore_powell_old, etc.) | ⏳ precisa da migração inicial | — |

**Diferença estrutural vs `pareto_ipca`:** cada categoria gera até **3 séries**
(NSA idx, SA idx, Weight) — pareto_ipca ainda serve var. Var no CPI-US foi removido
no sync 2026-07-20 pra não lotar SQL de lixo (usuário deriva variação mensal do
índice no consumo). BLS publica SA nativo — não precisa de X-13. **Peso é
time-varying** (fase 2 entregue): base RI Dez de cada ano 2000-2025 + ajuste
implícito mensal `w_i(m) = w_i(Dez) × I_i(m) / I_i(Dez)` seguindo metodologia BLS
"monthly relative importance". Headline `all_items` recebe peso sintético 100.0
constante (sobrescreve o renorm ~99.9997 do CSV). Weight é gravado 1× pareado com
o idx via `series_name=f"{label} (Index)"` — frontend casa Weight ao idx via
`series_name+country+indicator`.

**Totais servidos**: 49 categorias (41 base + 8 custom) × 3 séries = **147 séries**
(~46 500 linhas EAV). As 8 custom aggregations são derivadas via álgebra Laspeyres
em `scripts/build_custom_aggregations.R` a partir do `recon.csv` + `pesos.csv`.
Proveniência gravada em **`bls_code`** com formato simplificado (`CPIUS:{cat}`, um
único code por categoria — a distinção idx vs Weight sai de `series_name`+`data_type`,
não do code). Distinção base vs custom sai do próprio `category_code` (ex.:
`core_ex_oer` vs `core`), não do code de proveniência. Migração idempotente
(`_migrate_cpius_to_current`) rodada antes do main loop: normaliza qualquer row
CPIUS (haver_code ou bls_code populado) pro formato atual — `haver_code=NULL`,
`bls_code='CPIUS:{cat}'` sem sufixo, `indicator='CPI'`, `data_type='Weight'` (era
`Peso`).

## Pré-requisitos (na máquina corp)

- `opt_utils.database.SQLConnector` disponível (mesmo módulo do `sidra_itau.ipynb`)
- ODBC driver SQL Server configurado (mesmo que o notebook usa)
- Permissão de INSERT/DELETE em `OPT_Macro_Series_2` e `OPT_Macro_Series_Data_2`
- Diretório de trabalho: `pareto_cpius/`
- (Opcional mas recomendado) `BLS_API_KEY` exportado — sem chave, BLS API v2
  limita a 25 requests/dia, o que trava re-runs frequentes
- CSVs gerados pelo pipeline R existem em `data/`:
  - `data/cpi_cpius_indice.csv` (índice rebased jan/2000=100, NSA + SA) — **único CSV consumido pelo loader; var não é mais gravada**
  - `data/cpi_cpius_pesos.csv` (peso Relative Importance BLS, time-varying)
  - `data/cpi_cpius_custom.csv` + `cpi_cpius_pesos_custom.csv` (8 agregações custom Laspeyres)

Se ainda não rodou o pipeline:
```bash
cd pareto_cpius
export BLS_API_KEY=<sua_chave>              # opcional mas recomendado
Rscript scripts/fetch_bls_cpiu.R               # 2000 → atual, ~30s com chave
python scripts/parse_historical_ri.py          # RI Dez 2000-2025 → pesos_annual.csv (~2s)
Rscript scripts/fetch_bls_pesos.R              # peso mensal ajustado (Fase 2), ~1s
Rscript scripts/build_custom_aggregations.R    # deriva 8 agregacoes custom (~2s)
# (opcional) rebase pra outra base:
BASE_DATE=2019-12-01 Rscript scripts/build_cpi_indice.R
```

Requer: **Python 3** com `openpyxl` (`pip install openpyxl`) pra parsear os xlsx BLS.

---

## Estágio 1 — `--dry-run` (zero conexão SQL)

**Objetivo:** confirmar que os 4 CSVs são lidos OK e a lista de 49 categorias
(41 base + 8 custom) × 2 sa_flags + Weight está correta. Não toca SQL, não
importa `opt_utils`.

```bash
python script_itau/load_cpius_to_sql.py --dry-run
```

**Sucesso:** imprime "82 (categoria, sa_flag) combinacoes" (idx base, 41 × 2)
+ "41 categorias com Weight (RI BLS)" + "8 agregacoes custom + NSA/SA" +
"8 Weights custom derivados". Lista 49 cats × [NSA idx, SA idx, Weight] =
~147 itens, cada um com N obs (~317 desde jan/2000). As 8 custom aparecem com
tag `[CUSTOM]`. Imprime também 1 `bls_code` por cat: `CPIUS:{cat}` (sem
sufixo `/Index`).

**Se falhar aqui:** problema é nos CSVs (rode `fetch_bls_cpiu.R` +
`fetch_bls_pesos.R` + `build_custom_aggregations.R`) ou nos labels em
`CATEGORY_LABELS` / `CUSTOM_LABELS` (faltaram códigos).

---

## Estágio 2 — `--check` (preflight read-only no SQL)

**Objetivo:** abrir conexão SQL e validar que: (a) o `SQLConnector` funciona
com `connector="pyodbc"` (b) as 2 tabelas existem (c) a coluna `bls_code`
existe em `OPT_Macro_Series_2` (necessária pra sync 2026-07-17-b) (d) a
coluna `description` aguenta nosso pior caso (~110 chars) (e) listar todas as
séries CPIUS existentes (qualquer formato — `bls_code LIKE 'CPIUS:%'` OU
`haver_code LIKE 'CPIUS:%'`) que serão normalizadas pela migração antes do
main loop.

```bash
python script_itau/load_cpius_to_sql.py --check
```

**Sucesso:** 5 linhas `[OK]` e zero `[FAIL]`. Mostra contagem de linhas
atuais de cada tabela + lista consolidada de séries CPIUS existentes (0 na
primeira carga).

**Se falhar aqui:**
- `ModuleNotFoundError: opt_utils` → instalação corp quebrada
- erro de conexão pyodbc → credenciais/driver/DSN
- `[FAIL] OPT_Macro_Series_2` → permissão ou tabela com nome diferente
- `[FAIL] coluna bls_code NAO existe` → rodar `ALTER TABLE OPT_Macro_Series_2 ADD bls_code VARCHAR(255) NULL;`
- `[FAIL] description = VARCHAR(N)` com N<110 → mexer no schema OU encurtar
  as strings `description=` no loader

---

## Estágio 3 — smoke test (`--only all_items,core`)

**Objetivo:** gravar 6 séries (2 categorias × [NSA idx + SA idx + Weight]) e
verificar no SSMS antes de soltar as 147 séries.

```bash
python script_itau/load_cpius_to_sql.py --only all_items,core
```

Pergunta `Confirma gravacao de ate 6 series no SQL? [s/N]` — responda `s`.

**Verificação no SSMS:**
```sql
SELECT series_id, series_name, indicator, data_type, haver_code, bls_code
FROM OPT_Macro_Series_2 WHERE bls_code IN ('CPIUS:all_items', 'CPIUS:core')
ORDER BY series_id;
-- esperado: 6 linhas (all_items × 3 + core × 3)
-- haver_code = NULL em todas.
-- bls_code em 2 valores: CPIUS:all_items, CPIUS:core (sem sufixo /Index).
-- indicator = 'CPI' em todas.
-- series_name termina em "(Index)" em todas (idx e Weight compartilham nome).

-- Confirma que nenhuma linha CPIUS antiga sobrou fora do formato atual:
SELECT COUNT(*) FROM OPT_Macro_Series_2
WHERE (bls_code LIKE 'CPIUS:all_items%' OR bls_code LIKE 'CPIUS:core%')
  AND (bls_code LIKE '%/Index' OR indicator <> 'CPI' OR haver_code IS NOT NULL);
-- esperado: 0 (migração normalizou tudo).

SELECT s.series_name, s.data_type, COUNT(*) AS n
FROM OPT_Macro_Series_Data_2 d
JOIN OPT_Macro_Series_2 s ON s.series_id = d.series_id
WHERE s.bls_code IN ('CPIUS:all_items', 'CPIUS:core')
GROUP BY s.series_name, s.data_type
ORDER BY s.series_name, s.data_type;
-- esperado: 6 linhas, ~317 obs cada (jan/2000 → mês atual):
--   NSA:    n=317
--   SA:     n=317
--   Weight: n=317 (all_items = 100.0 constante; core = time-varying ~65-70)

-- Confirma Weight all_items = 100.0 constante:
SELECT MIN(value) AS wmin, MAX(value) AS wmax, COUNT(*) AS n
FROM OPT_Macro_Series_Data_2 d
JOIN OPT_Macro_Series_2 s ON s.series_id = d.series_id
WHERE s.bls_code = 'CPIUS:all_items' AND s.data_type = 'Weight';
-- esperado: wmin=100.0, wmax=100.0, n=317

SELECT TOP 5 * FROM OPT_Macro_Series_Data_2 WHERE series_id = <id_all_items_NSA_idx>
ORDER BY date;
-- valores de referência em sim_output/OPT_Macro_Series_Data_2.csv
```

**Se algo estiver errado aqui, ANTES de continuar:**
```sql
-- rollback do smoke test (apaga só as 6 séries inseridas):
DELETE FROM OPT_Macro_Series_Data_2
WHERE series_id IN (SELECT series_id FROM OPT_Macro_Series_2
                    WHERE bls_code IN ('CPIUS:all_items', 'CPIUS:core'));
DELETE FROM OPT_Macro_Series_2
WHERE bls_code IN ('CPIUS:all_items', 'CPIUS:core');
```

---

## Estágio 4 — carga completa (49 categorias × 3 séries = 147)

**Objetivo:** gravar até 147 séries (41 base + 8 custom, cada uma × [NSA idx,
SA idx, Weight]). Re-roda as 6 do Estágio 3 — `replace=True` apaga dados
antigos antes do reinsert, sem duplicar. Antes do main loop,
`_migrate_cpius_to_current` normaliza qualquer linha CPIUS antiga (haver_code
populado, sufixo /Index em bls_code, indicator=CPI-U, data_type=Peso) pro
formato atual.

```bash
python script_itau/load_cpius_to_sql.py
```

Confirma `Confirma gravacao de ate 147 series no SQL? [s/N]` → `s`.

**Verificação:**
```sql
SELECT data_type, COUNT(*) AS n_series
FROM OPT_Macro_Series_2 WHERE bls_code LIKE 'CPIUS:%'
GROUP BY data_type;
-- esperado: NSA=49, SA=49, Weight=49 (total 147)

-- Confirma que não sobrou row com formato antigo:
SELECT COUNT(*) AS n_stale FROM OPT_Macro_Series_2
WHERE (bls_code LIKE 'CPIUS:%' OR haver_code LIKE 'CPIUS:%')
  AND (haver_code IS NOT NULL OR bls_code LIKE '%/Index' OR indicator <> 'CPI');
-- esperado: 0

-- Base vs custom sai do category_code (não do bls_code). Contar custom:
SELECT COUNT(*) AS n_custom_series FROM OPT_Macro_Series_2
WHERE bls_code IN (
  'CPIUS:rent_of_shelter', 'CPIUS:core_ex_oer', 'CPIUS:cpi_ex_oer',
  'CPIUS:core_services_ex_shelter', 'CPIUS:supercore_powell_old',
  'CPIUS:core_services_ex_shelter_pubtrans_medical',
  'CPIUS:super_super_core', 'CPIUS:core_services_ex_volatiles'
);
-- esperado: 24 (8 custom × 3 séries)

-- all_items peso constante = 100.0 em todas as datas:
SELECT MIN(value) AS wmin, MAX(value) AS wmax, COUNT(*) AS n
FROM OPT_Macro_Series_Data_2 d
JOIN OPT_Macro_Series_2 s ON s.series_id = d.series_id
WHERE s.bls_code = 'CPIUS:all_items' AND s.data_type = 'Weight';
-- esperado: wmin=100.0, wmax=100.0, n=317

SELECT s.data_type, COUNT(*) AS n_obs
FROM OPT_Macro_Series_Data_2 d
JOIN OPT_Macro_Series_2 s ON s.series_id = d.series_id
WHERE s.bls_code LIKE 'CPIUS:%'
GROUP BY s.data_type;
-- NSA:    49 séries × ~316-318 obs
-- SA:     49 séries × ~316-318 obs
-- Weight: 49 séries × ~316-317 obs
```

**Cleanup de rows orphan de var** (se rodaram versão anterior do loader com
var gravado): a migração NÃO deleta essas rows automaticamente. Pra remover
manualmente:
```sql
-- Preview do que seria apagado (data_type NSA/SA sem "(Index)" no series_name):
SELECT series_id, series_name, data_type, bls_code
FROM OPT_Macro_Series_2
WHERE bls_code LIKE 'CPIUS:%'
  AND data_type IN ('NSA','SA')
  AND series_name NOT LIKE '% (Index)';

-- Depois de conferir, apagar:
DELETE FROM OPT_Macro_Series_Data_2
WHERE series_id IN (SELECT series_id FROM OPT_Macro_Series_2
                    WHERE bls_code LIKE 'CPIUS:%'
                      AND data_type IN ('NSA','SA')
                      AND series_name NOT LIKE '% (Index)');
DELETE FROM OPT_Macro_Series_2
WHERE bls_code LIKE 'CPIUS:%'
  AND data_type IN ('NSA','SA')
  AND series_name NOT LIKE '% (Index)';
```

---

## Rollback completo (se precisar desfazer tudo)

```sql
DELETE FROM OPT_Macro_Series_Data_2
WHERE series_id IN (SELECT series_id FROM OPT_Macro_Series_2
                    WHERE bls_code LIKE 'CPIUS:%');

DELETE FROM OPT_Macro_Series_2 WHERE bls_code LIKE 'CPIUS:%';
```

Isso só remove o que este loader inseriu (filtra pelo prefixo `CPIUS:` no
`bls_code`) — não afeta as séries SIDRA/IPCA nem as do Haver.

---

## ⚠️ Fix pendente: `core_services` estava com item_code errado (SASL5 → SASLE)

**Data**: 2026-08-11. Todo run antes disso gravou no SQL a série
**"Services less medical care services"** (SASL5) com label "core_services",
não a **"Services less energy services"** (SASLE) correta. Contaminou:

- Base cat `core_services` (~0.07pp yoy off vs Haver)
- 5 das 8 customs que usam `core_services` como base do Laspeyres:
  `core_services_ex_shelter`, `supercore_powell_old`, `super_super_core`,
  `core_services_ex_shelter_pubtrans_medical`, `core_services_ex_volatiles`
  (~0.2-0.4pp yoy off).

**Fix aplicado (2026-08-11)** em `update_cpius_lean.py`, `cpiu_table_1.csv`,
`load_cpius_to_sql.py`, `simulate_cpius_to_sql.py`, `_probe_subitem_tree.py`
e `CLAUDE.md`. `reconstruct_cpius.py` já estava certo (achou o bug antes mas
o fix não propagou).

**IMPORTANTE — SQL corp precisa full re-load** dessas 6 categorias. A rodagem
rápida (`update_cpius_lean.py`) só reescreve últimos `INCREMENTAL_MONTHS=24`
por série, então history > 2 anos ainda fica com dados de SASL5 antigo.
Rodar quando voltar da viagem:

```powershell
# Full re-load do que estava contaminado. Vai reescrever full history 2000→hoje.
python script_itau\load_cpius_to_sql.py --only core_services,core_services_ex_shelter,supercore_powell_old,super_super_core,core_services_ex_shelter_pubtrans_medical,core_services_ex_volatiles
```

Antes disso, rodar o pipeline R full pra regenerar os CSVs em `data/` com
SASLE (ver Estágio 1 acima). Como o R fetcher lê de `cpiu_table_1.csv` (já
corrigido), o próximo run vai vir certo.

---

## Priority subset load (22 cats dashboard)

Comando pra full re-load histórico só das 22 cats principais (16 base + 6 custom = 66 séries), em vez das 49 completas. Útil quando só o dashboard interessa e o custo de reescrever as outras 27 cats é desperdício.

**Pré-req**: pipeline R full antes (`fetch_bls_cpiu` + `fetch_bls_pesos` + `build_custom_aggregations`).

```powershell
python script_itau/load_cpius_to_sql.py --only all_items,food,energy,core,core_goods,new_vehicles,used_cars_trucks,core_services,shelter,oer,rent,lodging_away,medical_care,transportation_services,airline_fares,car_truck_rental,core_ex_oer,cpi_ex_oer,core_services_ex_shelter,supercore_powell_old,super_super_core,core_services_ex_volatiles
```

Confirma `Confirma gravacao de ate 66 series no SQL? [s/N]` → `s`.

Cats na ordem: CPI geral, Food, Energy, Core CPI, Core goods, New vehicles, Used cars/trucks, Core services (SASLE), Shelter, OER, RPR (`rent`), Lodging away, Health care (`medical_care`/SAM), Transportation services, Airline fares, Car & truck rental, Core ex OER, CPI ex OER, Core services ex rent of shelter, Core services ex RPR & OER (`supercore_powell_old`), Super super core, Core services ex volatiles.

---

## Manutenção mensal (após BLS soltar novo release)

BLS solta CPI-U mensalmente ~10-15 do mês seguinte (release calendar em
https://www.bls.gov/schedule/news_release/cpi.htm). Existem dois caminhos:

- **Opção A — rodagem rápida** (`update_cpius_lean.py`): **padrão do
  dia-a-dia**. Um script Python self-contained puxa idx do BLS, recalcula
  Weight, escreve direto no SQL. Sem CSVs intermediários, sem R. ~15s.
- **Opção B — pipeline completo pra cats selecionadas**: fallback pra
  quando a rápida falhar em algumas cats, ou pra reconstruir uma cat do
  zero (histórico full de jan/2000). Roda o pipeline R inteiro (fetcha 41
  base cats, pesos time-varying, 8 customs Laspeyres), depois grava só as
  cats pedidas via `load_cpius_to_sql.py --only`.

Sempre começar pela A. Se cair alguma cat, ir pra B só nessas.

---

### Opção A — rodagem rápida (`update_cpius_lean.py`) — PADRÃO

**Pré-requisitos:**
- `opt_utils.database.SQLConnector` disponível (mesmo ambiente corp usado
  pelo `sidra_itau.ipynb`).
- `BLS_API_KEY` no env (32 chars). Sem chave: rate limit derruba na
  segunda re-run.
- Python 3.10+ com `pandas`, `requests` (já vêm no ambiente corp).

**Passo 1 — smoke test em simulate (sem tocar SQL):**

```bash
cd pareto_cpius
python quick_update/update_cpius_lean.py --cats all --simulate
```

Confirma no log:
- `API key ON` (senão exportar `BLS_API_KEY` antes).
- `cats pedidas: 41 base + 8 custom = 49`.
- `[fetch] 82 series_ids x N janela(s) (20a) x batches de 50` → com key
  são 2 batches (2000-2019 + 2020-atual), sem key seriam 4 (janelas de 10a).
- `[fetch] concluido: 82/82 series c/ dados (0 vazias)` — se aparecer
  `[WARN] sem dados: CUUR0000<item>`, BLS pode ter reestruturado esse item
  code (raro; ver "Cat solta" abaixo).
- `RI_BASE_DATE = 2025-12  |  ultimo mes idx BLS = YYYY-MM` — o mês de idx
  tem que ser o do release mais recente (ex.: rodando em 13/ago vai pegar
  jul/2026). Se vier atrasado, BLS ainda não publicou — esperar ou seguir.
- **NENHUM** `[WARN] RI_BASE_DATE esta N meses atras`. Se aparecer, PARAR e
  atualizar `RI_BASE_DATE` + `RI_HISTORICAL[YYYY]` no
  `update_cpius_lean.py` (ver "Bump anual da RI base" abaixo).
- Ao fim: `[simulate] OPT_Macro_Series_2 = 147 rows` e
  `OPT_Macro_Series_Data_2 = ~46 500 rows`.

**Passo 2 — run real (grava no SQL corp):**

```bash
python quick_update/update_cpius_lean.py --cats all
```

Comportamento:
- Cada cat re-envia os **últimos 24 meses** (`INCREMENTAL_MONTHS`). Cobre
  o novo release + revisão SA anual do BLS + recalculo de Weight.
- Se uma série é nova no SQL (primeira vez que essa cat aparece), faz
  **seed full** (jan/2000 → hoje).
- Idempotente: pode rodar 2× seguido sem duplicar.

Redirect pra log:
```bash
python quick_update/update_cpius_lean.py --cats all > \
  quick_update/logs/lean_$(date +%Y%m%d).log 2>&1
```

**Passo 3 — verificação SQL:**

```sql
-- Confirma última data em Data_2 (deve ser o release novo):
SELECT s.data_type, MAX(d.date) AS last_date, COUNT(DISTINCT d.series_id) AS n_series
FROM OPT_Macro_Series_Data_2 d
JOIN OPT_Macro_Series_2 s ON s.series_id = d.series_id
WHERE s.bls_code LIKE 'CPIUS:%'
GROUP BY s.data_type;
-- esperado: NSA=49, SA=49, Weight=49; last_date = último dia do mês do release novo

-- Contagem de rows das últimas 24 datas (pra confirmar o incremental
-- fechou tudo):
SELECT COUNT(*) FROM OPT_Macro_Series_Data_2 d
JOIN OPT_Macro_Series_2 s ON s.series_id = d.series_id
WHERE s.bls_code LIKE 'CPIUS:%'
  AND d.date >= DATEADD(month, -24, EOMONTH(GETDATE()));
-- esperado: ~3500 (49 séries × 3 datatypes × 24 meses)
```

**Se algo falhar na rodagem rápida:**
- `RuntimeError: [BLS] REQUEST_NOT_PROCESSED` → rate limit; esperar 1h e
  tentar de novo, OU rodar Opção B pra cats críticas.
- `requests.exceptions.Timeout` → BLS lento; re-tentar. Se persistir,
  Opção B com fetch R (menos ruído de rede pela API v2 aceitar POST
  batchado).
- `[WARN] sem dados: CUUR0000XXX` numa cat só → BLS reestruturou aquele
  item code. Passar essa cat via Opção B **não resolve** — precisa achar o
  novo code e atualizar `ITEM_CODES` no lean **e** o mapa
  `scripts/bls_maps/cpiu_table_1.csv`. As demais cats seguiram
  normalmente; só falta essa.
- ImportError `opt_utils.database` → não está no ambiente corp; rodar
  `--simulate` só valida a mecânica.

---

### Opção B — pipeline completo pra cats selecionadas (fallback)

**Quando usar:**
- A rodagem rápida caiu em algumas cats e você quer reconstruir só essas
  do zero (jan/2000 → hoje).
- Você quer forçar re-fetch full ignorando o INCREMENTAL_MONTHS=24 (ex.:
  auditoria histórica, discrepância de vintage).
- BLS mudou item code de uma cat e a rápida está deixando ela vazia.

**Custo:** ~35s totais (fetch R + parse + build) + `--only` do loader é
rápido. Pipeline R **sempre** roda full pras 41 base cats (não tem modo
seletivo por cat no fetcher); o filtro por cat entra só na hora da carga
SQL via `--only`.

**Passo 0 — decidir a lista de cats.**

Passar como CSV, sem espaços. Ex.: `motor_fuel,gasoline,fuel_oil` (base)
ou `core_ex_oer,super_super_core` (custom). Aceita mistura. Se uma custom
está na lista, todas as bases dela entram no fetch (as bases só vão pro
SQL se estiverem explicitamente em `--only`).

**Passo 1 — re-executar o pipeline R (regera CSVs em `data/`):**

```bash
cd pareto_cpius
export BLS_API_KEY=<sua_chave>

# 1a) idx NSA + SA das 41 base cats. Full 2000→atual (~30s com key).
Rscript scripts/fetch_bls_cpiu.R

# 1b) Só rode se BLS publicou Table 6 nova (~Fev do ano seguinte). Se em
#     dúvida, pula — é raro dentro do ano-fiscal.
python scripts/parse_historical_ri.py

# 1c) Weight time-varying: RI base × ajuste implícito mensal (~1s).
Rscript scripts/fetch_bls_pesos.R

# 1d) 8 agregações custom Laspeyres (~2s).
Rscript scripts/build_custom_aggregations.R
```

Ao fim, 4 CSVs em `data/` estão atualizados:
`cpi_cpius_indice.csv`, `cpi_cpius_pesos.csv`, `cpi_cpius_custom.csv`,
`cpi_cpius_pesos_custom.csv`.

**Passo 2 — dry-run do loader filtrando pelas cats escolhidas:**

```bash
python script_itau/load_cpius_to_sql.py --dry-run --only motor_fuel,gasoline,fuel_oil
```

Confirma que lista só o que você quer (3 cats × [NSA, SA, Weight] = 9
itens) e mostra o `bls_code` que cada uma vai gravar.

**Passo 3 — carga real (só as cats do `--only`):**

```bash
python script_itau/load_cpius_to_sql.py --only motor_fuel,gasoline,fuel_oil
```

Confirma `Confirma gravacao de ate 9 series no SQL? [s/N]` → `s`. Pra
pular o prompt em automação: `--no-confirm`.

**Diferença importante vs Opção A:** o loader usa `replace=True` — ele
**apaga TODAS as rows dessas séries e reinserde o histórico full**
(jan/2000 → hoje, ~317 rows). Não é incremental 24m como o lean. Isso é
o comportamento desejado quando você quer reconstruir do zero.

**Verificação:**
```sql
SELECT s.series_name, s.data_type, MIN(d.date) AS min_d, MAX(d.date) AS max_d, COUNT(*) AS n
FROM OPT_Macro_Series_Data_2 d
JOIN OPT_Macro_Series_2 s ON s.series_id = d.series_id
WHERE s.bls_code IN ('CPIUS:motor_fuel','CPIUS:gasoline','CPIUS:fuel_oil')
GROUP BY s.series_name, s.data_type
ORDER BY s.series_name, s.data_type;
-- esperado: 9 linhas, min_d = 2000-01-31, max_d = último dia do mês do release novo, n ≈ 317
```

---

### Bump anual da RI base (só se `[WARN]` disparar)

Quando BLS publicar Table 6 base 2026 (~Dez/2026 ou Fev/2027):

1. Baixar `2026.xlsx` de https://www.bls.gov/cpi/tables/relative-importance/
   e salvar em `data/raw/relative_importance/2026.xlsx`.
2. `python scripts/parse_historical_ri.py` → regera `cpi_cpius_pesos_annual.csv`
   com a linha 2026.
3. Copiar o dict do CSV pro `RI_HISTORICAL[2026] = {...}` em
   `quick_update/update_cpius_lean.py`.
4. Atualizar `RI_BASE_DATE = "2026-12"` no mesmo arquivo.
5. Smoke test: `python quick_update/update_cpius_lean.py --cats all --simulate`
   — não deve mais aparecer `[WARN] RI_BASE_DATE`.

Enquanto não bumpar, o script continua rodando com a base antiga; só o
`[WARN]` alerta. Rodar com RI atrasada > 12 meses vira erro estatístico
material (peso implícito diverge da revisão do BLS).

---

### Cat solta (BLS reestruturou item code)

Cenário raro: BLS reorganiza a taxonomia e um `item_code` some ou muda
significado. Sintoma: a rodagem rápida marca essa cat como
`[WARN] sem dados: CUUR0000XXX` e a série no SQL fica congelada no último
release bom.

Diagnóstico:
1. Baixar https://download.bls.gov/pub/time.series/cu/cu.item e procurar
   pelo item_code antigo — se sumiu, buscar pelo label esperado (ex.:
   "Rent of primary residence").
2. Achar o novo `item_code` e atualizar em **dois lugares**:
   - `scripts/bls_maps/cpiu_table_1.csv` (pra pipeline R)
   - `ITEM_CODES` em `quick_update/update_cpius_lean.py` (pra rodagem
     rápida)
3. Re-rodar smoke `--simulate`. Se voltou (0 warns), rodar real.

Se labels mudaram sem quebrar `item_code`, só o `CATEGORY_LABELS` /
`CATEGORY_BLS_DEFS` precisam ajustar — a série no SQL segue viva.

---

**Vintage:** BLS revisa fatores sazonais em janeiro de cada ano
(recalcula últimos 5 anos de SA). A janela de 24m do lean pega ~99% da
revisão prática; se quiser fechar 100% do fator revisitado, rodar a
Opção B na virada do ano — o `replace=True` reescreve todo o histórico
das cats escolhidas. `release_date`/`vintage_date` gravados na tabela
ajudam a rastrear (`release_date` = data em que a linha entrou no SQL, não
o release BLS).

---

## Comparação contra simulação local

Os valores esperados estão em `script_itau/sim_output/OPT_Macro_Series_Data_2.csv`
(gerado por `simulate_cpius_to_sql.py --save`). Se uma linha qualquer no SQL
não bater com a equivalente no CSV simulado, há discrepância no write —
investigar `sidra_to_sql`.

```sql
SELECT TOP 10 s.series_name, s.data_type, d.date, d.value
FROM OPT_Macro_Series_Data_2 d
JOIN OPT_Macro_Series_2 s ON s.series_id = d.series_id
WHERE s.bls_code LIKE 'CPIUS:all_items%'
ORDER BY s.data_type, d.date;
```
Compare com:
```bash
head -20 script_itau/sim_output/OPT_Macro_Series_Data_2.csv
```

Diferença esperada: no SQL as datas são **último dia do mês** (convenção Haver
corp — o loader converte via `MonthEnd(0)`), no CSV do simulate ficam no dia
01 (formato do CSV upstream). Os valores devem bater.
