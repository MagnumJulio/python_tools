# RUNBOOK — operação mensal do pareto_cpius no SQL Itaú

BLS solta CPI-U mensalmente ~10-15 do mês seguinte (calendar em https://www.bls.gov/schedule/news_release/cpi.htm). Cheatsheet do release day em `RUNBOOK_RELEASE_DAY.md`.

**Escopo servido no SQL corp**: 49 categorias (41 base + 8 custom) × 3 séries (NSA idx, SA idx, Weight) = **147 séries** (~46 500 rows EAV). Proveniência em `bls_code = 'CPIUS:{cat}'`.

---

## Pré-requisitos

- `opt_utils.database.SQLConnector` disponível (mesmo ambiente do `sidra_itau.ipynb`)
- ODBC driver SQL Server configurado
- Permissão INSERT/DELETE em `OPT_Macro_Series_2` e `OPT_Macro_Series_Data_2`
- `BLS_API_KEY` no env (32 chars) — sem chave, rate limit derruba na 2ª re-run
- Diretório de trabalho: `pareto_cpius/`

---

## Opção A — rodagem rápida mensal (`update_cpius_lean.py`) — PADRÃO

**Passo 1 — smoke test em simulate (sem tocar SQL):**

```bash
cd pareto_cpius
python quick_update/update_cpius_lean.py --cats all --simulate
```

Confirmar no log:
- `API key ON`
- `cats pedidas: 41 base + 8 custom = 49`
- `[fetch] concluido: 82/82 series c/ dados (0 vazias)`
- `RI_BASE_DATE = YYYY-MM  |  ultimo mes idx BLS = YYYY-MM` (mês do release novo)
- **NENHUM** `[WARN] RI_BASE_DATE esta N meses atras` (se aparecer, ver "Bump anual" abaixo)
- `[simulate] OPT_Macro_Series_2 = 147 rows` e `OPT_Macro_Series_Data_2 = ~46 500 rows`

**Passo 2 — run real (grava no SQL corp):**

```bash
python quick_update/update_cpius_lean.py --cats all > quick_update/logs/lean_$(date +%Y%m%d).log 2>&1
```

Comportamento:
- Reescreve os últimos 24 meses (`INCREMENTAL_MONTHS`) por série. Cobre release + revisão SA anual + recalculo de Weight.
- Se série é nova no SQL, faz seed full (jan/2000 → hoje).
- Idempotente: pode rodar 2× seguido sem duplicar.

**Passo 3 — verificação SQL:**

```sql
-- Última data em Data_2 (deve ser o release novo)
SELECT s.data_type, MAX(d.date) AS last_date, COUNT(DISTINCT d.series_id) AS n_series
FROM OPT_Macro_Series_Data_2 d
JOIN OPT_Macro_Series_2 s ON s.series_id = d.series_id
WHERE s.bls_code LIKE 'CPIUS:%'
GROUP BY s.data_type;
-- esperado: NSA=49, SA=49, Weight=49; last_date = último dia do mês do release

-- Confirma o incremental fechou os 24m
SELECT COUNT(*) FROM OPT_Macro_Series_Data_2 d
JOIN OPT_Macro_Series_2 s ON s.series_id = d.series_id
WHERE s.bls_code LIKE 'CPIUS:%'
  AND d.date >= DATEADD(month, -24, EOMONTH(GETDATE()));
-- esperado: ~3500 (49 séries × 3 datatypes × 24 meses)
```

---

## Opção B — full re-load histórico (`load_cpius_to_sql.py`) — FALLBACK

**Quando usar:**
- Opção A caiu em algumas cats e você quer reconstruir do zero (jan/2000 → hoje)
- Auditoria histórica ou discrepância de vintage — quer forçar re-fetch ignorando o INCREMENTAL_MONTHS=24
- BLS mudou item code de uma cat e o lean deixou ela vazia
- Revisão SA anual (janeiro) — quer reescrever todo o histórico com os novos fatores sazonais

**Custo:** ~35s pipeline R + carga SQL (`--only`). Loader usa `replace=True` — apaga rows das cats escolhidas e reinserde full (~317 rows por série).

**Passo 1 — regenera CSVs (pipeline R full):**

```bash
cd pareto_cpius
Rscript scripts/fetch_bls_cpiu.R              # idx NSA+SA 41 base cats (~30s)
Rscript scripts/fetch_bls_pesos.R             # Weight time-varying (~1s)
Rscript scripts/build_custom_aggregations.R   # 8 customs Laspeyres (~2s)
```

Só rodar `python scripts/parse_historical_ri.py` se BLS publicou Table 6 nova (~Fev do ano seguinte).

**Passo 2 — carga SQL com `--only`:**

Full (49 cats):
```bash
python script_itau/load_cpius_to_sql.py --only all
```

Ou subset arbitrário (CSV, sem espaços):
```bash
python script_itau/load_cpius_to_sql.py --only motor_fuel,gasoline,fuel_oil
```

Aceita mistura base + custom. Se uma custom entra no `--only`, as bases dela vão pro fetch mas só vão pro SQL se estiverem explicitamente listadas.

Confirma `Confirma gravacao de ate N series no SQL? [s/N]` → `s`. Pra automação: `--no-confirm`.

**Passo 3 — verificação:**
```sql
SELECT s.series_name, s.data_type, MIN(d.date) AS min_d, MAX(d.date) AS max_d, COUNT(*) AS n
FROM OPT_Macro_Series_Data_2 d
JOIN OPT_Macro_Series_2 s ON s.series_id = d.series_id
WHERE s.bls_code LIKE 'CPIUS:%'
GROUP BY s.series_name, s.data_type
ORDER BY s.series_name, s.data_type;
-- min_d = 2000-01-31, max_d = último dia do mês do release, n ≈ 317
```

---

## Priority subset load (22 cats dashboard)

Alternativa à Opção B full quando só o dashboard interessa. 22 cats × 3 = **66 séries** (~⅓ do full).

Pré-req: mesmo Passo 1 da Opção B (pipeline R full).

```bash
python script_itau/load_cpius_to_sql.py --only all_items,food,energy,core,core_goods,new_vehicles,used_cars_trucks,core_services,shelter,oer,rent,lodging_away,medical_care,transportation_services,airline_fares,car_truck_rental,core_ex_oer,cpi_ex_oer,core_services_ex_shelter,supercore_powell_old,super_super_core,core_services_ex_volatiles
```

Cats na ordem: CPI geral, Food, Energy, Core CPI, Core goods, New vehicles, Used cars/trucks, Core services (SASLE), Shelter, OER, RPR (`rent`), Lodging away, Health care (`medical_care`/SAM), Transportation services, Airline fares, Car & truck rental, Core ex OER, CPI ex OER, Core services ex rent of shelter, Core services ex RPR & OER (`supercore_powell_old`), Super super core, Core services ex volatiles.

---

## Bump anual da RI base

Quando `[WARN] RI_BASE_DATE esta N meses atras` disparar (BLS publicou Table 6 nova):

1. Baixar `YYYY.xlsx` de https://www.bls.gov/cpi/tables/relative-importance/ e salvar em `data/raw/relative_importance/YYYY.xlsx`.
2. `python scripts/parse_historical_ri.py` → regera `cpi_cpius_pesos_annual.csv` com a linha nova.
3. Copiar o dict do CSV pro `RI_HISTORICAL[YYYY] = {...}` em `quick_update/update_cpius_lean.py`.
4. Atualizar `RI_BASE_DATE = "YYYY-12"` no mesmo arquivo.
5. Smoke test: `python quick_update/update_cpius_lean.py --cats all --simulate` — não deve mais disparar o WARN.

Rodar com RI atrasada > 12m vira erro estatístico material (peso implícito diverge da revisão BLS).

---

## Cat solta (BLS reestruturou item code)

Sintoma: rodagem rápida marca cat como `[WARN] sem dados: CUUR0000XXX` e série no SQL fica congelada no último release bom.

Diagnóstico:
1. Baixar https://download.bls.gov/pub/time.series/cu/cu.item e procurar item_code antigo — se sumiu, buscar pelo label esperado.
2. Achar novo `item_code` e atualizar em **dois lugares**:
   - `scripts/bls_maps/cpiu_table_1.csv` (pipeline R)
   - `ITEM_CODES` em `quick_update/update_cpius_lean.py` (rodagem rápida)
3. Re-rodar smoke `--simulate`. Se voltou (0 warns), rodar real.

Se labels mudaram sem quebrar item_code, só `CATEGORY_LABELS` / `CATEGORY_BLS_DEFS` precisam ajustar.

---

## Comparação contra simulação local

Valores esperados em `script_itau/sim_output/OPT_Macro_Series_Data_2.csv` (gerado por `simulate_cpius_to_sql.py --save`).

```sql
SELECT TOP 10 s.series_name, s.data_type, d.date, d.value
FROM OPT_Macro_Series_Data_2 d
JOIN OPT_Macro_Series_2 s ON s.series_id = d.series_id
WHERE s.bls_code LIKE 'CPIUS:all_items%'
ORDER BY s.data_type, d.date;
```
Compara com `head -20 script_itau/sim_output/OPT_Macro_Series_Data_2.csv`.

Diferença esperada: no SQL as datas são **último dia do mês** (convenção Haver corp), no CSV do simulate ficam no dia 01. Valores devem bater.

---

## Rollback (se precisar desfazer tudo)

```sql
DELETE FROM OPT_Macro_Series_Data_2
WHERE series_id IN (SELECT series_id FROM OPT_Macro_Series_2
                    WHERE bls_code LIKE 'CPIUS:%');

DELETE FROM OPT_Macro_Series_2 WHERE bls_code LIKE 'CPIUS:%';
```

Filtra pelo prefixo `CPIUS:` no `bls_code` — não afeta séries SIDRA/IPCA nem Haver.
