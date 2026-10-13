# RUNBOOK — atualização rápida CPI-U (22 cats dashboard)

Copy-paste sequencial pra release day BLS. Pipeline R + `load_cpius_to_sql.py --only`, mesmo padrão do IPCA.

Escopo: **22 categorias específicas do dashboard** (headline + core aggs + shelter + transportes + customs analíticos como `core_ex_oer`, `supercore_powell_old`).

Tempo esperado end-to-end: **~2-3 min**.

## 0. Pré-requisitos

- Estar no corp (VPN/rede interna) — `opt_utils` disponível
- Working dir = raiz do pareto_cpius
- Env `BLS_API_KEY` setado (registro em https://data.bls.gov/registrationEngine/)

```powershell
cd pareto_cpius
$env:BLS_API_KEY   # confirma que existe. Se vazio: $env:BLS_API_KEY = "<sua_key>"
```

## 1. Fetch BLS idx (Table 1, 49 base cats × NSA+SA)

```powershell
Rscript scripts/fetch_bls_cpiu.R
```
Esperado: `~60-90s`. Baixa idx via BLS API v2, gera `data/cpi_cpius_recon.csv` + `data/cpi_cpius_indice.csv`. Sanity check no log: `[fetch] concluido: 82/82 series c/ dados (0 vazias)`. Se der `REQUEST_NOT_PROCESSED`, esperar 5-10min (rate limit) e retentar.

## 2. Fetch pesos (RI Table 6 + ajuste implícito mensal)

```powershell
Rscript scripts/fetch_bls_pesos.R
```
Esperado: `~5-10s`. Gera `data/cpi_cpius_pesos.csv` a partir dos históricos anuais RI (2000-2025) + ajuste implícito BLS pra frequência mensal. Verificar `[WARN] RI_BASE_DATE` — se aparecer, o histórico anual precisa update (BLS soltou nova Table 6 anual).

## 3. Build custom aggregations (Laspeyres Dez-anchor)

```powershell
Rscript scripts/build_custom_aggregations.R
```
Esperado: `~5s`. Gera `data/cpi_cpius_custom.csv` + `data/cpi_cpius_pesos_custom.csv` com 8 agregações analíticas (core_ex_oer, supercore_powell_old, etc.). Recipes em `scripts/bls_maps/custom_aggregations.csv`.

## 4. Dry-run da carga (checa o que vai escrever)

```powershell
python script_itau/load_cpius_to_sql.py --only all_items,core,airline_fares,core_ex_oer,core_services_ex_shelter,core_services_ex_volatiles,cpi_ex_oer,energy,food,lodging_away,medical_services,new_vehicles,oer,rent,shelter,super_super_core,supercore_powell_old,transportation_services,used_cars_trucks,car_truck_rental,core_goods,core_services --dry-run
```
Deve listar as **22 categorias** (18 base + 4 custom) com `idx NSA + idx SA + Weight` cada.

## 5. Carga real (66 séries = 22 × 3 datatypes)

```powershell
python script_itau/load_cpius_to_sql.py --only all_items,core,airline_fares,core_ex_oer,core_services_ex_shelter,core_services_ex_volatiles,cpi_ex_oer,energy,food,lodging_away,medical_services,new_vehicles,oer,rent,shelter,super_super_core,supercore_powell_old,transportation_services,used_cars_trucks,car_truck_rental,core_goods,core_services
```
Confirmar na prompt (ou `--no-confirm`). Esperado: `~30-60s`.

## 6. Sanity check SQL

```sql
-- 6a. Última data chegou nas 22 cats?
SELECT s.data_type, MAX(d.date) AS last_date, COUNT(DISTINCT d.series_id) AS n_series
FROM OPT_Macro_Series_Data_2 d
JOIN OPT_Macro_Series_2 s ON s.series_id = d.series_id
WHERE s.bls_code IN (
  'CPIUS:all_items','CPIUS:core','CPIUS:airline_fares','CPIUS:core_ex_oer',
  'CPIUS:core_services_ex_shelter','CPIUS:core_services_ex_volatiles',
  'CPIUS:cpi_ex_oer','CPIUS:energy','CPIUS:food','CPIUS:lodging_away',
  'CPIUS:medical_services','CPIUS:new_vehicles','CPIUS:oer','CPIUS:rent',
  'CPIUS:shelter','CPIUS:super_super_core','CPIUS:supercore_powell_old',
  'CPIUS:transportation_services','CPIUS:used_cars_trucks','CPIUS:car_truck_rental',
  'CPIUS:core_goods','CPIUS:core_services'
)
GROUP BY s.data_type;
-- esperado: NSA=22, SA=22, Weight=22; last_date = mês do release

-- 6b. Spot-check all_items NSA vs release BLS
SELECT TOP 3 d.date, d.value
FROM OPT_Macro_Series_Data_2 d
JOIN OPT_Macro_Series_2 s ON s.series_id = d.series_id
WHERE s.bls_code = 'CPIUS:all_items' AND s.data_type = 'NSA'
ORDER BY d.date DESC;
-- valor do mês novo tem que bater CUUR0000SA0 do release BLS Table 1
```

## 7. Alt measures (Atlanta Sticky family + Cleveland Median/Trimmed + custom)

**Pré-req**: proxy corp — scripts já leem `HTTP_PROXY`/`HTTPS_PROXY` do ambiente (corp seta por default). Só se quiser forçar outro, usa `CORP_PROXY_URL` como override.

```powershell
python scripts/build_alt_measures_cpi.py        # ~60-120s — 9 cats (6 Atlanta + 2 Cleveland + 1 custom Trim25)
python script_itau/load_alt_measures_cpi_to_sql.py --no-confirm
```
Grava `CPIUS:alt_*` no SQL corp. Match 100% com Atlanta/Cleveland (fontes oficiais).

## 8. Difusão CPI-U

```powershell
python scripts/build_diffusion_cpius.py         # ~30-60s
python script_itau/load_diffusion_to_sql.py     # 5 séries
```
Grava `CPIUS:diffusion_*`. Já tem filtro <70% items válidos (commit `8de6b4e`).

## 9. Inflation breadth (3-bin ponderado por peso subitem)

```powershell
python scripts/build_breadth_cpi.py             # ~30s (cache ja aquecido pelo step 7)
python script_itau/load_breadth_cpi_to_sql.py --no-confirm
```
Grava `CPIUS:breadth_above_3pct` / `CPIUS:breadth_0_to_3pct` / `CPIUS:breadth_below_0pct`. Soma dos 3 bins = 100 em cada mês. Cross-section ponderada em 177 subitens leaves (RI subitem Dez do ano anterior).

Dashboard JS calcula contribuições / variantes em cima dessas 3 séries.

---

## Rollback / troubleshooting

- **`REQUEST_NOT_PROCESSED` no step 1**: rate limit BLS. Esperar 5-10min e retentar. Se persistir, checar `BLS_API_KEY` correta.
- **`[WARN] sem dados: CUUR0000XXX` numa cat**: BLS reestruturou item code. Ver `RUNBOOK.md` seção "Cat solta" — precisa atualizar `scripts/bls_maps/cpiu_table_1.csv`.
- **`[WARN] RI_BASE_DATE esta N meses atras`** no step 2: bump anual da base RI. Adicionar novo `.xlsx` em `data/raw/relative_importance/` + reparse (`scripts/parse_historical_ri.py`). Uma vez por ano.
- **SQL row conflict**: `_migrate_cpius_to_current` roda antes do main loop e normaliza rows antigas (haver_code populado, sufixo /Index no bls_code, data_type='Peso') — idempotente (guard anti-UQ desde commit f9cccf6).
- **Corp vs local divergem** (deferred 2026-08-21): dívida conhecida, +0.15 a +0.33pp em algumas cats pós-fix SASL5. Ver memória `project_pareto_cpius_corp_vs_local_diverge.md`. Não bloqueia release.

## Categorias NÃO cobertas neste run

Este runbook cobre **22 cats do dashboard**. Ficam de fora as **27 restantes** (49 total base + custom):
- Food breakdown: `food_home`, `food_away`, `food_cereals_bakery`, `food_meats`, `food_dairy`, `food_fruits_veg`, `food_nonalc_bev`, `food_other_home`
- Energy breakdown: `energy_commodities`, `energy_services`, `fuel_oil`, `motor_fuel`, `gasoline`, `electricity`, `utility_gas`
- Apparel, medical_care (aggregate), medical_goods, alcoholic bev, tobacco, physicians_services, hospital_services, motor_vehicle_maint, motor_vehicle_insur, public_transportation
- Custom: `rent_of_shelter`, `core_services_ex_shelter_pubtrans_medical`

Pra full load, remover `--only` nos steps 4 e 5 (grava 49 × 3 = 147 séries).
