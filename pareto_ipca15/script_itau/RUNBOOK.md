# RUNBOOK — carga do pareto_ipca15 no SQL Itaú

Fork do runbook `pareto_ipca` pro **IPCA-15**. Procedimento em 6 estágios
(4 obrigatórios + 5 e 6 opcionais), com pontos de parada explícitos.
Namespace `IPCA15` no SQL é **estritamente disjunto** do IPCA cheio:
`bls_code='IPCA15:{cat}'`, `indicator='IPCA-15'`, `series_name` prefixo
`'IPCA-15: '`. Não há risco de colisão com rows do `pareto_ipca`.

## Diferenças críticas vs `pareto_ipca` (importante ler antes)

| Item | pareto_ipca | pareto_ipca15 |
|---|---|---|
| Janela | 2006-07 → atual | 2012-02 → atual |
| Base índice | dez/2006=100 | dez/2012=100 |
| `bls_code` | `IPCA:{cat}` | `IPCA15:{cat}` |
| `indicator` | `IPCA` | `IPCA-15` |
| `series_name` | `IPCA: {label}` | `IPCA-15: {label}` |
| Auditoria BCB | ativa (breakdowns mapeados) | só headline vs SGS 7478 (real); breakdowns viram diagnóstico do gap vs IPCA cheio |

## Pré-requisitos (na máquina corp)

- `opt_utils.database.SQLConnector` disponível
- ODBC driver SQL Server configurado
- Permissão de INSERT/DELETE em `OPT_Macro_Series_2` e `OPT_Macro_Series_Data_2`
- Coluna `bls_code` existe em `OPT_Macro_Series_2` (mesma coluna usada pelo `pareto_ipca`; se já rodou o outro loader, já tem)
- Diretório de trabalho: `pareto_ipca15/`
- CSVs gerados pelo pipeline R existem em `data/`:
  - `data/ipca15_pareto_recon.csv` (variação mensal)
  - `data/ipca15_pareto_indice.csv` (número-índice)
  - `data/ipca15_pareto_pesos.csv` (pesos Laspeyres — gerado junto com recon)

Se ainda não rodou o pipeline R:
```bash
cd pareto_ipca15
Rscript scripts/seed_ibge_history.R               # ~40s, MUDA (sem fetch BCB); gera os 3 CSVs
Rscript scripts/build_pareto_indice.R             # ~5s, gera ipca15_pareto_indice.csv
```
Validação BCB fica DESLIGADA por default (rotina). Pra confirmar o headline vs SGS 7478 (~0.00pp esperado) sob demanda, use `Rscript scripts/seed_ibge_history.R --with-bcb` ou rode `Rscript scripts/_audit_ibge_vs_bcb.R` que sempre valida.

---

## Estágio 1 — `--dry-run` (zero conexão SQL)

**Objetivo:** confirmar que os 3 CSVs (recon, indice, pesos) são lidos OK e a
lista de 28 categorias está correta. Não toca SQL, não importa `opt_utils`.

```bash
python script_itau/load_pareto_to_sql.py --dry-run
```

**Sucesso:** imprime "28 categorias" três vezes (recon / índice / pesos) e lista
28 itens (IPCA-15: Total, IPCA-15: Monitorados, IPCA-15: Livres, ...). Cada
linha mostra `Weight x2: N obs` (quando há peso) e 1 bls_code por cat
(`IPCA15:{cat}`, sem sufixo `/Index`).

**Se falhar aqui:** problema é nos CSVs (rode o pipeline R) ou nos labels em
`CATEGORY_LABELS` (faltaram códigos).

---

## Estágio 2 — `--check` (preflight read-only no SQL)

**Objetivo:** abrir conexão SQL e validar (a) `SQLConnector` funciona com
`connector="pyodbc"`, (b) as 2 tabelas existem, (c) coluna `bls_code` existe,
(d) `description` suporta ~95 chars, (e) listar séries IPCA-15 pré-existentes
(`bls_code LIKE 'IPCA15:%'` OU `haver_code LIKE 'PARETO_IPCA15:%'`).

```bash
python script_itau/load_pareto_to_sql.py --check
```

**Sucesso:** 4 linhas `[OK]` e zero `[FAIL]`. Depois, seção lista séries IPCA-15
já cadastradas (esperado 0 na primeira carga; namespace disjunto do IPCA cheio).

**Se falhar aqui:**
- `ModuleNotFoundError: opt_utils` → instalação local quebrada
- erro pyodbc → credenciais/driver/DSN
- `[FAIL] OPT_Macro_Series_2` → permissão ou tabela com nome diferente
- `[FAIL] coluna bls_code NAO existe` → rode `ALTER TABLE OPT_Macro_Series_2 ADD bls_code VARCHAR(255) NULL;` no SSMS antes de continuar
- `[FAIL] description = VARCHAR(N)` com N<95 → mexer no schema OU encurtar `description=` no loader

---

## Estágio 3 — smoke test (`--only livres,nucleo_ex0`)

**Objetivo:** gravar 8 séries (2 categorias × [var NSA, idx NSA, Weight-label,
Weight-Indice]) e verificar no SSMS antes de soltar a carga completa.

```bash
python script_itau/load_pareto_to_sql.py --only livres,nucleo_ex0
```

Pergunta `Confirma gravacao de ate 8 series no SQL? [s/N]` — responda `s`.
(Se nucleo_ex0 não tiver peso, o total desce pra 6.)

**Verificação no SSMS:**
```sql
SELECT series_id, series_name, data_type, haver_code, bls_code
FROM OPT_Macro_Series_2
WHERE bls_code LIKE 'IPCA15:livres%' OR bls_code LIKE 'IPCA15:nucleo_ex0%'
ORDER BY series_id;
-- esperado: ate 8 linhas; haver_code = NULL em todas (INSERT novo nao seta);
-- bls_code em 2 valores unicos:
--   IPCA15:livres      (4 rows: var NSA, idx NSA, Weight label, Weight Indice)
--   IPCA15:nucleo_ex0  (2 rows: var NSA, idx NSA — sem peso)
-- Distincao var-side vs idx-side sai do series_name ("(Indice)" no fim).

SELECT s.series_name, s.data_type, COUNT(*) AS n
FROM OPT_Macro_Series_Data_2 d
JOIN OPT_Macro_Series_2 s ON s.series_id = d.series_id
WHERE s.bls_code LIKE 'IPCA15:livres%' OR s.bls_code LIKE 'IPCA15:nucleo_ex0%'
GROUP BY s.series_name, s.data_type
ORDER BY s.series_name, s.data_type;
-- esperado: N obs por (series_name, data_type), sendo N ~ meses desde fev/2012

-- Confirma Weight duplicado com mesmos valores:
SELECT TOP 5 s.series_name, d.date, d.value
FROM OPT_Macro_Series_Data_2 d
JOIN OPT_Macro_Series_2 s ON s.series_id = d.series_id
WHERE s.bls_code = 'IPCA15:livres' AND s.data_type = 'Weight'
ORDER BY d.date, s.series_name;
-- esperado: pra cada data, "IPCA-15: Livres" e "IPCA-15: Livres (Indice)"
-- com o MESMO value.
```

**Rollback do smoke test (se algo errado, antes de continuar):**
```sql
DELETE FROM OPT_Macro_Series_Data_2
WHERE series_id IN (SELECT series_id FROM OPT_Macro_Series_2
                    WHERE bls_code LIKE 'IPCA15:livres%'
                       OR bls_code LIKE 'IPCA15:nucleo_ex0%');
DELETE FROM OPT_Macro_Series_2
WHERE bls_code LIKE 'IPCA15:livres%' OR bls_code LIKE 'IPCA15:nucleo_ex0%';
```

---

## Estágio 4 — carga completa NSA (28 categorias)

**Objetivo:** gravar até **100 séries** (28 var + 28 idx + até 22 pesos × 2)
com `data_type='NSA'`/`'Weight'`. Re-roda séries já cadastradas no Estágio 3 —
`replace=True` apaga dados antigos antes do reinsert.

```bash
python script_itau/load_pareto_to_sql.py
```

Confirma `Confirma gravacao de ate N series no SQL? [s/N]` (N ≤ 100) → `s`.

**Verificação:**
```sql
SELECT data_type, COUNT(*) AS n_series
FROM OPT_Macro_Series_2 WHERE bls_code LIKE 'IPCA15:%'
GROUP BY data_type;
-- esperado: NSA=56 (28 var + 28 idx), Weight=ate 44 (ate 22 pesos x 2 — label + Indice).
-- nucleos estatisticos MA/MS/DP/P55/medio/difusao nao tem peso.

-- Distingue Weight-label (par com var) vs Weight-Indice (par com idx).
SELECT
  CASE WHEN series_name LIKE '%(Indice)' THEN 'Weight (Indice)' ELSE 'Weight (label)' END AS weight_role,
  COUNT(*) AS n
FROM OPT_Macro_Series_2
WHERE bls_code LIKE 'IPCA15:%' AND data_type = 'Weight'
GROUP BY CASE WHEN series_name LIKE '%(Indice)' THEN 'Weight (Indice)' ELSE 'Weight (label)' END;
-- esperado: Weight (label)=22, Weight (Indice)=22.

-- total (headline) Weight = 100 constante:
SELECT MIN(value) AS wmin, MAX(value) AS wmax, COUNT(*) AS n
FROM OPT_Macro_Series_Data_2 d
JOIN OPT_Macro_Series_2 s ON s.series_id = d.series_id
WHERE s.bls_code = 'IPCA15:total' AND s.data_type = 'Weight';
-- esperado: wmin=100.0, wmax=100.0.

SELECT s.data_type, COUNT(*) AS n_obs
FROM OPT_Macro_Series_Data_2 d
JOIN OPT_Macro_Series_2 s ON s.series_id = d.series_id
WHERE s.bls_code LIKE 'IPCA15:%'
GROUP BY s.data_type;
-- NSA:    56 series x N obs (N = meses desde fev/2012 — cresce a cada IPCA-15)
-- Weight: ate 44 series x N obs (22 pares label + Indice)
```

---

## Estágio 5 (opcional) — versão dessazonalizada (X-13)

**Objetivo:** gerar e gravar `data_type='SA'` pras 56 séries (28 var + 28 idx),
totalizando 112 séries NSA+SA (+ até 44 Weight×2 = 156 no máximo).
Só faz sentido se `x13as` está instalado no ambiente.

```bash
python script_itau/load_pareto_to_sql.py --sa
```

Pergunta confirmação pra até 156 séries. Cada série pode levar alguns segundos
no X-13 (pode demorar 5-10min total).

Se uma categoria falhar no X-13, o loader imprime `[WARN]` e segue.
```sql
SELECT data_type, COUNT(*) FROM OPT_Macro_Series_2
WHERE bls_code LIKE 'IPCA15:%'
GROUP BY data_type;
-- esperado: NSA=56, SA<=56 (quantas dessazonalizaram OK), Weight=ate 44
```

### Estágio 5.1 — workarounds SA conhecidos (herdados do pareto_ipca)

Os mesmos 3 workarounds do `pareto_ipca` provavelmente aparecem aqui também
(mesma metodologia, apenas fonte SIDRA diferente):

**(a) `IPCA-15: Servicos (Indice)` SA** — X-13 falha com TD peak warning.
Workaround: reconstrói idx_SA via identidade `idx[t]=idx[t-1]·(1+var[t]/100)`
a partir do var_SA.
```bash
python script_itau/_fix_servicos_idx_sa.py
```

**(b) `IPCA-15: Nucleo DP` SA + `IPCA-15: Nucleo Medio` SA** — wrapper corp
morre com `'NoneType' object has no attribute 'startswith'` (bug do
`x13_custom`). Workaround em 2 passos:
```bash
Rscript scripts/_sa_dp_nucleo_medio.R
python script_itau/_fix_dp_medio_sa.py
```

**Atenção — bug do upsert por chave natural:** se já existem metas legadas
Haver com `series_name` igual e `data_type='SA'`, o `sidra_to_sql` faz upsert
na meta legada. Mitigação: deletar a meta legada antes de rodar o workaround.

---

## Estágio 6 (opcional) — validação SA contra Haver

⚠️ **Pendente pra IPCA-15**: SA contra Haver depende de códigos Haver
IPCA-15 específicos (diferentes dos do IPCA cheio). Pra headline, comparar
com SGS 7478 (BCB) via seção [5a] do reconstruct já cobre o essencial;
breakdowns SA IPCA-15 vs Haver ficam pendentes até códigos serem mapeados.

---

## Rollback completo (se precisar desfazer tudo)

```sql
-- Namespace IPCA15 disjunto — este DELETE nao toca rows do pareto_ipca:
DELETE FROM OPT_Macro_Series_Data_2
WHERE series_id IN (SELECT series_id FROM OPT_Macro_Series_2
                    WHERE bls_code LIKE 'IPCA15:%');
DELETE FROM OPT_Macro_Series_2 WHERE bls_code LIKE 'IPCA15:%';

-- Rollback defensivo (caso alguem tenha gravado formato ancestral):
DELETE FROM OPT_Macro_Series_Data_2
WHERE series_id IN (SELECT series_id FROM OPT_Macro_Series_2
                    WHERE haver_code LIKE 'PARETO_IPCA15:%');
DELETE FROM OPT_Macro_Series_2 WHERE haver_code LIKE 'PARETO_IPCA15:%';
```

Isso só remove o que este loader inseriu (filtra por `bls_code LIKE 'IPCA15:%'`
ou `haver_code LIKE 'PARETO_IPCA15:%'`) — não afeta as séries do pareto_ipca
(namespace `IPCA:%`) nem as SIDRA inseridas pelo `sidra_itau.ipynb`.

---

## Re-execução periódica (após IBGE soltar novo IPCA-15)

Pipeline incremental — só recomputa janela recente (não refaz histórico):
```bash
cd pareto_ipca15
Rscript scripts/reconstruct_ipca.R                    # default 24 meses (T7062) + valida vs SGS 7478
Rscript scripts/build_pareto_indice.R
python script_itau/load_pareto_to_sql.py --no-confirm # sem prompt
```

`reconstruct_ipca.R` sem args usa T7062 (POF 2017-18, IPCA-15) e janela dos
últimos 24 meses, SEM fetch BCB (rotina de atualização é muda por default).
Para reconstruir toda a história (raro): use `seed_ibge_history.R`. Se quiser
validar `total` vs SGS 7478 (~0.00pp) numa rodada específica, passe `--with-bcb`.

`--no-confirm` pula o prompt interativo:
```bash
python script_itau/load_pareto_to_sql.py --no-confirm > load_$(date +%Y%m%d).log 2>&1
```

---

## Comparação contra simulação local

Os valores esperados estão em `script_itau/sim_output/OPT_Macro_Series_Data_2.csv`
(gerado por `simulate_pareto_to_sql.py --save`). Se uma linha no SQL não bater
com a equivalente no CSV simulado, há discrepância no write — investigar
`sidra_to_sql`.

```sql
SELECT TOP 10 series_id, date, value FROM OPT_Macro_Series_Data_2
WHERE series_id IN (SELECT series_id FROM OPT_Macro_Series_2
                    WHERE bls_code LIKE 'IPCA15:livres%')
ORDER BY series_id, date;
```
