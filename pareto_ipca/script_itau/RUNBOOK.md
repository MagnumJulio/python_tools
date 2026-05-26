# RUNBOOK — carga do pareto_ipca no SQL Itaú

Procedimento controlado, em 5 estágios, com pontos de parada explícitos.
Cada estágio é independente — se algo der errado, dá pra parar e investigar
sem ter sujado o banco.

## Pré-requisitos (na máquina corp)

- `opt_utils.database.SQLConnector` disponível (mesmo módulo do `sidra_itau.ipynb`)
- ODBC driver SQL Server configurado (mesmo que o notebook usa)
- Permissão de INSERT/DELETE em `OPT_Macro_Series_2` e `OPT_Macro_Data_2`
- Diretório de trabalho: `pareto_ipca/`
- CSVs gerados pelo pipeline R existem em `data/`:
  - `data/ipca_pareto_recon.csv` (variação mensal)
  - `data/ipca_pareto_indice.csv` (número-índice)

Se ainda não rodou o pipeline R:
```bash
cd pareto_ipca
Rscript scripts/seed_ibge_history.R     # ~50s, gera ipca_pareto_recon.csv
Rscript scripts/build_pareto_indice.R   # ~5s, gera ipca_pareto_indice.csv
```

---

## Estágio 1 — `--dry-run` (zero conexão SQL)

**Objetivo:** confirmar que os 2 CSVs são lidos OK e a lista de 25 séries
está correta. Não toca SQL, não importa `opt_utils`.

```bash
python script_itau/load_pareto_to_sql.py --dry-run
```

**Sucesso:** imprime "25 categorias" duas vezes e lista 25 itens
(IPCA: Monitorados, IPCA: Livres, ..., IPCA: Indice de Difusao).
**Se falhar aqui:** problema é nos CSVs (rode o pipeline R) ou nos labels
em `CATEGORY_LABELS` (faltaram códigos).

---

## Estágio 2 — `--check` (preflight read-only no SQL)

**Objetivo:** abrir conexão SQL e validar que: (a) o `SQLConnector` realmente
funciona com `connector="pyodbc"` (b) as 2 tabelas existem (c) a coluna
`description` aguenta nosso pior caso (~95 chars) (d) listar séries com
`sidra_code LIKE 'PARETO_IPCA:%'` que já existam (de runs anteriores).

```bash
python script_itau/load_pareto_to_sql.py --check
```

**Sucesso:** 4 linhas `[OK]` e zero `[FAIL]`. Mostra contagem de linhas
atuais de cada tabela + lista de séries PARETO_IPCA já cadastradas.

**Se falhar aqui:**
- `ModuleNotFoundError: opt_utils` → instalação local quebrada
- erro de conexão pyodbc → credenciais/driver/DSN
- `[FAIL] OPT_Macro_Series_2` → permissão ou tabela com nome diferente
- `[FAIL] description = VARCHAR(N)` com N<95 → mexer no schema OU encurtar `description=` no loader

---

## Estágio 3 — smoke test (`--only livres,nucleo_ex0`)

**Objetivo:** gravar 4 séries (2 categorias × {variação, índice}) e verificar
no SSMS antes de soltar as 50 séries.

```bash
python script_itau/load_pareto_to_sql.py --only livres,nucleo_ex0
```

Pergunta `Confirma gravacao de ate 4 series no SQL? [s/N]` — responda `s`.

**Verificação no SSMS:**
```sql
SELECT * FROM OPT_Macro_Series_2 WHERE sidra_code LIKE 'PARETO_IPCA:%';
-- esperado: 4 linhas (livres var/idx + nucleo_ex0 var/idx)

SELECT series_id, COUNT(*) AS n FROM OPT_Macro_Data_2
WHERE series_id IN (SELECT series_id FROM OPT_Macro_Series_2
                    WHERE sidra_code LIKE 'PARETO_IPCA:%')
GROUP BY series_id;
-- esperado: 4 linhas, cada uma com n=238 (jul/2006 a abr/2026)

SELECT TOP 5 * FROM OPT_Macro_Data_2 WHERE series_id = <id_da_livres_var>
ORDER BY date;
-- esperado: 2006-07-01 valor=0.130644, 2006-08-01 valor=0.085540, etc.
-- (esses valores estão em sim_output/OPT_Macro_Data_2.csv pra conferência)
```

**Se algo estiver errado aqui, ANTES de continuar:**
```sql
-- rollback do smoke test (apaga só as 4 séries inseridas):
DELETE FROM OPT_Macro_Data_2
WHERE series_id IN (SELECT series_id FROM OPT_Macro_Series_2
                    WHERE sidra_code LIKE 'PARETO_IPCA:%');
DELETE FROM OPT_Macro_Series_2 WHERE sidra_code LIKE 'PARETO_IPCA:%';
```

---

## Estágio 4 — carga completa NSA (25 categorias)

**Objetivo:** gravar as 50 séries (25 var + 25 idx) com `data_type='NSA'`.
Re-roda séries já cadastradas no Estágio 3 — `replace=True` apaga dados
antigos antes do reinsert, sem duplicar.

```bash
python script_itau/load_pareto_to_sql.py
```

Confirma `Confirma gravacao de ate 50 series no SQL? [s/N]` → `s`.

**Verificação:**
```sql
SELECT COUNT(*) FROM OPT_Macro_Series_2 WHERE sidra_code LIKE 'PARETO_IPCA:%';
-- esperado: 50

SELECT COUNT(*) FROM OPT_Macro_Data_2
WHERE series_id IN (SELECT series_id FROM OPT_Macro_Series_2
                    WHERE sidra_code LIKE 'PARETO_IPCA:%');
-- esperado: 11900  (50 séries × 238 obs)
```

---

## Estágio 5 (opcional) — versão dessazonalizada (X-13)

**Objetivo:** gerar e gravar `data_type='SA'` pras 50 séries (total: 100).
Só faz sentido se `x13as` está instalado no ambiente.

```bash
python script_itau/load_pareto_to_sql.py --sa
```

Pergunta confirmação pra 100 séries. Cada série pode levar alguns segundos
no X-13 (pode demorar 5-10min total).

Se uma categoria falhar no X-13, o loader imprime `[WARN]` e segue —
não bloqueia as outras. Verifique no fim:
```sql
SELECT data_type, COUNT(*) FROM OPT_Macro_Series_2
WHERE sidra_code LIKE 'PARETO_IPCA:%'
GROUP BY data_type;
-- esperado: NSA=50, SA<=50 (quantas dessazonalizaram OK)
```

---

## Rollback completo (se precisar desfazer tudo)

```sql
DELETE FROM OPT_Macro_Data_2
WHERE series_id IN (SELECT series_id FROM OPT_Macro_Series_2
                    WHERE sidra_code LIKE 'PARETO_IPCA:%');

DELETE FROM OPT_Macro_Series_2 WHERE sidra_code LIKE 'PARETO_IPCA:%';
```

Isso só remove o que esse loader inseriu (filtra pelo prefixo
`PARETO_IPCA:` no sidra_code) — não afeta as séries SIDRA inseridas pelo
`sidra_itau.ipynb`.

---

## Re-execução periódica (após IBGE soltar novo mês)

Pipeline incremental — só recomputa janela recente:
```bash
cd pareto_ipca
Rscript scripts/reconstruct_ipca.R                    # default últimos 24 meses
Rscript scripts/build_pareto_indice.R
python script_itau/load_pareto_to_sql.py --no-confirm # sem prompt
```

`--no-confirm` é útil pra agendar via Task Scheduler. Mantém `--check` e
log de gravação no stdout pra auditoria.

---

## Comparação contra simulação local

Os valores esperados estão em `script_itau/sim_output/OPT_Macro_Data_2.csv`
(gerado por `simulate_pareto_to_sql.py --save`). Se uma linha qualquer no
SQL não bater com a equivalente no CSV simulado, há discrepância no
write — investigar `sidra_to_sql`.

```sql
SELECT TOP 10 series_id, date, value FROM OPT_Macro_Data_2
WHERE series_id IN (SELECT series_id FROM OPT_Macro_Series_2
                    WHERE sidra_code LIKE 'PARETO_IPCA:livres/V63%')
ORDER BY series_id, date;
```
Compare com:
```bash
head -15 script_itau/sim_output/OPT_Macro_Data_2.csv | grep -E "^2006|series_id"
```
