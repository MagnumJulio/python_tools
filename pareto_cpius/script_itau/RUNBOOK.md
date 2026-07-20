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

**Totais servidos**: 47 categorias (39 base + 8 custom) × 3 séries = **141 séries**
(~44 700 linhas EAV). As 8 custom aggregations são derivadas via álgebra Laspeyres
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

**Objetivo:** confirmar que os 4 CSVs são lidos OK e a lista de 47 categorias
(39 base + 8 custom) × 2 sa_flags + Weight está correta. Não toca SQL, não
importa `opt_utils`.

```bash
python script_itau/load_cpius_to_sql.py --dry-run
```

**Sucesso:** imprime "78 (categoria, sa_flag) combinacoes" (idx base, 39 × 2)
+ "39 categorias com Weight (RI BLS)" + "8 agregacoes custom + NSA/SA" +
"8 Weights custom derivados". Lista 47 cats × [NSA idx, SA idx, Weight] =
~141 itens, cada um com N obs (~317 desde jan/2000). As 8 custom aparecem com
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
verificar no SSMS antes de soltar as 141 séries.

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

## Estágio 4 — carga completa (47 categorias × 3 séries = 141)

**Objetivo:** gravar até 141 séries (39 base + 8 custom, cada uma × [NSA idx,
SA idx, Weight]). Re-roda as 6 do Estágio 3 — `replace=True` apaga dados
antigos antes do reinsert, sem duplicar. Antes do main loop,
`_migrate_cpius_to_current` normaliza qualquer linha CPIUS antiga (haver_code
populado, sufixo /Index em bls_code, indicator=CPI-U, data_type=Peso) pro
formato atual.

```bash
python script_itau/load_cpius_to_sql.py
```

Confirma `Confirma gravacao de ate 141 series no SQL? [s/N]` → `s`.

**Verificação:**
```sql
SELECT data_type, COUNT(*) AS n_series
FROM OPT_Macro_Series_2 WHERE bls_code LIKE 'CPIUS:%'
GROUP BY data_type;
-- esperado: NSA=47, SA=47, Weight=47 (total 141)

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
-- NSA:    47 séries × ~316-318 obs
-- SA:     47 séries × ~316-318 obs
-- Weight: 47 séries × ~316-317 obs
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

## Re-execução periódica (após BLS soltar novo release)

BLS solta CPI-U mensalmente ~10-15 do mês seguinte (release calendar em
https://www.bls.gov/schedule/news_release/cpi.htm). Pipeline incremental:

```bash
cd pareto_cpius
Rscript scripts/fetch_bls_cpiu.R                       # re-baixa preços (rápido)
Rscript scripts/fetch_bls_pesos.R                      # regera pesos ajustados (parse RI só se novo Dez rolou)
Rscript scripts/build_custom_aggregations.R            # re-deriva 8 custom aggs
python script_itau/load_cpius_to_sql.py --no-confirm   # sem prompt
```

**Nota sobre pesos anuais**: `parse_historical_ri.py` só precisa re-rodar quando um novo RI de Dezembro é publicado (~Fev do ano seguinte). Baixar a Table 6 nova de https://www.bls.gov/cpi/tables/relative-importance/, salvar como `data/raw/relative_importance/YYYY.xlsx`, rodar o parser, e re-rodar `fetch_bls_pesos.R`. Dentro do ano-fiscal, apenas o preço muda (o script já pega os índices novos automaticamente).

**Nota:** `fetch_bls_cpiu.R` não tem modo incremental — sempre re-baixa a
janela inteira. Com `BLS_API_KEY` isso é ~30s e cabe folgado no limite de
500 req/dia. Sem chave, cuidado com o limite de 25 req/dia (2 batches × 2
janelas = 4 req por run, então ~6 runs por dia).

`--no-confirm` pula o prompt interativo:
```bash
python script_itau/load_cpius_to_sql.py --no-confirm > load_$(date +%Y%m%d).log 2>&1
```

**Vintage:** BLS revisa fatores sazonais em janeiro de cada ano (recalcula
últimos 5 anos de SA). Isso significa que valores SA anteriores podem mudar
quando você re-roda em jan/2027, por exemplo. `release_date`/`vintage_date`
gravados na tabela ajudam a rastrear isso — em fase 2 vale versionar por
release date.

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
