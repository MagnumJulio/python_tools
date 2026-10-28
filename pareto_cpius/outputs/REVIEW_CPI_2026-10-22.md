# CPI-U — review das métricas (compilado 2026-10-22)

Compilado das métricas CPI geradas pelo projeto `pareto_cpius`, mapeando
processo (fonte → fetch → transform → saída → SQL → dashboard) e
destacando pontos fortes e falhas conhecidas.

## Resumo executivo

- **Universo entregue**: 49 categorias (41 base BLS Table 1 + 8 custom Laspeyres) × idx NSA + idx SA + Weight = **147 séries base**; mais 9 alt measures × 3 metrics = **26 séries alt**; mais 3 breadth, 7 diffusion, 4 OER regional → **~187 séries servidas no SQL corp**.
- **Fonte primária**: BLS Public Data API v2 (ou xlsx Atlanta/CSV Cleveland pras alt). FRED só pra audit das séries BLS e pra pegar Cleveland Median/Trim16 (que não têm BLS equivalent).
- **Status pós iteração 2026-10-22**: alt measures robustas (FRED via `requests`, chartdata complementar, TTL cache 24h, proxy MoM SA integrado ao CSV+SQL). Último release coberto end-to-end: **set/2026**.
- **Gap de validação**: só spot-checks pontuais; nenhum teste automatizado nem sanity-range no pre-flight do loader. Shutdown de outubro-2025 passa como "n/a" em todas as fontes exceto 3 cats; breadth gera 40% artificial no bin `<0%` nesse mês (dado faltante classificado erroneamente).

---

## Famílias de métricas e processo

### 1. CPI base (41 cats, Table 1 BLS)

**Fonte**: BLS API v2, item codes canônicos `CUUR0000<item>` (NSA) e `CUSR0000<item>` (SA) desde jan/2000.

**Fetch**: `scripts/fetch_bls_cpiu.R`
- Batches de 50 series com `BLS_API_KEY` (25 sem key) × janelas de 20 anos (limite v2).
- Mapa (category_code, label, item_code, indent_level) em `scripts/bls_maps/cpiu_table_1.csv`.
- Validado contra `cu.item.tsv` canônico (feedback mem `feedback_verify_bls_item_codes.md`).

**Saída**: `data/cpi_cpius_recon.csv` (long: `date, category_code, sa_flag, series_id, value_index, value_var_mm, value_var_yoy`) + `data/cpi_cpius_indice.csv` (rebased jan/2000=100).

**SQL loader**: `script_itau/load_cpius_to_sql.py` — 3 datatypes por cat: idx NSA + idx SA + Weight. `bls_code="CPIUS:{cat}"`, `indicator="CPI"`.

**Dashboard**: `outputs/dashboard_cpius_last_12m.md` — 22 cats subset (dash gerente). 5 tabelas (pesos NSA + MoM NSA/SA + YoY NSA/SA).

### 2. Pesos (RI Table 6, Dez-anchor + ajuste implícito mensal)

**Fonte**: BLS Table 6 Relative Importance, histórico 2000-2025 em `data/raw/relative_importance/{txt,xlsx}`.

**Fetch**: `scripts/parse_historical_ri.py` (txt 2000-2019 + xlsx 2020-2025) → `cpi_cpius_pesos_annual.csv`. Depois `scripts/fetch_bls_pesos.R` aplica ajuste implícito mensal: `w_i(m) = w_i(Dez_{t-1}) × I_i(m) / I_i(Dez_{t-1})` + renormaliza soma food+energy+core=100.

**Saída**: `data/cpi_cpius_pesos.csv` (long: `date, category_code, value`).

**Validado**: soma food+energy+core=100.000 em 26 anos-base + 317 datas mensais. `all_items` bate 100.000 ± 1e-3pp.

**Falhas tratadas**: cats com drift de label histórico (`oer` era "primary residence" pré-2018, `utility_gas`, `hospital_services`, `airline_fares`, `energy_services` derivado 2000-2005) — fallback explícito em `CATS`/`DERIVED` do parser.

### 3. Custom aggregations (Laspeyres Dez-anchor, 8 recipes)

**Script**: `scripts/build_custom_aggregations.R`.

**Métodos**: `exclude` (base menos subset) e `sum` (soma de includes). Peso derivado via álgebra Laspeyres.

**Recipes** (`scripts/bls_maps/custom_aggregations.csv`):
- `cpi_ex_oer`, `core_ex_oer`, `rent_of_shelter`, `supercore_powell_old`,
  `core_services_ex_shelter`, `core_services_ex_shelter_pubtrans_medical`,
  `super_super_core`, `core_services_ex_volatiles`.

**Validação pontual** (release Jun/2026): `w_cpi_ex_oer = 74.1508` = `w_all − w_oer = 99.9997 − 25.8489` bate exato.

### 4. Alt measures (9 séries de inflação subjacente)

**Script**: `scripts/build_alt_measures_cpi.py` (reescrito 2026-10-22).

**9 séries, 3 fontes**:
- **Atlanta xlsx** (`data/raw/atlanta/stickyprice.xlsx`): 6 séries Sticky/Flex family, 1967→atual, ambos 1-mo ann + YoY.
- **Cleveland chartdata CSV** (`data/raw/cleveland/`): Median + Trim16 YoY (2017+).
- **FRED** (`fredgraph.csv?id=...`): Cleveland Median + Trim16 1-mo annualized (1983+).
- **Custom bottom-up**: Trimmed Sym 25% CPI (70 indent-3 nodes BLS universe, STL dessaz, 2001+, só 1-mo).

**Mudanças críticas 2026-10-22**:
- `fetch_fred_csv` passa de `_curl_get` (subprocess curl) para `requests.get(url, timeout=60)`. Resolve curl rc=28/56 intermitente em casa e proxy Basic-auth corp.
- FRED e Cleveland chartdata agora **complementares**, não fallback: rodam sempre; consolidação via `groupby(['measure','date']).agg({'ann_1mo':'max','ann_12mo':'max'})` NaN-safe.
- Helper `_cache_fresh(path, ttl_hours)` + env `CACHE_TTL_HOURS=24`. Atlanta/Cleveland 24h, subitem BLS 7d. **Resolve o bug** "if not path.exists(): download" que travou alt_measures em agosto quando o server já tinha setembro.
- **Nova coluna `mom_sa`** no CSV: `(1 + ann_1mo/100)^(1/12) - 1`. Mesma unidade dos MoM SA das 22 cats BLS — comparação direta.

**Saída**: `data/cpi_cpius_alt_measures.csv` (schema `date, measure, ann_1mo, mom_sa, ann_12mo`).

**SQL loader**: 9 measures × até 3 metrics (1mo/mom_sa/12mo) = **26 séries** (Trim25 custom não tem YoY). Namespace `CPIUS:alt_{measure}_{metric}`.

**Dashboard**: `outputs/dashboard_cpius_extras_last_12m.md` (6 tabelas: 1-mo, proxy MoM SA, YoY, breadth, diffusion YoY, diffusion 6m-ann).

### 5. Breadth (3-bin ponderado por peso subitem)

**Script**: `scripts/build_breadth_cpi.py`.

**Metodologia**: cross-section de 177 subitens leaves CPI-U, agrupados em 3 bins de YoY (`<0`, `0-3`, `>3`) e ponderados pelo peso RI Dez do ano anterior.

**Saída**: `data/cpi_cpius_breadth.csv` + `script_itau/load_breadth_cpi_to_sql.py` → 3 séries SQL (`CPIUS:breadth_*`).

**Filtro de qualidade**: `<70% items válidos` → row descartada (commit `8de6b4e`, propagação após deriva CPI-U+PCE).

### 6. Diffusion (4 aggregates × 2 metrics, item-level ponderado)

**Script**: `scripts/build_diffusion_cpius.py`.

**Agregados**: Headline (todos itens), Goods, Goods ex cars, Services.
**Métricas**: `diffusion_yoy_3pct` (todos 4) + `diffusion_6ma_ann_3pct` (só Headline — decisão explícita no código).

**Saída**: `data/cpiu_diffusion.csv` + `script_itau/load_diffusion_to_sql.py` → 5 séries SQL (`CPIUS:diffusion_*`).

### 7. OER regional (4 Census regions, submódulo isolado)

**Script**: `scripts/fetch_bls_oer_regional.R` + `script_itau/load_oer_regional_to_sql.py`.

**Fonte**: 4 áreas Census (`0100` NE, `0200` MW, `0300` S, `0400` W) × SEHC NSA, dez/1982→atual.

**Isolamento**: namespace separado `CPIUS_OER:{area}` (não conflita com `CPIUS:oer` do loader principal). US skipado por default (`--include-us` força).

**Decisão explícita**: só NSA (SA regional não existe no BLS); só Index (sem Weight — não faz sentido isolar peso regional de 1 subitem).

---

## Pontos fortes

1. **Fonte primária 100% BLS para séries base** — FRED só como audit (é cópia licenciada do BLS, deve bater).
2. **Pesos time-varying obrigatórios** desde o primeiro corte servido (segue feedback mem `feedback_pesos_time_varying.md`). Não há snapshot constante.
3. **Namespace SQL isolado** por família: `CPIUS:{cat}` (base+custom), `CPIUS_OER:{area}` (regional), `CPIUS:alt_{measure}_{metric}` (alt), `CPIUS:breadth_{bin}` (breadth), `CPIUS:diffusion_{agg}_{metric}` (diff). Evita colisão + facilita filtro.
4. **Fallback multi-fonte** nas alt measures: FRED + Cleveland chartdata + xlsx cache. Pipeline não quebra se uma fonte cai (desde iteração 2026-10-22).
5. **TTL cache invalidante** (24h padrão, 7d pros leaves BLS pesados). Evita regressão silenciosa quando fonte terceira publica mas cache local está stale.
6. **Dashboards reproduzíveis em markdown** (`_make_dashboard_*.py`). Entrega analista-friendly, auditável, não depende de BI tool.
7. **Mapa auditável** de taxonomia BLS (`scripts/bls_maps/cpiu_table_1.csv`, `cu.item.tsv`), evita item codes "mágicos" no código.
8. **Spot-checks documentados**: todos os refactors recentes validados contra Table 1 do release (ex: all_items 333.952, motor_vehicle_insur 858.481, physicians' 438.626, hospital 457.320 em Jun/2026).
9. **Convenções do schema SQL explicitadas no CLAUDE.md** — garante que recarregas num ciclo seguinte não contaminam formatação (migrações idempotentes).
10. **Proxy MoM SA das alt measures** (2026-10-22) em pipeline permite comparação direta das medidas Fed com as 22 cats BLS na mesma unidade.

---

## Falhas conhecidas e riscos (ordenado por severidade)

### RESOLVIDOS (commit `325f17d`, 2026-10-22)

**Cache subitem compartilhado entre breadth e alt_measures** (ALTA).

- `cpi_cpius_subitem_sa_raw.csv` era usado tanto por `build_alt_measures_cpi.py` (70 indent-3 pro Trim25 custom) quanto por `build_breadth_cpi.py` (177 leaves). `FORCE_FETCH` do alt_measures sobrescrevia total o cache, destruindo os 107 extras do breadth. Resultado: breadth no SQL podia ficar com universe reduzido dependendo da ordem do runbook.
- **Fix**: cada script tem seu arquivo isolado — `_subitem_alt_raw.csv` (70) e `_subitem_breadth_raw.csv` (177). Zero interseção de contrato.

**Shutdown de outubro-2025 inflava breadth** (ALTA).

- `compute_breadth` tinha `dropna(yoy)` mas renormalizava pra 100% dos items **presentes**. No release incompleto de Out/2025 (BLS shutdown), 6 items cobriam 11.42% do peso → breadth output virava amostra enviesada (`below_0pct=40.12%` artificial).
- **Fix**: `COVERAGE_THRESHOLD_PCT=70` descarta datas abaixo do limiar, com `[WARN]` explícito. Analogo ao filter de `build_diffusion_cpius.py`.

**Trimmed Sym 25% custom com description "Fed oficial"** (MÉDIA).

- `load_alt_measures_cpi_to_sql.py` tinha description hardcoded `"Fed oficial"` pra todas as 9 alt measures, incluindo `trimmed_sym_25_cpi_custom` (bottom-up Itaú).
- Series name já diferenciava (`"CPI-U: Trimmed Sym 25% (custom)"` vs `"(Cleveland Fed)"` / `"(Atlanta Fed)"`), e `bls_code` tem sufixo `_custom`. Mas gestor olhando pela description via `"Fed oficial"` num custom.
- **Fix**: `description` dinâmica — `measure.endswith("_custom")` → `"custom bottom-up Itau (nao e fonte oficial Fed)"`.

### MÉDIA (ainda abertos)

**Validação histórica insuficiente**.

- Nenhum teste automatizado. Spot-checks pontuais contra Table 1 do release foram feitos manualmente em Jun/2026 (CLAUDE.md documenta valores). Não roda a cada release.
- Pre-flight do loader só valida existência de tabela/coluna, não valores (sanity ranges, deltas vs vintage anterior).
- **Risco**: regressão silenciosa (como SASL5→SASLE, 2 bugs em 9 dias — feedback mem `feedback_verify_bls_item_codes.md`).
- **Ação sugerida**: adicionar validação simples no loader (ex: `|MoM NSA all_items| < 2.0% em release normal; log WARN se exceder`).

### BAIXA

**Dashboards manualmente regerados após cada release**.

- `_make_dashboard_last_12m.py` + `_make_dashboard_extras_last_12m.py` precisam ser rodados a mão pós-fetch. RUNBOOK documenta, mas não é CI.

**Simulate mode só existe para CPI principal e OER regional**.

- `simulate_cpius_to_sql.py` + `simulate_oer_regional_to_sql.py` existem; alt measures / breadth / diffusion loaders só têm `--dry-run` (lista o payload, não executa Mock).
- Útil pra validar schema SQL antes do push real no corp.
- **Ação sugerida**: adicionar simulate loaders quando houver mudança de schema.

**Caches `raw/` versionados** (309KB Atlanta + 1.9KB Cleveland).

- Decisão explícita (seed Fed xlsx/CSVs) pra desbloquear corp sem precisar internet pra `atlantafed.org`. OK, infla repo em ~500KB mas aceitável.

**OER regional sem SA**.

- SA regional não existe no BLS. Documentado em CLAUDE.md como decisão. Para analista que queira SA, cai no YoY (robusto a sazonalidade).

**Trimmed Sym 25% custom sem YoY**.

- Construção produz só 1-mo annualized; YoY ficaria mal definido via composição de 12 ann_1mo (não bate com YoY direto por conta de drift). Documentado implicitamente (`ann_12mo = NaN` no CSV).

**Dallas Trimmed Mean PCE 404 no FRED** — bloqueia a família PCE, **não CPI**.
- Documentado em `pareto_pce/TODO.md`.

---

## Shape dos dados finais (release Set/2026)

Para auditoria rápida:

| Família              | Universo       | Last date | Linhas SQL approx |
|----------------------|----------------|-----------|-------------------|
| CPI base + custom    | 49 cats × 3 dt | 2026-09   | ~44.700           |
| OER regional         | 4 regions      | 2026-09   | ~2.024            |
| Alt measures         | 9 × 3 metrics  | 2026-09   | ~15.000           |
| Breadth 3-bin        | 3 bins         | 2026-08   | ~900              |
| Diffusion            | 5 series       | 2026-09   | ~1.500            |

**Spot-check** release Set/2026 vs dashboard atual:
- `all_items` NSA YoY = 3.69%, SA YoY = 3.71% — bate release BLS.
- `core` NSA YoY = 2.75%, SA MoM = 0.29% — bate release BLS.
- `sticky_cpi` YoY = 2.82% — bate exato o 2.8% publicado no site Atlanta Fed.
- Cleveland Median 1-mo ann = 2.808% — bate FRED online.

---

## Próximos passos recomendados (ordenado por ROI)

1. **Sanity-range no loader** (MÉDIA) — 20 min, loga WARN se MoM/YoY exceder N desvios.
2. **CI/smoke test pós-fetch** (BAIXA mas valor longo prazo) — script que rode fetch + consolida + compara com snapshot anterior.
3. **Simulate loaders pra alt/breadth/diffusion** (BAIXA) — alinhar com `simulate_cpius_to_sql.py` do CPI principal.
4. **Investigar corp vs local** (ad-hoc, quando confirmar divergência real) — reprodução dedicada no corp.
