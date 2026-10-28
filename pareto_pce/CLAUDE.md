# pareto_pce — pipeline BEA/Fed pra Personal Consumption Expenditures (PCE)

Pipeline irmão do `pareto_cpius` (CPI-US) e `pareto_ipca` (IPCA Brasil) mas pro
**PCE deflator** — a medida de inflação de referência do Fed FOMC. Serve 4
famílias de métricas no SQL corp Itaú (OPT_Macro_Series_2 / Data_2):

1. **Diffusion** (5 series): share de leaves PCE com YoY > 3% (ou 6m-ann > 3%
   só pra Headline), em 4 agregados (Headline, Goods, Services, Goods ex cars).
2. **Breadth** (3 series): distribuição de peso cross-section em 3 bins de YoY
   (`below_0 / 0_to_3 / above_3`), ponderado por nominais BEA.
3. **Altas distribution** (5 series): distribuição Dallas-style em 5 bins de
   **MoM SAAR** (`0-2 / 2-3 / 3-5 / 5-10 / >10`), Headline only. Correlação
   histórica média +0.905 vs Dallas `pcedata.xlsx` (mesma métrica, universos
   próximos).
4. **Alt measures** (2+2 series): Index level dos core alt measures do Fed —
   Cleveland Fed Median PCE + Dallas Fed Trimmed Mean PCE scraped (oficiais)
   + reconstrução bottom-up própria dos 2 (`_proxy`) pra decomposição e
   sensibilidade. Validado: mean|d| YoY 0.09-0.11pp vs oficial (corr +0.99).
   Todos em Index SA rebase Jan/2000=100.

Headline/subcomponentes PCE padrão **NÃO** sobem por aqui — o corp já serve
isso bem via Haver Analytics. Este projeto cobre **só o que o Haver não
entrega** (métricas derivadas: diffusion, breadth, alt measures).

## Estrutura

```
pareto_pce/
├── data/                                  # gerada em runtime (não commitada)
│   ├── pce_indices_raw.csv                # BEA U20404 (price indexes) bruto
│   ├── pce_nominais_raw.csv               # BEA U20405 (current dollars) bruto
│   ├── pce_alt_measures.csv               # Cleveland Median + Dallas Trimmed (scraped), com value_index
│   ├── pce_alt_measures_proxy.csv        # Mesmas 2 measures bottom-up (`_proxy`)
│   ├── pce_diffusion.csv                  # 4 agregados × 2 metrics
│   ├── pce_breadth.csv                    # 3 bins (long: date, bin, weight_share)
│   ├── pce_altas_distribution.csv         # 5 bins Dallas MoM SAAR + bin complemento
│   ├── leaves_detected.csv                # 190 leaves auditáveis (gerado por build_diffusion.py)
│   └── raw/
│       ├── cleveland/median-pce-full-history.csv
│       └── dallas/pcedata.xlsx            # benchmark conceitual (NÃO comparável direto)
├── scripts/
│   ├── fetch_pce.py                       # ⭐ BEA U20404 + U20405 via API
│   ├── build_diffusion.py                 # 190 leaves + 5 series diffusion
│   ├── build_breadth_pce.py               # 3 bins breadth ponderado por nominais
│   ├── build_altas_distribution_pce.py    # 5 bins Dallas MoM SAAR
│   ├── build_alt_measures_pce.py          # Cleveland CSV + Dallas FRED → value_index SA (scraped)
│   └── build_alt_measures_pce_proxy.py   # Mesmas 2 measures bottom-up (190 leaves + nominais)
├── script_itau/
│   ├── load_pce_to_sql.py                 # 5 series diffusion
│   ├── load_breadth_pce_to_sql.py         # 3 series breadth
│   ├── load_altas_distribution_pce_to_sql.py # 5 series altas dist Dallas-style
│   ├── load_alt_measures_pce_to_sql.py    # 2 series alt scraped (Index SA)
│   ├── load_alt_measures_pce_proxy_to_sql.py # 2 series alt bottom-up (_proxy)
│   ├── simulate_pce_to_sql.py             # local mock (só diffusion)
│   └── RUNBOOK.md
├── outputs/dashboards/                    # markdown last-12m + validação
├── CLAUDE.md                              # (este arquivo)
└── TODO.md                                # backlog, open items
```

## Pipeline (ordem mensal)

```bash
cd pareto_pce
export BEA_API_KEY=<key>                             # https://apps.bea.gov/API/signup/

python scripts/fetch_pce.py                          # U20404 + U20405
python scripts/build_diffusion.py                    # exporta leaves_detected.csv tambem
python scripts/build_breadth_pce.py                  # precisa leaves_detected.csv + pce_nominais_raw.csv
python scripts/build_altas_distribution_pce.py       # idem — 5 bins Dallas MoM SAAR
python scripts/build_alt_measures_pce.py             # Cleveland CSV + Dallas FRED (scraped)
python scripts/build_alt_measures_pce_proxy.py      # bottom-up Itau (precisa leaves_detected + nominais)
```

Loaders SQL (só rodam no corp — precisam `opt_utils.database.SQLConnector`):

```bash
python script_itau/load_pce_to_sql.py --dry-run                             # diffusion
python script_itau/load_breadth_pce_to_sql.py --dry-run                     # breadth
python script_itau/load_altas_distribution_pce_to_sql.py --dry-run          # altas dist
python script_itau/load_alt_measures_pce_to_sql.py --dry-run                # alt measures scraped
python script_itau/load_alt_measures_pce_proxy_to_sql.py --dry-run         # alt measures proxy (bottom-up)
```

Cada loader tem `--dry-run`, `--no-confirm`, `--full` (default varia — ver
docstring de cada), e preserva CSV principal se release parcial.

## Convenções SQL (namespace PCE)

Namespace **`PCE:`** disjunto de IPCA, IPCA-15 e CPI-US. Todas usam:
- `country = 'US'`
- `subject = 'Prices'`
- `indicator = 'PCE'`
- `frequency = 'M'`
- `haver_code = NULL` (nunca populado; `bls_code` é a chave de proveniência)

**Diffusion** (5 series, `data_type='NSA'`):
- `PCE:diffusion_headline_yoy`      — Share of items YoY > 3%, Headline
- `PCE:diffusion_headline_6ma_ann`  — Share of items 6m-ann > 3%, Headline
- `PCE:diffusion_goods_yoy`         — Share of items YoY > 3%, Goods
- `PCE:diffusion_services_yoy`      — Share of items YoY > 3%, Services
- `PCE:diffusion_goods_ex_cars_yoy` — Share of items YoY > 3%, Goods ex cars

**Breadth** (3 series, `data_type='NSA'`, soma = 100% por mês):
- `PCE:breadth_above_3pct`
- `PCE:breadth_0_to_3pct`
- `PCE:breadth_below_0pct`

**Altas distribution** (5 series, `data_type='NSA'`, Headline only, bins de MoM SAAR):
- `PCE:altas_dist_0_2`   — share do peso com MoM SAAR em (0, 2]%
- `PCE:altas_dist_2_3`   — (2, 3]%
- `PCE:altas_dist_3_5`   — (3, 5]%
- `PCE:altas_dist_5_10`  — (5, 10]%
- `PCE:altas_dist_gt_10` — > 10%

O CSV também guarda um 6º bin `zero_or_below` (complemento: share com MoM
SAAR ≤ 0) mas ele NÃO sobe pro SQL — alinhado com `pcedata.xlsx` Dallas, que
publica só os 5 positivos. Analista deriva via `(100 - soma dos 5)` se precisar.

**Alt measures scraped** (2 series, `data_type='SA'`, Index level, rebase Jan/2000=100):
- `PCE:alt_median_pce`         — Cleveland CSV oficial
- `PCE:alt_trimmed_mean_pce`   — Dallas FRED oficial

**Alt measures proxy** (2 series paralelas, mesmo schema SA):
- `PCE:alt_median_pce_proxy`         — weighted 50th percentile dos 190 leaves U20404
- `PCE:alt_trimmed_mean_pce_proxy`   — trim 24% low + 31% high dos mesmos leaves

Loader scraped tem `_cleanup_legacy_alt` que apaga qualquer `PCE:alt_%`
**NÃO proxy** fora do plano atual — cobre variantes legadas
`_1mo/_mom_sa/_12mo` do schema antigo. O loader proxy é independente
e nunca é apagado pelo cleanup do scraped (os bls_codes `_proxy` não
colidem com os oficiais).

## Fontes

- **BEA NIPA Underlying Detail** (`apps.bea.gov/api/data/`, dataset
  `NIUnderlyingDetail`):
  - `U20404` — Price Indexes for PCE by Type of Product (320+ linhas/mês × ~400 LineNumbers)
  - `U20405` — Current Dollars (nominais) com estrutura idêntica, usado como peso do breadth
- **Cleveland Fed** — Median PCE full history CSV (`clevelandfed.org/-/media/files/webcharts/medianpce/median-pce-full-history.csv`), 1977+
- **Dallas Fed** — Trimmed Mean PCE via FRED:
  - `PCETRIM1M158SFRBDAL` (1-mo annualized SA) — IDs atualizados 2026-10
  - `PCETRIM12M159SFRBDAL` (12-mo YoY)
  - Fallback xlsx nativo: `dallasfed.org/-/media/documents/research/pce/pcedata.xlsx`

## Diffusion — identificação dos 190 leaves

O U20404 publica ~400 linhas mas a maioria é agregado hierárquico. Pra isolar
os leaves que entram no diffusion/breadth:

1. **Boundary Goods vs Services**: via `LineNumber` da linha "Goods" (=2) e
   "Services" (varia por release). Qualquer leaf entre essas = Goods; qualquer
   leaf depois = Services.
2. **SUBAGG_LINES**: lista manual em `build_diffusion.py` (linhas 26-148) com
   todos os LineNumbers que são agregados hierárquicos (Durable goods,
   Food and beverages, etc.). ~110 agregados.
3. **MARKET_DRIVEN_EXCLUDE** (linhas 164-178): 9 items Services com YoY
   anômalos — imputed financial (Commercial banks, Securities commissions,
   Portfolio mgmt, Trust), streaming (Video, Audio), postal/delivery (First-class
   postal, Other delivery), Air transport. Calibrado 2026-09-10 pra bater o
   chart BBA (Services 58% vs BBA 57.8%).
4. **OUT_OF_SCOPE_RANGES**: Expenditures abroad (146-149), Foreign travel
   (334-341), NPISHs (342-368), Derived aggregates (369-402).
5. **CAR_LINES** (6, 9, 13, 17, 21, 22): 6 leaves de motor vehicles usados
   pra isolar "Goods ex cars".

**Validação (2026-09-10 chart BBA jul-2026)**:
- Goods: 47.8% nosso vs 47.3% BBA (Δ +0.5pp) ✓
- Services: 58.0% nosso vs 57.8% BBA (Δ +0.2pp) ✓
- Goods ex cars: 50.0% nosso vs 49.4% BBA (Δ +0.6pp) ✓
- Cars: 6 items exato ✓

Contagem final 190 leaves (91 Goods + 109 Services) vs 200 BBA — 10 a menos,
% agregado compensa. Fechar exato exige nota interna BBA com lista — ver
TODO.md.

## Alt measures — chain universal pra INDEX

Mesmo padrão do CPI alt measures (sync 2026-10-28):

```
mom_sa = (1 + ann_1mo/100)^(1/12) - 1
idx[t] = idx[t-1] * (1 + mom_sa[t])     # cumprod
```

Rebase final pra Jan/2000=100 por measure. Cleveland CSV + Dallas FRED
ambos publicam `ann_1mo` SA, então chain universal — nenhuma fonte publica
index nativo.

**Validação chain** (dashboard `dashboard_pce_alt_index_check.md`):
- Median Cleveland: 0.0000pp YoY+MoM em TODA história (584 obs YoY, 595 MoM)
- Trimmed Mean Dallas: max 0.0074pp YoY (round-trip de 2 decimais do FRED),
  MoM 0.0000pp exato

## Breadth — peso = nominais BEA do próprio mês

Diferença fundamental vs CPI breadth:
- **CPI**: peso = RI Dez do ano anterior × renormalização mensal (BLS publica
  arquivo histórico de Relative Importance)
- **PCE**: peso = nominal BEA U20405 do próprio mês / Σ_leaves nominal_j(m) ×
  100 (BEA não publica RI em arquivo histórico, mas nominais mensais estão
  disponíveis — approach direto)

Guard de cobertura idêntico (release < 70% dos leaves = data descartada).

**Dallas pcedata.xlsx NÃO é comparador direto do breadth YoY**: Dallas mede
MoM SAAR sobre universe próprio, não YoY sobre U20404. Correlação ~0 esperada
e observada. Pra benchmark apples-to-apples ver seção **Altas distribution**
abaixo (que usa a mesma métrica MoM SAAR que Dallas, só muda universo).

## Altas distribution — 5 bins Dallas-style

Resposta ao pedido "distribuição de altas pra PCE" (Itaú BBA, 2026-10-28).
Decompõe o range positivo de inflação em 5 bins de magnitude (`0-2 / 2-3 /
3-5 / 5-10 / >10%` em MoM SAAR), análogo ao `pcedata.xlsx` do Dallas Fed.

- **Métrica**: MoM SAAR = `((idx[t]/idx[t-1])^12 - 1) * 100` por leaf. U20404
  é SA (confirmado via médias mensais Jan..Dez 2010-2026 todas ~0.14-0.24%
  sem spike sazonal), então chain direto sem STL.
- **Universe**: mesmos 190 leaves do breadth/diffusion.
- **Peso**: mesmo esquema do breadth — nominais BEA U20405 do próprio mês.
- **Headline only**: Dallas não decompõe em Goods/Services; mantemos a mesma
  convenção.
- **6º bin `zero_or_below`**: complemento (share deflationary / flat). Fica
  só no CSV, não vai pro SQL — alinhado com `pcedata.xlsx` Dallas que só
  publica os 5 bins positivos. Derivável via `100 - sum(5)`.

**Validação vs Dallas** (dashboard `dashboard_pce_altas_distribution.md`):
- Correlação média por bin **+0.905** (vs breadth YoY: 0.0). 3-5% tem corr
  +0.977; os outros 4 bins entre +0.849 e +0.916.
- Média histórica de 13 meses overlap: diffs por bin entre -2.35pp e +1.70pp
  (vs breadth: diffs > 20pp).
- Confirma: mesma metodologia que Dallas, só muda universe (190 leaves U20404
  vs ~178 Trimmed Mean components).

## Dashboards

- `outputs/dashboards/dashboard_pce_last_12m.md` — snapshot mensal: alt
  measures (Index + 1mo + mom_sa + YoY) + diffusion (YoY>3% + 6m-ann>3%).
  Regenera com `python outputs/dashboards/_make_dashboard_pce_last_12m.py`.
- `outputs/dashboards/dashboard_pce_alt_index_check.md` — validação chain do
  index alt measures (YoY/MoM derivado vs publicado, max |Δ| < 0.002pp
  esperado).

## Env vars

- `BEA_API_KEY` — obrigatório pro fetch BEA (grátis em `apps.bea.gov/API/signup/`)
- `CORP_PROXY_URL` ou `HTTPS_PROXY` — proxy corp Itaú quando aplicável
- `CACHE_TTL_HOURS=24` — janela de re-fetch pros xlsx/CSV Cleveland+Dallas

## Lições aprendidas (herdadas do CPI)

- **HYC00 no DELETE do loader**: driver corp Microsoft ODBC não aceita
  `datetime.date` em `WHERE date>=? AND date<=?`. Loaders usam só
  `DELETE WHERE series_id = ?` + re-escreve full history. Default `--full`.
- **Proxy senha vencida**: build scripts têm guard anti-regressão silenciosa
  (se vier menos measures que esperado → preserva CSV principal + exit 2).
- **FRED IDs mudam sem aviso**: Dallas trocou `*680SFRBDAL` por
  `*158/159SFRBDAL` em 2026-10. Monitorar via search anual.

## Backlog não crítico

Items que seriam "nice to have" mas não bloqueiam entrega atual (todos
sobreviveram do antigo TODO.md, agora deletado):

- **Gap 10 leaves vs BBA**: 190 (nossos) vs 200 (alvo BBA jul-2026, chart
  interno — 1 Goods + 9 Services faltando). % agregado compensa (Δ ≤ 0.6pp
  nos 3 buckets), mas source não fecha exato. Fechar exige nota BBA com a
  lista oficial; sem ela, iteração vira chute.
- **Peso por expenditure share pro diffusion**: hoje o diffusion é
  count-based ("Share of PCE Items"); versão weighted (nominais U20405) seria
  complementar — reusa a infra do breadth. Chart BBA referência usa count,
  então não é prioritário.
- **Validação amostral do breadth vs snapshots BBA**: se aparecer snapshot
  histórico BBA do breadth, dá pra sanity check pontual.
- **simulate_breadth_pce_to_sql.py**: espelho local sem SQLConnector corp,
  padrão `simulate_pce_to_sql.py`. Loader já validou via `--dry-run`, não
  é urgente.
