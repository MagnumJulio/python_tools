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
| Weight gravado 2× (label + label Index) | ✅ sync 2026-07-17 (par com var e par com idx) | ✅ idem | 2026-07-17 |
| Headline `all_items` peso = 100.0 constante | ✅ sync 2026-07-17 (sobrescreve renorm ~99.9997) | ✅ idem | 2026-07-17 |
| Code simplificado + campo `bls_code` | ✅ sync 2026-07-17-b — `CPIUS:{cat}` / `CPIUS:{cat}/Index` gravado em `bls_code`; INSERTs novos não setam `haver_code` (fica `NULL` por default) | precisa ALTER TABLE `ADD bls_code VARCHAR(255) NULL` se ainda não tiver | 2026-07-17-b |
| Migração de rows antigas (`haver_code LIKE 'CPIUS:%'`) | ✅ `_migrate_haver_to_bls` roda antes do main loop (idempotente) | ⚠️ rodar 1x no corp se já houver rows CPIUS antigas; próximos runs viram no-op | 2026-07-17-b |
| Pesos (BLS Table 6, time-varying) | ✅ fase 2 entregue (RI Dez 2000-2025 + ajuste implícito BLS) | ⏳ precisa da migração inicial | — |
| SA nativa BLS (sem X-13) | ✅ já é assim (`data_type='SA'` vem direto de CUSR0000<item>) | idem quando migrar | — |
| Agregações custom (Laspeyres) | ✅ entregue 2026-07-16 (8 recipes: core_ex_oer, super_super_core, supercore_powell_old, etc.) | ⏳ precisa da migração inicial | — |

**Diferença estrutural vs `pareto_ipca`:** cada categoria gera até **6 séries**
(NSA var, NSA idx, SA var, SA idx, **Weight label**, **Weight label Index**) porque
(a) BLS publica SA nativo — não precisa de X-13, e (b) sync 2026-07-17 com pareto_ipca:
peso é gravado 2× por categoria, uma com `series_name=label` (par com var NSA/SA) e
outra com `series_name=f"{label} (Index)"` (par com idx NSA/SA), ambas com
`data_type="Weight"`. **Peso é time-varying**
(fase 2 entregue): base RI Dez de cada ano 2000-2025 + ajuste implícito mensal
`w_i(m) = w_i(Dez) × I_i(m) / I_i(Dez)` seguindo metodologia BLS "monthly relative
importance". Headline `all_items` recebe peso sintético 100.0 constante (sobrescreve
o renorm ~99.9997 do CSV).

**Totais servidos**: 47 categorias (39 base + 8 custom) × 6 séries = **282 séries**. As 8 custom aggregations são derivadas via álgebra Laspeyres em `scripts/build_custom_aggregations.R` a partir do `recon.csv` + `pesos.csv`. Proveniência migrou do campo `haver_code` (formato antigo `CPIUS:{cat}/{sid}/BLS-{sha}` + variantes) pro campo **`bls_code`** com formato simplificado (`CPIUS:{cat}` / `CPIUS:{cat}/Index`). Distinção var/idx/Weight dentro do mesmo lado (var/label vs idx/Index) é feita por `series_name`+`data_type`, não pelo code. Distinção base vs custom sai do próprio `category_code` (ex.: `core_ex_oer` vs `core`), não do code de proveniência. Migração idempotente rodada antes do main loop: linhas antigas (`haver_code LIKE 'CPIUS:%'`) sofrem `UPDATE` explícito `SET haver_code = NULL, bls_code = <novo>`.

## Pré-requisitos (na máquina corp)

- `opt_utils.database.SQLConnector` disponível (mesmo módulo do `sidra_itau.ipynb`)
- ODBC driver SQL Server configurado (mesmo que o notebook usa)
- Permissão de INSERT/DELETE em `OPT_Macro_Series_2` e `OPT_Macro_Series_Data_2`
- Diretório de trabalho: `pareto_cpius/`
- (Opcional mas recomendado) `BLS_API_KEY` exportado — sem chave, BLS API v2
  limita a 25 requests/dia, o que trava re-runs frequentes
- CSVs gerados pelo pipeline R existem em `data/`:
  - `data/cpi_cpius_recon.csv` (índice + var mm + var yoy, NSA + SA)
  - `data/cpi_cpius_indice.csv` (índice rebased jan/2000=100, NSA + SA)
  - `data/cpi_cpius_pesos.csv` (peso Relative Importance BLS, MVP = snapshot atual replicado)

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

**Objetivo:** confirmar que os 5 CSVs são lidos OK e a lista de 47 categorias
(39 base + 8 custom) × 2 sa_flags + Weight (2×) está correta. Não toca SQL, não
importa `opt_utils`.

```bash
python script_itau/load_cpius_to_sql.py --dry-run
```

**Sucesso:** imprime "78 (categoria, sa_flag) combinacoes" (recon+idx base,
39 × 2) + "39 categorias com Weight (RI BLS)" + "8 agregacoes custom +
NSA/SA" + "8 Weights custom derivados". Lista 47 cats × [NSA, SA, Weight x2
(label + Index)] = ~282 itens, cada um com N obs (~317 desde jan/2000). As
8 custom aparecem com tag `[CUSTOM]`. Imprime também os 2 `bls_code` por cat:
`CPIUS:{cat}` (var/label) e `CPIUS:{cat}/Index` (idx).

**Se falhar aqui:** problema é nos CSVs (rode `fetch_bls_cpiu.R` +
`fetch_bls_pesos.R` + `build_custom_aggregations.R`) ou nos labels em
`CATEGORY_LABELS` / `CUSTOM_LABELS` (faltaram códigos).

---

## Estágio 2 — `--check` (preflight read-only no SQL)

**Objetivo:** abrir conexão SQL e validar que: (a) o `SQLConnector` funciona
com `connector="pyodbc"` (b) as 2 tabelas existem (c) a coluna `bls_code`
existe em `OPT_Macro_Series_2` (necessária pra sync 2026-07-17-b) (d) a
coluna `description` aguenta nosso pior caso (~110 chars) (e) listar séries
tanto no formato NOVO (`bls_code LIKE 'CPIUS:%'`, serão reusadas) quanto no
ANTIGO (`haver_code LIKE 'CPIUS:%'`, pendentes de migração).

```bash
python script_itau/load_cpius_to_sql.py --check
```

**Sucesso:** 5 linhas `[OK]` e zero `[FAIL]`. Mostra contagem de linhas
atuais de cada tabela + duas listas: séries CPIUS no formato novo (0 na
primeira carga) e no formato antigo (pendentes de migração).

**Se falhar aqui:**
- `ModuleNotFoundError: opt_utils` → instalação corp quebrada
- erro de conexão pyodbc → credenciais/driver/DSN
- `[FAIL] OPT_Macro_Series_2` → permissão ou tabela com nome diferente
- `[FAIL] coluna bls_code NAO existe` → rodar `ALTER TABLE OPT_Macro_Series_2 ADD bls_code VARCHAR(255) NULL;`
- `[FAIL] description = VARCHAR(N)` com N<110 → mexer no schema OU encurtar
  as strings `description=` no loader

---

## Estágio 3 — smoke test (`--only all_items,core`)

**Objetivo:** gravar 12 séries (2 categorias × [NSA var/idx + SA var/idx + Weight label + Weight label Index]) e verificar no SSMS antes de soltar as 282 séries.

```bash
python script_itau/load_cpius_to_sql.py --only all_items,core
```

Pergunta `Confirma gravacao de ate 12 series no SQL? [s/N]` — responda `s`.

**Verificação no SSMS:**
```sql
SELECT series_id, series_name, data_type, haver_code, bls_code
FROM OPT_Macro_Series_2 WHERE bls_code LIKE 'CPIUS:all_items%'
   OR bls_code LIKE 'CPIUS:core%'
ORDER BY series_id;
-- esperado: 12 linhas (all_items × 6 + core × 6)
-- haver_code = NULL em todas (INSERT novo não seta o campo; migração de row
-- antiga faz UPDATE SET haver_code = NULL). bls_code em 4 valores:
--   CPIUS:all_items, CPIUS:all_items/Index, CPIUS:core, CPIUS:core/Index

-- Confirma que nenhuma linha CPIUS antiga sobrou pra estas cats:
SELECT COUNT(*) FROM OPT_Macro_Series_2
WHERE haver_code LIKE 'CPIUS:all_items%'
   OR haver_code LIKE 'CPIUS:core%';
-- esperado: 0 (a migração setou haver_code=NULL nas rows antigas).

SELECT s.series_name, s.data_type, COUNT(*) AS n
FROM OPT_Macro_Series_Data_2 d
JOIN OPT_Macro_Series_2 s ON s.series_id = d.series_id
WHERE s.bls_code LIKE 'CPIUS:all_items%' OR s.bls_code LIKE 'CPIUS:core%'
GROUP BY s.series_name, s.data_type
ORDER BY s.series_name, s.data_type;
-- esperado: 12 linhas, ~316-317 obs cada (jan/2000 → mês atual)
--   NSA (var):   n=316 (1o mês NaN diff)
--   NSA (idx):   n=317 (série completa)
--   SA  (var):   n=316
--   SA  (idx):   n=317
--   Weight (2x): n=317 cada; series_name repete label e label (Index);
--                bls_code do (Index) tem sufixo /Index (var_side vs Index_side).
--                all_items Weight deve ser 100.0 constante em todas as datas.

-- Confirma Weight duplicado com mesmos valores:
SELECT TOP 5 s.series_name, d.date, d.value
FROM OPT_Macro_Series_Data_2 d
JOIN OPT_Macro_Series_2 s ON s.series_id = d.series_id
WHERE s.bls_code LIKE 'CPIUS:core%' AND s.data_type = 'Weight'
ORDER BY d.date, s.series_name;
-- esperado: pra cada data, "CPI-U: ... (Core)" e "CPI-U: ... (Core) (Index)"
-- com o MESMO value.

SELECT TOP 5 * FROM OPT_Macro_Series_Data_2 WHERE series_id = <id_all_items_NSA_var>
ORDER BY date;
-- valores de referência em sim_output/OPT_Macro_Series_Data_2.csv
```

**Se algo estiver errado aqui, ANTES de continuar:**
```sql
-- rollback do smoke test (apaga só as 12 séries inseridas):
DELETE FROM OPT_Macro_Series_Data_2
WHERE series_id IN (SELECT series_id FROM OPT_Macro_Series_2
                    WHERE bls_code LIKE 'CPIUS:all_items%'
                       OR bls_code LIKE 'CPIUS:core%');
DELETE FROM OPT_Macro_Series_2
WHERE bls_code LIKE 'CPIUS:all_items%' OR bls_code LIKE 'CPIUS:core%';
```

---

## Estágio 4 — carga completa (47 categorias × 6 séries = 282)

**Objetivo:** gravar até 282 séries (39 base + 8 custom, cada uma × [NSA var,
NSA idx, SA var, SA idx, Weight label, Weight label Index]). Re-roda as 12
do Estágio 3 — `replace=True` apaga dados antigos antes do reinsert, sem
duplicar. Antes do main loop, `_migrate_haver_to_bls` reescreve qualquer linha
antiga (`haver_code LIKE 'CPIUS:%'`) das cats que estão no scope: `haver_code`
→ `NULL`, `bls_code` populado.

```bash
python script_itau/load_cpius_to_sql.py
```

Confirma `Confirma gravacao de ate 282 series no SQL? [s/N]` → `s`.

**Verificação:**
```sql
SELECT data_type, COUNT(*) AS n_series
FROM OPT_Macro_Series_2 WHERE bls_code LIKE 'CPIUS:%'
GROUP BY data_type;
-- esperado: NSA=94 (47 var + 47 idx), SA=94 (47 var + 47 idx), Weight=94 (47 × 2)

-- Distingue Weight label vs Weight label Index (via sufixo /Index em bls_code):
SELECT
  CASE WHEN bls_code LIKE '%/Index' THEN 'Weight (Index)' ELSE 'Weight (label)' END AS weight_role,
  COUNT(*) AS n
FROM OPT_Macro_Series_2
WHERE bls_code LIKE 'CPIUS:%' AND data_type = 'Weight'
GROUP BY CASE WHEN bls_code LIKE '%/Index' THEN 'Weight (Index)' ELSE 'Weight (label)' END;
-- esperado: Weight (label)=47, Weight (Index)=47

-- Base vs custom NÃO sai mais do bls_code (ambos usam CPIUS:{cat}). Sai do
-- próprio category_code. Se precisar contar, use a lista de category_codes
-- custom (rent_of_shelter, core_ex_oer, cpi_ex_oer, core_services_ex_shelter,
-- supercore_powell_old, core_services_ex_shelter_pubtrans_medical,
-- super_super_core, core_services_ex_volatiles):
SELECT COUNT(*) AS n_custom_series FROM OPT_Macro_Series_2
WHERE bls_code IN (
  'CPIUS:rent_of_shelter','CPIUS:rent_of_shelter/Index',
  'CPIUS:core_ex_oer','CPIUS:core_ex_oer/Index',
  'CPIUS:cpi_ex_oer','CPIUS:cpi_ex_oer/Index',
  'CPIUS:core_services_ex_shelter','CPIUS:core_services_ex_shelter/Index',
  'CPIUS:supercore_powell_old','CPIUS:supercore_powell_old/Index',
  'CPIUS:core_services_ex_shelter_pubtrans_medical','CPIUS:core_services_ex_shelter_pubtrans_medical/Index',
  'CPIUS:super_super_core','CPIUS:super_super_core/Index',
  'CPIUS:core_services_ex_volatiles','CPIUS:core_services_ex_volatiles/Index'
);
-- esperado: 48 (8 custom × 6 séries)

-- all_items peso constante = 100.0 em todas as datas:
SELECT MIN(value) AS wmin, MAX(value) AS wmax, COUNT(*) AS n
FROM OPT_Macro_Series_Data_2 d
JOIN OPT_Macro_Series_2 s ON s.series_id = d.series_id
WHERE s.bls_code LIKE 'CPIUS:all_items%' AND s.data_type = 'Weight';
-- esperado: wmin=100.0, wmax=100.0, n=634 (2 séries × 317 obs)

SELECT s.data_type, COUNT(*) AS n_obs
FROM OPT_Macro_Series_Data_2 d
JOIN OPT_Macro_Series_2 s ON s.series_id = d.series_id
WHERE s.bls_code LIKE 'CPIUS:%'
GROUP BY s.data_type;
-- NSA:    94 séries × ~316-318 obs
-- SA:     94 séries × ~316-318 obs
-- Weight: 94 séries × ~316-317 obs (47 label + 47 Index, mesmo valor)
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
