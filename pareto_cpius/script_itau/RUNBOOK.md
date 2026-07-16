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
| `haver_code` → novo campo `ons_code` | ⏳ pendente (mesmo do pareto_ipca) | ⏳ pendente | — |
| Pesos (BLS Table 6, time-varying) | ✅ fase 2 entregue (RI Dez 2000-2025 + ajuste implícito BLS) | ⏳ precisa da migração inicial | — |
| SA nativa BLS (sem X-13) | ✅ já é assim (`data_type='SA'` vem direto de CUSR0000<item>) | idem quando migrar | — |

**Diferença estrutural vs `pareto_ipca`:** cada categoria gera até **5 séries**
(NSA var, NSA idx, SA var, SA idx, Peso) porque BLS publica SA nativo — não
precisa de X-13. **Peso é time-varying** (fase 2 entregue): base RI Dez de cada
ano 2000-2025 + ajuste implícito mensal `w_i(m) = w_i(Dez) × I_i(m) / I_i(Dez)`
seguindo metodologia BLS "monthly relative importance". Total: 37 × 5 = **185
séries** com peso; sem peso, 37 × 4 = 148.

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
export BLS_API_KEY=<sua_chave>          # opcional mas recomendado
Rscript scripts/fetch_bls_cpiu.R           # 2000 → atual, ~30s com chave
python scripts/parse_historical_ri.py      # RI Dez 2000-2025 → pesos_annual.csv (~2s)
Rscript scripts/fetch_bls_pesos.R          # peso mensal ajustado (Fase 2), ~1s
# (opcional) rebase pra outra base:
BASE_DATE=2019-12-01 Rscript scripts/build_cpi_indice.R
```

Requer: **Python 3** com `openpyxl` (`pip install openpyxl`) pra parsear os xlsx BLS.

---

## Estágio 1 — `--dry-run` (zero conexão SQL)

**Objetivo:** confirmar que os 3 CSVs são lidos OK e a lista de 37 categorias
× 2 sa_flags + peso está correta. Não toca SQL, não importa `opt_utils`.

```bash
python script_itau/load_cpius_to_sql.py --dry-run
```

**Sucesso:** imprime "74 (categoria, sa_flag) combinacoes" (recon+idx) e
"37 categorias com peso (Relative Importance BLS)". Lista 37 cats × [NSA,
SA, Peso] = ~185 itens, cada um com N obs (~317 desde jan/2000).

**Se falhar aqui:** problema é nos CSVs (rode `fetch_bls_cpiu.R` +
`fetch_bls_pesos.R`) ou nos labels em `CATEGORY_LABELS` (faltaram códigos).

---

## Estágio 2 — `--check` (preflight read-only no SQL)

**Objetivo:** abrir conexão SQL e validar que: (a) o `SQLConnector` funciona
com `connector="pyodbc"` (b) as 2 tabelas existem (c) a coluna `description`
aguenta nosso pior caso (~110 chars) (d) listar séries com
`haver_code LIKE 'CPIUS:%'` que já existam (de runs anteriores).

```bash
python script_itau/load_cpius_to_sql.py --check
```

**Sucesso:** 4 linhas `[OK]` e zero `[FAIL]`. Mostra contagem de linhas
atuais de cada tabela + lista de séries CPIUS já cadastradas (0 na primeira
carga).

**Se falhar aqui:**
- `ModuleNotFoundError: opt_utils` → instalação corp quebrada
- erro de conexão pyodbc → credenciais/driver/DSN
- `[FAIL] OPT_Macro_Series_2` → permissão ou tabela com nome diferente
- `[FAIL] description = VARCHAR(N)` com N<110 → mexer no schema OU encurtar
  as strings `description=` no loader

---

## Estágio 3 — smoke test (`--only all_items,core`)

**Objetivo:** gravar 10 séries (2 categorias × [NSA var/idx + SA var/idx + Peso]) e
verificar no SSMS antes de soltar as 185 séries.

```bash
python script_itau/load_cpius_to_sql.py --only all_items,core
```

Pergunta `Confirma gravacao de ate 10 series no SQL? [s/N]` — responda `s`.

**Verificação no SSMS:**
```sql
SELECT * FROM OPT_Macro_Series_2 WHERE haver_code LIKE 'CPIUS:%';
-- esperado: 10 linhas (all_items × 5 + core × 5)

SELECT s.series_name, s.data_type, COUNT(*) AS n
FROM OPT_Macro_Series_Data_2 d
JOIN OPT_Macro_Series_2 s ON s.series_id = d.series_id
WHERE s.haver_code LIKE 'CPIUS:%'
GROUP BY s.series_name, s.data_type
ORDER BY s.series_name, s.data_type;
-- esperado: 10 linhas, ~316-317 obs cada (jan/2000 → mês atual)
--   var:  n=316 (1o mês NaN diff)
--   idx:  n=317 (série completa)
--   Peso: n=317 (série completa, valor variando mês-a-mês; ajuste implícito BLS)

SELECT TOP 5 * FROM OPT_Macro_Series_Data_2 WHERE series_id = <id_all_items_NSA_var>
ORDER BY date;
-- valores de referência em sim_output/OPT_Macro_Series_Data_2.csv
```

**Se algo estiver errado aqui, ANTES de continuar:**
```sql
-- rollback do smoke test (apaga só as 10 séries inseridas):
DELETE FROM OPT_Macro_Series_Data_2
WHERE series_id IN (SELECT series_id FROM OPT_Macro_Series_2
                    WHERE haver_code LIKE 'CPIUS:%');
DELETE FROM OPT_Macro_Series_2 WHERE haver_code LIKE 'CPIUS:%';
```

---

## Estágio 4 — carga completa (37 categorias × 5 séries = 185)

**Objetivo:** gravar até 185 séries (37 var NSA + 37 idx NSA + 37 var SA + 37
idx SA + 37 Peso). Re-roda as 10 do Estágio 3 — `replace=True` apaga dados
antigos antes do reinsert, sem duplicar.

```bash
python script_itau/load_cpius_to_sql.py
```

Confirma `Confirma gravacao de ate 185 series no SQL? [s/N]` → `s`.

**Verificação:**
```sql
SELECT data_type, COUNT(*) AS n_series
FROM OPT_Macro_Series_2 WHERE haver_code LIKE 'CPIUS:%'
GROUP BY data_type;
-- esperado: NSA=74 (37 var + 37 idx), SA=74 (37 var + 37 idx), Peso=37

SELECT s.data_type, COUNT(*) AS n_obs
FROM OPT_Macro_Series_Data_2 d
JOIN OPT_Macro_Series_2 s ON s.series_id = d.series_id
WHERE s.haver_code LIKE 'CPIUS:%'
GROUP BY s.data_type;
-- NSA:  74 séries × ~316-317 obs
-- SA:   74 séries × ~316-317 obs
-- Peso: 37 séries × 317 obs (RI time-varying, Dez 2000-2025 + ajuste implícito)
```

---

## Rollback completo (se precisar desfazer tudo)

```sql
DELETE FROM OPT_Macro_Series_Data_2
WHERE series_id IN (SELECT series_id FROM OPT_Macro_Series_2
                    WHERE haver_code LIKE 'CPIUS:%');

DELETE FROM OPT_Macro_Series_2 WHERE haver_code LIKE 'CPIUS:%';
```

Isso só remove o que este loader inseriu (filtra pelo prefixo `CPIUS:` no
haver_code) — não afeta as séries SIDRA/IPCA nem as do Haver.

---

## Re-execução periódica (após BLS soltar novo release)

BLS solta CPI-U mensalmente ~10-15 do mês seguinte (release calendar em
https://www.bls.gov/schedule/news_release/cpi.htm). Pipeline incremental:

```bash
cd pareto_cpius
Rscript scripts/fetch_bls_cpiu.R                       # re-baixa preços (rápido)
Rscript scripts/fetch_bls_pesos.R                      # regera pesos ajustados (parse RI só se novo Dez rolou)
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
WHERE s.haver_code LIKE 'CPIUS:all_items/%'
ORDER BY s.data_type, d.date;
```
Compare com:
```bash
head -20 script_itau/sim_output/OPT_Macro_Series_Data_2.csv
```

Diferença esperada: no SQL as datas são **último dia do mês** (convenção Haver
corp — o loader converte via `MonthEnd(0)`), no CSV do simulate ficam no dia
01 (formato do CSV upstream). Os valores devem bater.
