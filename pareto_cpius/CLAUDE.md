# pareto_cpius — pipeline R BLS-only para CPI-U (US) e agregações principais

Fetcha, em R, o **CPI-U headline + 38 agregações hierárquicas** publicadas na Table 1 do release mensal do BLS (Bureau of Labor Statistics, US), em SA (Seasonally Adjusted) e NSA (Not Seasonally Adjusted), **100% a partir da BLS Public Data API v2**. Também deriva **8 agregações custom** via álgebra Laspeyres com os pesos mensais (core ex OER, super super core, supercore Powell, etc.), totalizando **47 categorias**. FRED (St. Louis Fed) reservado apenas pra auditoria — a série FRED de CPI-U é uma cópia licenciada do BLS, então serve pra confirmar que nossa recon bate.

**Fonte primária**: BLS API v2 (`api.bls.gov/publicAPI/v2/timeseries/data/`) — endpoint POST JSON que aceita até 50 séries por request com `registrationkey` (chave gratuita) ou 25 séries sem chave. Item codes seguem a taxonomia do BLS CPI (`SA0`, `SA0L1E`, `SAF1`, etc.), montados em series IDs `CUUR0000<item>` (NSA) e `CUSR0000<item>` (SA).

**Princípio cardinal** (herdado do irmão `pareto_ipca`): tudo que é servido vem do BLS. FRED só existe pra conferir o que foi montado a partir do BLS.

## Estrutura

```
pareto_cpius/
├── data/                        # gerada em runtime (não commitada)
│   ├── cpi_cpius_recon.csv      # long: date, category_code, sa_flag, series_id,
│   │                            #        value_index, value_var_mm, value_var_yoy
│   └── cpi_cpius_indice.csv     # long: date, category_code, sa_flag, index (jan/2000=100)
├── scripts/
│   ├── fetch_bls_cpiu.R         # ⭐ MVP: fetcha Table 1 via BLS API v2
│   ├── bls_maps/
│   │   └── cpiu_table_1.csv     # mapa (category_code, label, item_code, indent_level, description)
│   ├── outputs/                 # audit/diagnóstico (gerada em runtime)
│   └── proxy_config.R           # opcional: proxy corporativo (no-op em casa)
└── (script_itau/)               # futuro: loader SQL corp Itaú, análogo ao pareto_ipca/script_itau
```

## Pipeline (ordem)

```bash
cd pareto_cpius
Rscript scripts/fetch_bls_cpiu.R              # baixa 39 categorias base × SA+NSA, jan/2000 → atual
python scripts/parse_historical_ri.py         # parseia RI Dez/2000-2025 (txt + xlsx) → pesos_annual.csv
Rscript scripts/fetch_bls_pesos.R             # aplica ajuste implicito BLS → peso mensal por cat
Rscript scripts/build_custom_aggregations.R   # deriva 8 agregacoes custom (algebra Laspeyres)
```

Saídas em `data/`: `cpi_cpius_recon.csv` (índice + var mensal + var yoy, 39 base cats), `cpi_cpius_indice.csv` (rebased jan/2000=100), `cpi_cpius_pesos_annual.csv` (RI base Dez, 26 anos × 39 cats), `cpi_cpius_pesos.csv` (peso mensal ajustado por preço), `cpi_cpius_custom.csv` (8 agregações custom, mesmo schema do recon), `cpi_cpius_pesos_custom.csv` (pesos derivados das custom).

**Chave BLS (recomendada)**: register em https://data.bls.gov/registrationEngine/ e exporte:
```bash
export BLS_API_KEY=<sua_chave>   # 50 séries/batch, 500 requests/dia
```
Sem chave: 25 séries/batch e 25 requests/dia (funciona pro MVP mas trava em atualizações repetidas).

**Janela custom**:
```bash
START_YEAR=1990 Rscript scripts/fetch_bls_cpiu.R
```
O código quebra automaticamente em sub-janelas de 20 anos (limite BLS v2 por request).

## Escopo das 39 categorias base mapeadas (Table 1)

Hierarquia completa da Table 1 (indent = nível). Todas saem tanto em SA quanto em NSA. Item codes canônicos definidos em `scripts/bls_maps/cpiu_table_1.csv` (coluna `indent_level` preserva a hierarquia). Adicionadas em 2026-07-16: `lodging_away` (SEHB) e `public_transportation` (SETG) — necessárias como leaf-level nos exclude recipes das agregações custom.

**All items** (`all_items` — SA0)
- **Food** (`food` — SAF1)
  - Food at home (`food_home` — SAF11)
    - Cereals and bakery products (`food_cereals_bakery` — SAF111)
    - Meats, poultry, fish, and eggs (`food_meats` — SAF112)
    - Dairy and related products (`food_dairy` — SAF113)
    - Fruits and vegetables (`food_fruits_veg` — SAF114)
    - Nonalcoholic beverages (`food_nonalc_bev` — SAF115)
    - Other food at home (`food_other_home` — SAF116)
  - Food away from home (`food_away` — SEFV)
- **Energy** (`energy` — SA0E)
  - Energy commodities (`energy_commodities` — SACE)
    - Fuel oil (`fuel_oil` — SEHE)
    - Motor fuel (`motor_fuel` — SETB) → Gasoline all types (`gasoline` — SETB01)
  - Energy services (`energy_services` — SEHF)
    - Electricity (`electricity` — SEHF01)
    - Utility (piped) gas service (`utility_gas` — SEHF02)
- **Core** — all items less food and energy (`core` — SA0L1E)
  - Commodities less food/energy commodities (`core_goods` — SACL1E)
    - Apparel (`apparel` — SAA)
    - New vehicles (`new_vehicles` — SETA01), Used cars/trucks (`used_cars_trucks` — SETA02)
    - Medical care commodities (`medical_goods` — SAM1)
    - Alcoholic beverages (`alcoholic_bev` — SEAF), Tobacco (`tobacco` — SEGA)
  - Services less energy services (`core_services` — SASL5)
    - Shelter (`shelter` — SAH1) → Rent (`rent` — SEHA), OER (`oer` — SEHC)
    - Medical care services (`medical_services` — SAM2) → Physicians' (`physicians_services` — SEMC01), Hospital (`hospital_services` — SEMD01)
    - Transportation services (`transportation_services` — SAS4) → Motor vehicle maint/repair (`motor_vehicle_maint` — SETD), Motor vehicle insurance (`motor_vehicle_insur` — SETE), Airline fares (`airline_fares` — SETG01)

**Validação (smoke test 2026-07-14, release Jun/2026):** todos os 37 codes retornaram dados; valores NSA batem exato com Table 1 do release (all_items 333.952, motor_vehicle_insur 858.481, physicians' 438.626, hospital 457.320). Se algum código ficar desatualizado (BLS reestrutura ocasionalmente), o BLS API retorna série vazia — dá pra ver no resumo final do `fetch_bls_cpiu.R`.

## Pesos (Relative Importance, Table 6 BLS) — Fase 2 entregue

`fetch_bls_pesos.R` gera `data/cpi_cpius_pesos.csv` no schema `(date, category_code, value)` — mesmo shape do `pareto_ipca/data/ipca_pareto_pesos.csv`. Valores em %, 0-100.

**Metodologia fiel ao BLS ("monthly relative importance")**: base anual = RI publicado em Dezembro de cada ano (Dez 2000, Dez 2001, ..., Dez 2025), extraído dos arquivos históricos em `data/raw/relative_importance/` (txt 2000-2019 + xlsx 2020-2025) via `scripts/parse_historical_ri.py`. Pra cada mês *m* do ano *t*, aplica ajuste implícito de preço:

```
w_i(m) = w_i(Dez_{t-1}) × I_i(m) / I_i(Dez_{t-1})
```

Depois renormaliza a soma food+energy+core=100 pra preservar coerência hierárquica. Isso captura o drift dentro do ano (ex.: gasoline oscilando 2.5% em COVID → 6.7% no pico 2008 → 3.8% em jun/2026), o que peso constante não capturava.

**Fonte histórica**: BLS solta a Table 6 Relative Importance em cada release de Dezembro (`https://www.bls.gov/cpi/tables/relative-importance/YYYY.htm`). Base biennial pré-2023 (1993-95, ..., 2017-18) e anual pós-2023 (2023, 2024). Arquivos brutos manuais em `data/raw/relative_importance/`:
- `ri-archive-2000-2009/*.txt` (fixed-width 2000-2009)
- `ri-archive-2010-2019/*.txt` (fixed-width 2010-2019)
- `2020.xlsx`..`2025.xlsx` (formato tabular a partir do redesenho BLS)

**Validação**: soma food+energy+core=100.000 em todas as 26 anos-base + todas as 317 datas mensais. `all_items` também bate 100.000 dentro do erro de renorm (< 1e-3 pp).

**Cats com drift de label** que exigiram fallback histórico: `oer` (era "primary residence" antes de 2018), `utility_gas` ("Utility natural gas service" pré-2015), `hospital_services` ("...and related services" pré-2010), `airline_fares` ("Airline fare" singular pré-2007), `energy_services` (não existia como agregado nomeado; derivado de electricity+utility_gas em 2000-2005). Ver `CATS`/`DERIVED` em `scripts/parse_historical_ri.py`.

## Agregações custom (Laspeyres) — entregue 2026-07-16

`scripts/build_custom_aggregations.R` lê `data/cpi_cpius_recon.csv` + `data/cpi_cpius_pesos.csv` + recipe file `scripts/bls_maps/custom_aggregations.csv` e deriva agregações que não existem prontas no release BLS, usando o mesmo peso mensal do fetch_bls_pesos.

**Métodos suportados** (coluna `method` da recipe):
- `exclude`: `var_agg(m) = (var_base × w_base − Σ var_i × w_i) / (w_base − Σ w_i)`, onde `i` está na coluna `excludes`. Peso derivado: `w_agg = w_base − Σ w_i`.
- `sum`: `var_agg(m) = Σ var_i × w_i / Σ w_i`, onde `i` está em `includes`. Peso derivado: `w_agg = Σ w_i`.

Índice reconstruído por composição mensal a partir de jan/2000=100 (`I(m) = I(m−1) × (1 + var(m)/100)`), YoY = `I(m)/I(m−12) − 1`.

**8 recipes iniciais** (`scripts/bls_maps/custom_aggregations.csv`):

| code | método | base | excludes/includes | descrição |
|---|---|---|---|---|
| `rent_of_shelter` | sum | — | rent + oer + lodging_away | Conceito Fed de shelter (RPR + OER + lodging) |
| `core_ex_oer` | exclude | core | oer | Core CPI (SA0L1E) menos OER |
| `cpi_ex_oer` | exclude | all_items | oer | All items menos OER |
| `core_services_ex_shelter` | exclude | core_services | rent + oer + lodging_away | Core services menos rent-of-shelter |
| `supercore_powell_old` | exclude | core_services | rent + oer | Powell supercore antigo (só RPR+OER) |
| `core_services_ex_shelter_pubtrans_medical` | exclude | core_services | rent + oer + lodging_away + public_transportation + medical_services | Core services menos housing + PubTrans + medical |
| `super_super_core` | exclude | core_services | rent + oer + lodging_away + airline_fares + medical_services | Core services ex OER+RPR+lodging+airline+medical |
| `core_services_ex_volatiles` | exclude | core_services | airline_fares + medical_services | Core services menos volatilidades |

**Extensibilidade**: adicionar uma linha em `custom_aggregations.csv` + expandir `CUSTOM_LABELS` em `simulate_cpius_to_sql.py` e `load_cpius_to_sql.py`. Nenhum código novo em R necessário.

**Validação (release Jun/2026)**: peso derivado bate exato com a algebra esperada (`w_cpi_ex_oer = 74.1508` = `w_all − w_oer = 99.9997 − 25.8489`). YoY do último ponto NSA: `cpi_ex_oer=3.62%`, `supercore_powell_old=3.33%`, `rent_of_shelter=3.30%`, `super_super_core=1.97%` — trajetórias condizentes com narrativa Fed (super_super_core = medida mais "core").

## Metas próximas (fase 2)

1. **Núcleos alternativos (Cleveland Fed):**
   - **Median CPI** (FRED: `MEDCPIM158SFRBCLE`)
   - **16% Trimmed-Mean CPI** (FRED: `TRMMEANCPIM158SFRBCLE`)
   - Não vêm do BLS — publicados pela Cleveland Fed e re-servidos via FRED. Análogos aos núcleos MA/MS/DP do IPCA.

2. ~~**Pesos históricos anuais**~~ ✅ **entregue 2026-07-16** — RI Dez 2000-2025 parsed dos arquivos brutos + ajuste implícito mensal BLS. Ver seção "Pesos" acima.

3. ~~**Recon Laspeyres via subitens** (Table 7)~~ — parcialmente **superado** por `build_custom_aggregations.R` (2026-07-16). Recortes tipo "core services less shelter" / "supercore" agora derivam via álgebra Laspeyres a partir das 39 agregações prontas do BLS + peso mensal, sem precisar dos ~200 subitens. Recon via Table 7 continuaria útil apenas se precisarmos operar dentro de leaf-level (ex.: excluir apenas gasolina não-premium), mas isso é fora do escopo atual.

4. **C-CPI-U (Chained CPI)** (Table 3):
   - Publicado com defasagem (revisões subsequentes). BLS API expõe via item codes `SUUR0000<item>`. Baixa relevância no dia a dia mas útil pra debates de indexação (Social Security etc.).

5. **Auditoria FRED**: script `_audit_bls_vs_fred.R` comparando nossa recon BLS-native contra as mesmas séries republicadas em FRED (ex.: `CPIAUCSL` = SA0 SA). Deve bater exato (FRED apenas re-serve BLS).

6. **Loader SQL corp Itaú** (`script_itau/load_cpius_to_sql.py`, ✅ entregue): mesmo padrão de `pareto_ipca/script_itau/load_pareto_to_sql.py` mas com diferenças de escopo — sync 2026-07-20: **só `idx` NSA + idx SA + Weight** (var NSA/SA foi removida do SQL pra não lotar de lixo; variação mensal pode ser derivada do índice no consumo). Cada categoria vira até **3 séries**. Convenções: `data_type="Weight"` (não `"Peso"`), Weight gravado **1×** por categoria com `series_name=f"{label} (Index)"` (par com o idx) — sem duplicação porque não há mais var pareado. Headline `all_items` recebe peso sintético 100.0 constante (sobrescreve valor renormalizado ~99.9997 do CSV). Proveniência gravada em **`bls_code`** com formato simplificado **`CPIUS:{cat}`** — sem sufixo `/Index` (a distinção idx vs Weight sai de `series_name`+`data_type`, não do code); INSERTs novos não setam `haver_code` (o SQL preenche como `NULL` por default). `indicator="CPI"` (não `"CPI-U"` — sync 2026-07-20). Base e custom compartilham o mesmo formato — a distinção sai do próprio `category_code` (ex.: `core_ex_oer` vs `core`), não do code. Migração idempotente (`_migrate_cpius_to_current`) rodada antes do main loop: normaliza qualquer row CPIUS antiga (haver_code populado, sufixo /Index em bls_code, indicator=CPI-U, data_type=Peso) pro formato atual. Total: 47 × 3 = **141 séries** (~44 700 linhas EAV). Simulador local em `simulate_cpius_to_sql.py` (mesma lógica com `MockSQLConnector`).

## Convenções dos scripts

- **Auto-cwd**: descobre a raiz do projeto via `--file=` e faz `setwd()`. Funciona de qualquer pasta de invocação.
- **Env vars**: `BLS_API_KEY` (chave BLS opcional), `START_YEAR` (default 2000).
- **Proxy opcional**: `scripts/proxy_config.R` é sourceado se existir. Sem o arquivo (rodando em casa) vira no-op.
- **Comentários em português**, terse, com `# Por que:` explicando decisões não-óbvias.
- **Pacotes**: só `httr` e `jsonlite` (base R pra resto). Sem `tidyverse`.

## Referências externas

- BLS API v2 docs: https://www.bls.gov/developers/api_signature_v2.htm
- Item codes CPI-U (arquivo canônico): https://download.bls.gov/pub/time.series/cu/cu.item
- BLS CPI news release page (Tables 1-8): https://www.bls.gov/cpi/tables/supplemental-files/home.htm
- FRED (audit-only): `CPIAUCSL` = SA0 SA, `CPILFESL` = SA0L1E SA, `CPIENGSL` = SA0E SA
- Cleveland Fed alternative core measures (fase 2): https://www.clevelandfed.org/indicators-and-data/median-cpi

## Notas de vintage

- **Datas**: BLS publica um valor por mês em unidade "monthly index" (base 1982-84=100 nativa do BLS). Nosso rebase jan/2000=100 é só pra comparabilidade visual entre categorias.
- **SA revisions**: BLS revisa fator sazonal em jan de cada ano (recalcula últimos 5 anos). Isso significa que uma pull tirada em fev/2026 pode diferir levemente de uma tirada em dez/2025 para o mesmo mês. Guardar `release_date` no futuro loader SQL vai facilitar vintage tracking.
- **Coverage**: as 37 séries listadas cobrem toda a Table 1 do release BLS (headline + agregações por expenditure category em 4 níveis de profundidade). Somas ponderadas exatas requerem pesos (Table 6/8 relative importance, fase 2) — a coluna `Relative importance` da Table 1 do release já dá a referência (all_items=100000, food=13447, energy=7791, core=78762, etc.). No MVP servem só os níveis das agregações prontas do BLS.
