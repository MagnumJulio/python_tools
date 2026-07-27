# RUNBOOK — carga do pareto_ipca no SQL Itaú

Procedimento controlado, em 6 estágios (4 obrigatórios + 5 e 6 opcionais),
com pontos de parada explícitos. Cada estágio é independente — se algo der
errado, dá pra parar e investigar sem ter sujado o banco.

## Sync local ↔ máquina corp (deltas conhecidos)

Este repo local diverge da cópia da máquina corp em pontos rastreados abaixo.
Ao migrar mudanças de um lado pro outro, revisar item a item.

| Delta | Estado local | Estado corp | Aplicado em |
|---|---|---|---|
| Sufixo `(Peso)` em `series_name` | ❌ removido — peso compartilha `series_name` com NSA, só `data_type` difere | ❌ removido (fonte da mudança) | 2026-07-14 |
| Categoria `total` (IPCA headline) | ✅ existe — R exporta `ipca_oficial` como `total` var/idx/weight | ⚠️ existe no `CATEGORY_LABELS` como `ipca_total` (label mapping) — precisa **renomear pra `total`** e garantir que o R do corp também exporta | 2026-07-14 (local) |
| Bloco `PESO_ONLY` no loader | ❌ removido (código morto pós-`total`) | ⚠️ pode ainda existir referenciando `ipca_total` — remover ao sincronizar | 2026-07-14 (local) |
| `data_type="Weight"` (era `"Peso"`) | ✅ sync 2026-07-17 | migração faz Peso→Weight nas linhas antigas | 2026-07-17 |
| Weight gravado 2× (label + label Indice) | ✅ sync 2026-07-17 (par com var e par com idx) | ✅ frontend depende disso pra casar peso via series_name+country+indicator | 2026-07-17 |
| Code simplificado + campo `bls_code` | ✅ sync 2026-07-17 (2 codes) → sync 2026-07-27 (colapso pra `IPCA:{cat}` unico, sem `/Index`); INSERTs novos não setam `haver_code` (fica `NULL` por default) | precisa ALTER TABLE `ADD bls_code VARCHAR(255) NULL` se ainda não tiver | 2026-07-27 |
| Migração de rows antigas (haver_code OU bls_code com `/Index`) | ✅ `_migrate_pareto_to_current` roda antes do main loop (idempotente); cobre 3 estados: `haver_code LIKE 'PARETO_IPCA:%'`, `bls_code LIKE 'IPCA:%/Index'`, e formato final | ⚠️ rodar 1x no corp; próximos runs viram no-op | 2026-07-27 |

**Não reintroduzir `f"{label} (Peso)"`** nem `data_type="Peso"` ao mesclar código.

## Pré-requisitos (na máquina corp)

- `opt_utils.database.SQLConnector` disponível (mesmo módulo do `sidra_itau.ipynb`)
- ODBC driver SQL Server configurado (mesmo que o notebook usa)
- Permissão de INSERT/DELETE em `OPT_Macro_Series_2` e `OPT_Macro_Series_Data_2`
- Diretório de trabalho: `pareto_ipca/`
- CSVs gerados pelo pipeline R existem em `data/`:
  - `data/ipca_pareto_recon.csv` (variação mensal)
  - `data/ipca_pareto_indice.csv` (número-índice)
  - `data/ipca_pareto_pesos.csv` (pesos Laspeyres — gerado junto com recon)

Se ainda não rodou o pipeline R:
```bash
cd pareto_ipca
Rscript scripts/seed_ibge_history.R              # ~50s, gera ipca_pareto_recon.csv (+ pesos)
Rscript scripts/build_pareto_indice.R            # ~5s,  gera ipca_pareto_indice.csv
# Opcional em release day (BCB fora do ar / lento):
Rscript scripts/seed_ibge_history.R --no-bcb     # pula validação vs SGS
```
`--no-bcb` também aceito pelo `reconstruct_ipca.R`; propagado ao subprocesso
via env var `SKIP_BCB_VALIDATION=1`.

---

## Estágio 1 — `--dry-run` (zero conexão SQL)

**Objetivo:** confirmar que os 3 CSVs (recon, indice, pesos) são lidos OK e
a lista de 28 categorias está correta. Não toca SQL, não importa `opt_utils`.

```bash
python script_itau/load_pareto_to_sql.py --dry-run
```

**Sucesso:** imprime "28 categorias" três vezes (recon / índice / pesos) e lista
28 itens (IPCA: Total, IPCA: Monitorados, IPCA: Livres, ..., IPCA: Indice de Difusao, IPCA: Nucleo P55, IPCA: Nucleo Medio). Cada linha mostra `Weight x2: N obs` (quando há peso) e 1 bls_code por cat (`IPCA:{cat}`, sem sufixo `/Index` — sync 2026-07-27).
**Se falhar aqui:** problema é nos CSVs (rode o pipeline R) ou nos labels
em `CATEGORY_LABELS` (faltaram códigos).

---

## Estágio 2 — `--check` (preflight read-only no SQL)

**Objetivo:** abrir conexão SQL e validar que: (a) o `SQLConnector` realmente
funciona com `connector="pyodbc"` (b) as 2 tabelas existem (c) a coluna
**`bls_code`** existe em `OPT_Macro_Series_2` (d) a coluna `description`
aguenta nosso pior caso (~95 chars) (e) listar séries pré-existentes em
qualquer um dos 3 estados possíveis: **ancestral** (`haver_code LIKE
'PARETO_IPCA:%'`), **intermediário** (`bls_code LIKE 'IPCA:%/Index'`,
sync 2026-07-17), ou **atual** (`bls_code = 'IPCA:{cat}'`, sync 2026-07-27).
Rows fora do formato atual são normalizadas antes do main loop.

```bash
python script_itau/load_pareto_to_sql.py --check
```

**Sucesso:** 4 linhas `[OK]` e zero `[FAIL]` (OPT_Macro_Series_2 acessível,
OPT_Macro_Series_Data_2 acessível, coluna bls_code presente, description
com largura suficiente). Depois, seção lista consolidada de séries IPCA em
qualquer formato (ancestral haver, intermediário `/Index`, ou atual).
Qualquer row fora do formato atual é normalizada antes do main loop.

**Se falhar aqui:**
- `ModuleNotFoundError: opt_utils` → instalação local quebrada
- erro de conexão pyodbc → credenciais/driver/DSN
- `[FAIL] OPT_Macro_Series_2` → permissão ou tabela com nome diferente
- `[FAIL] coluna bls_code NAO existe` → rode `ALTER TABLE OPT_Macro_Series_2 ADD bls_code VARCHAR(255) NULL;` no SSMS antes de continuar
- `[FAIL] description = VARCHAR(N)` com N<95 → mexer no schema OU encurtar `description=` no loader

---

## Estágio 3 — smoke test (`--only livres,nucleo_ex0`)

**Objetivo:** gravar 8 séries (2 categorias × [var NSA, idx NSA, Weight-label,
Weight-Indice]) e verificar no SSMS antes de soltar a carga completa. Se já
havia linhas antigas dessas cats em qualquer estado (`haver_code LIKE
'PARETO_IPCA:livres/%'` OU `bls_code LIKE 'IPCA:livres/Index'`), a migração
antes do main loop normaliza pro formato atual e reaproveita os `series_id`
— nenhum INSERT duplicado.

```bash
python script_itau/load_pareto_to_sql.py --only livres,nucleo_ex0
```

Pergunta `Confirma gravacao de ate 8 series no SQL? [s/N]` — responda `s`.
(Se nucleo_ex0 não tiver peso — pode não ter — o total desce pra 6.)

**Verificação no SSMS:**
```sql
SELECT series_id, series_name, data_type, haver_code, bls_code
FROM OPT_Macro_Series_2
WHERE bls_code LIKE 'IPCA:livres%' OR bls_code LIKE 'IPCA:nucleo_ex0%'
ORDER BY series_id;
-- esperado: até 8 linhas; haver_code = NULL em todas (INSERT novo não seta o
-- campo; migração de row antiga faz UPDATE SET haver_code = NULL);
-- bls_code em 2 valores unicos (sync 2026-07-27, sem sufixo /Index):
--   IPCA:livres  (compartilhado por 4 rows: var NSA, idx NSA, Weight label, Weight Indice)
--   IPCA:nucleo_ex0  (mesma coisa; nucleo_ex0 nao tem peso, entao 2 rows)
-- Distincao var-side vs idx-side sai do series_name ("(Indice)" no fim).

-- Confirma que nenhuma linha PARETO_IPCA nem bls_code /Index sobrou pra estas cats:
SELECT COUNT(*) FROM OPT_Macro_Series_2
WHERE haver_code LIKE 'PARETO_IPCA:livres%'
   OR haver_code LIKE 'PARETO_IPCA:nucleo_ex0%'
   OR bls_code   LIKE 'IPCA:livres/Index%'
   OR bls_code   LIKE 'IPCA:nucleo_ex0/Index%';
-- esperado: 0 (migracao setou haver_code=NULL e colapsou /Index).

SELECT s.series_name, s.data_type, COUNT(*) AS n
FROM OPT_Macro_Series_Data_2 d
JOIN OPT_Macro_Series_2 s ON s.series_id = d.series_id
WHERE s.bls_code LIKE 'IPCA:livres%' OR s.bls_code LIKE 'IPCA:nucleo_ex0%'
GROUP BY s.series_name, s.data_type
ORDER BY s.series_name, s.data_type;
-- esperado: n=238 (var) / 239 (idx / Weight) por (series_name, data_type)

-- Confirma Weight duplicado com mesmos valores:
SELECT TOP 5 s.series_name, d.date, d.value
FROM OPT_Macro_Series_Data_2 d
JOIN OPT_Macro_Series_2 s ON s.series_id = d.series_id
WHERE s.bls_code LIKE 'IPCA:livres%' AND s.data_type = 'Weight'
ORDER BY d.date, s.series_name;
-- esperado: pra cada data, "IPCA: Livres" e "IPCA: Livres (Indice)" com o
-- MESMO value.

SELECT TOP 5 * FROM OPT_Macro_Series_Data_2 WHERE series_id = <id_da_livres_var>
ORDER BY date;
-- esperado: 2006-07-31 valor=0.130644, 2006-08-31 valor=0.085540, etc.
-- (valores de referência em sim_output/OPT_Macro_Series_Data_2.csv)
```

**Se algo estiver errado aqui, ANTES de continuar:**
```sql
-- rollback do smoke test (apaga só as 8 séries inseridas):
DELETE FROM OPT_Macro_Series_Data_2
WHERE series_id IN (SELECT series_id FROM OPT_Macro_Series_2
                    WHERE bls_code LIKE 'IPCA:livres%'
                       OR bls_code LIKE 'IPCA:nucleo_ex0%');
DELETE FROM OPT_Macro_Series_2
WHERE bls_code LIKE 'IPCA:livres%' OR bls_code LIKE 'IPCA:nucleo_ex0%';
```

---

## Estágio 4 — carga completa NSA (28 categorias)

**Objetivo:** gravar até **100 séries** (28 var + 28 idx + até 22 pesos × 2)
com `data_type='NSA'`/`'Weight'`. Re-roda séries já cadastradas no Estágio 3 —
`replace=True` apaga dados antigos antes do reinsert, sem duplicar. Antes do
main loop, `_migrate_pareto_to_current` reescreve qualquer linha em formato
não-atual das cats que estão no scope (ancestral `haver_code LIKE
'PARETO_IPCA:%'` OU intermediário `bls_code LIKE 'IPCA:%/Index'`):
`haver_code` → `NULL`, `bls_code` colapsado pra `IPCA:{cat}` (sem
`/Index`), `data_type` migra `Peso→Weight`. Idempotente: rows já no formato
final são puladas sem gerar UPDATE.

```bash
python script_itau/load_pareto_to_sql.py
```

Confirma `Confirma gravacao de ate N series no SQL? [s/N]` (N ≤ 100) → `s`.

**Verificação:**
```sql
SELECT data_type, COUNT(*) AS n_series
FROM OPT_Macro_Series_2 WHERE bls_code LIKE 'IPCA:%'
GROUP BY data_type;
-- esperado: NSA=56 (28 var + 28 idx), Weight=até 44 (até 22 pesos × 2 — label + Indice).
-- núcleos estatísticos MA/MS/DP/P55/medio/difusao não têm peso.

-- Distingue Weight-label (par com var) vs Weight-Indice (par com idx).
-- Sync 2026-07-27: bls_code eh unico por cat; discriminacao sai do series_name
-- (sufixo "(Indice)" no lado idx).
SELECT
  CASE WHEN series_name LIKE '%(Indice)' THEN 'Weight (Indice)' ELSE 'Weight (label)' END AS weight_role,
  COUNT(*) AS n
FROM OPT_Macro_Series_2
WHERE bls_code LIKE 'IPCA:%' AND data_type = 'Weight'
GROUP BY CASE WHEN series_name LIKE '%(Indice)' THEN 'Weight (Indice)' ELSE 'Weight (label)' END;
-- esperado: Weight (label)=22, Weight (Indice)=22.

-- total (headline) Weight = 100 constante nas 238+ datas:
SELECT MIN(value) AS wmin, MAX(value) AS wmax, COUNT(*) AS n
FROM OPT_Macro_Series_Data_2 d
JOIN OPT_Macro_Series_2 s ON s.series_id = d.series_id
WHERE s.bls_code LIKE 'IPCA:total%' AND s.data_type = 'Weight';
-- esperado: wmin=100.0, wmax=100.0 (peso do headline eh 100 por definicao).

SELECT s.data_type, COUNT(*) AS n_obs
FROM OPT_Macro_Series_Data_2 d
JOIN OPT_Macro_Series_2 s ON s.series_id = d.series_id
WHERE s.bls_code LIKE 'IPCA:%'
GROUP BY s.data_type;
-- NSA:    56 séries × N obs (N = meses desde jul/2006 — cresce a cada IPCA)
-- Weight: até 44 séries × N obs (22 pares label + Indice)
-- nucleo_medio começa jan/2007 (warm-up DP 6m); as outras a partir jul/2006.

-- Nenhuma linha em formato pre-colapso deve sobrar apos a migracao:
SELECT
  SUM(CASE WHEN haver_code LIKE 'PARETO_IPCA:%'    THEN 1 ELSE 0 END) AS n_ancestral,
  SUM(CASE WHEN bls_code   LIKE 'IPCA:%/Index%'    THEN 1 ELSE 0 END) AS n_intermediario
FROM OPT_Macro_Series_2;
-- esperado: n_ancestral=0, n_intermediario=0
```

---

## Estágio 5 (opcional) — versão dessazonalizada (X-13)

**Objetivo:** gerar e gravar `data_type='SA'` pras 56 séries (28 var + 28 idx),
totalizando 112 séries NSA+SA (+ até 44 Weight×2 = 156 no máximo).
Só faz sentido se `x13as` está instalado no ambiente.

```bash
python script_itau/load_pareto_to_sql.py --sa
```

Pergunta confirmação pra até 156 séries (56 NSA + 56 SA + até 44 Weight×2).
Cada série pode levar alguns segundos no X-13 (pode demorar 5-10min total).

Se uma categoria falhar no X-13, o loader imprime `[WARN]` e segue —
não bloqueia as outras. Verifique no fim:
```sql
SELECT data_type, COUNT(*) FROM OPT_Macro_Series_2
WHERE bls_code LIKE 'IPCA:%'
GROUP BY data_type;
-- esperado: NSA=56, SA<=56 (quantas dessazonalizaram OK), Weight=até 44
```

### Estágio 5.1 — workarounds SA conhecidos

Três séries falham no wrapper corp `x13_custom` e exigem mini-scripts:

**(a) `IPCA: Servicos (Indice)` SA** — X-13 falha com TD peak warning.
Workaround: reconstrói idx_SA via identidade `idx[t]=idx[t-1]·(1+var[t]/100)`
a partir do var_SA (que passou OK).
```bash
python script_itau/_fix_servicos_idx_sa.py
```

**(b) `IPCA: Nucleo DP` SA + `IPCA: Nucleo Medio` SA** — wrapper corp morre
com `'NoneType' object has no attribute 'startswith'` (bug do
`x13_custom`, não do X-13 em si — provado: R `seasonal` dessazonaliza
as duas sem problema). Workaround em 2 passos:
```bash
# Passo 1: gera SA via R seasonal (path alternativo ao wrapper corp).
Rscript scripts/_sa_dp_nucleo_medio.R
# Produz data/ipca_pareto_sa_dp_medio.csv (476 linhas, 238 obs cada).
# Pré-req: pacote R `seasonal` instalado (install.packages("seasonal")).

# Passo 2: grava o CSV no SQL.
python script_itau/_fix_dp_medio_sa.py
```

**Atenção — bug do upsert por chave natural:** se já existem metas legadas
Haver com `series_name` igual e `data_type='SA'` (ex.: "IPCA: Servicos
(Indice)" SA importado do Haver antes), o `sidra_to_sql` faz upsert
**na meta legada** em vez de criar nova com o `bls_code='IPCA:{cat}'` do
pareto. Sintoma pós sync 2026-07-27: script imprime `[OK] gravado` mas a
query `WHERE bls_code = 'IPCA:{cat}' AND data_type = 'SA'` não retorna a
row esperada (ela grudou na meta legada Haver que tem `bls_code=NULL`).
Mitigação: deletar a meta legada antes de rodar o workaround.

---

## Estágio 6 (opcional) — validação SA contra Haver

**Objetivo:** comparar nossa SA contra séries SA do Haver já carregadas no SQL
corp pra defender a metodologia. Sai uma tabela com `mean|d|`, `max|d|`,
`bias`, `corr` por categoria.

**Importante — normalização:** nossa SA está em **variação mensal %**.
Haver pode estar em **índice nível** (escala 100+) ou em **variação**.
O script sempre normaliza pra MoM antes de comparar — basta marcar
`"idx"` ou `"var"` no MAPPING.

### Configuração

Edite `MAPPING` no topo de `script_itau/_validate_sa_vs_haver.py`:
```python
MAPPING = {
    "nossa_cat": (haver_series_id, "idx" ou "var"),
    ...
}
```
- `"idx"` → série Haver está em nível (ex: 245.67); deriva MoM%
- `"var"` → série Haver já está em variação mensal (%); compara direto

### Execução

```bash
python script_itau/_validate_sa_vs_haver.py --window 24
# ou --window 60 pra janela maior
```

Output:
- Por categoria: amostra dos últimos 3 valores Haver (pra confirmar idx vs var), overlap, métricas, últimos 12 diffs
- Tabela markdown final pra colar em relatório

**Interpretação:**
- `mean|d| < 0.05pp` → SA convergente (defendível)
- `mean|d| 0.05–0.10pp` → diferenças metodológicas (specs X-13 diferentes); ainda OK
- `mean|d| > 0.10pp` → investigar: mesma definição de categoria? mesma base?

**Buscar no Haver os SA equivalentes destas categorias** (nomes prováveis):
- `IPCA: Monitored Prices SA` → `administrados`
- `IPCA: Free Prices SA` → `livres`
- `IPCA: Services SA` → `servicos`
- `IPCA: Industrial Goods SA` → `industriais`
- `IPCA: Food at Home SA` → `alim_domicilio`
- `IPCA: Core - Mean SA` → `nucleo_medio`
- `IPCA: Core - Trimmed Mean SA` → `nucleo_ma`
- `IPCA: Core - Smoothed Trimmed Mean SA` → `nucleo_ms`
- `IPCA: Core - Double Weight SA` → `nucleo_dp`
- `IPCA: Core - P55 SA` → `nucleo_p55`

---

## Rollback completo (se precisar desfazer tudo)

```sql
-- Rollback pos-migracao (formato atual, sync 2026-07-27):
-- bls_code LIKE 'IPCA:%' captura tanto o formato ATUAL (IPCA:{cat}) quanto o
-- INTERMEDIARIO (IPCA:{cat}/Index) — se por algum motivo a migracao nao rodou.
DELETE FROM OPT_Macro_Series_Data_2
WHERE series_id IN (SELECT series_id FROM OPT_Macro_Series_2
                    WHERE bls_code LIKE 'IPCA:%');
DELETE FROM OPT_Macro_Series_2 WHERE bls_code LIKE 'IPCA:%';

-- Rollback do formato ANCESTRAL (haver_code, pre-sync 2026-07-17):
DELETE FROM OPT_Macro_Series_Data_2
WHERE series_id IN (SELECT series_id FROM OPT_Macro_Series_2
                    WHERE haver_code LIKE 'PARETO_IPCA:%');
DELETE FROM OPT_Macro_Series_2 WHERE haver_code LIKE 'PARETO_IPCA:%';
```

Isso só remove o que este loader inseriu (filtra por `bls_code LIKE 'IPCA:%'`
nos formatos novo/intermediário ou `haver_code LIKE 'PARETO_IPCA:%'` no
ancestral) — não afeta as séries SIDRA inseridas pelo `sidra_itau.ipynb`.

---

## Re-execução periódica (após IBGE soltar novo mês)

Pipeline incremental — só recomputa janela recente (não refaz histórico):
```bash
cd pareto_ipca
Rscript scripts/reconstruct_ipca.R                    # default últimos 24 meses (T7060)
Rscript scripts/build_pareto_indice.R
python script_itau/load_pareto_to_sql.py --no-confirm # sem prompt
```

`reconstruct_ipca.R` sem args usa T7060 (POF 2017-18) e janela dos últimos
24 meses. Para reconstruir toda a história (raro): use `seed_ibge_history.R`.

**Release day (BCB fora do ar ou lento):** adicione `--no-bcb` no script R
pra pular a validação vs SGS (não afeta a recon em si — só desliga a
comparação de auditoria e evita ruído/timeout se a API BCB estiver com
problema no dia do release IBGE):
```bash
Rscript scripts/reconstruct_ipca.R --no-bcb
```

`--no-confirm` pula o prompt interativo. O loader imprime log de cada série
gravada no stdout — redirecione pra arquivo se quiser auditoria:
```bash
python script_itau/load_pareto_to_sql.py --no-confirm > load_$(date +%Y%m%d).log 2>&1
```

---

## Comparação contra simulação local

Os valores esperados estão em `script_itau/sim_output/OPT_Macro_Series_Data_2.csv`
(gerado por `simulate_pareto_to_sql.py --save`). Se uma linha qualquer no
SQL não bater com a equivalente no CSV simulado, há discrepância no
write — investigar `sidra_to_sql`.

```sql
SELECT TOP 10 series_id, date, value FROM OPT_Macro_Series_Data_2
WHERE series_id IN (SELECT series_id FROM OPT_Macro_Series_2
                    WHERE bls_code LIKE 'IPCA:livres%')
ORDER BY series_id, date;
```
Compare com:
```bash
head -15 script_itau/sim_output/OPT_Macro_Series_Data_2.csv | grep -E "^2006|series_id"
```
