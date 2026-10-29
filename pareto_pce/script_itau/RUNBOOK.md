# RUNBOOK — pareto_pce carga no SQL corp

> **Atualizado 2026-10-29**: adicionados 4 series diffusion MoM>0 (impulso
> corrente) + 4 series alt measures proxy Goods/Services. Total agora: **25
> series PCE** (era 17).

## Pré-requisitos

- Máquina corp com `opt_utils` no PYTHONPATH.
- Env `BEA_API_KEY` setada (registro grátis em https://apps.bea.gov/API/signup/).
- Proxy corp: scripts já leem `HTTP_PROXY`/`HTTPS_PROXY` do ambiente (corp
  seta por default). Só se precisar forçar outro: `set CORP_PROXY_URL=http://<user>:<pass>@...`
  como override.
- Coluna `bls_code` já criada no `OPT_Macro_Series_2` (compartilhada com
  IPCA/CPI-US).

## Escopo servido — 25 series no SQL corp

Todas `country='US'`, `subject='Prices'`, `indicator='PCE'`, `frequency='M'`.

### Diffusion (9 series, `data_type='NSA'`)

**YoY > 3%** (sinal estrutural — carrega 12m de bagagem):

| bls_code | series_name |
|---|---|
| `PCE:diffusion_headline_yoy`      | PCE: Diffusion Headline (YoY > 3%) |
| `PCE:diffusion_headline_6ma_ann`  | PCE: Diffusion Headline (6m annualized > 3%) |
| `PCE:diffusion_goods_yoy`         | PCE: Diffusion Goods (YoY > 3%) |
| `PCE:diffusion_services_yoy`      | PCE: Diffusion Services (YoY > 3%) |
| `PCE:diffusion_goods_ex_cars_yoy` | PCE: Diffusion Goods ex Cars (YoY > 3%) |

**MoM > 0** (impulso corrente — share em inflação positiva vs deflationary):

| bls_code | series_name |
|---|---|
| `PCE:diffusion_headline_mom_above_0`      | PCE: Diffusion Headline (MoM > 0%) |
| `PCE:diffusion_goods_mom_above_0`         | PCE: Diffusion Goods (MoM > 0%) |
| `PCE:diffusion_services_mom_above_0`      | PCE: Diffusion Services (MoM > 0%) |
| `PCE:diffusion_goods_ex_cars_mom_above_0` | PCE: Diffusion Goods ex Cars (MoM > 0%) |

### Breadth (3 series, `data_type='NSA'`, soma = 100% por mês)

| bls_code | series_name |
|---|---|
| `PCE:breadth_above_3pct` | PCE: Breadth (share YoY > 3%) |
| `PCE:breadth_0_to_3pct`  | PCE: Breadth (share 0 ≤ YoY ≤ 3%) |
| `PCE:breadth_below_0pct` | PCE: Breadth (share YoY < 0%) |

### Altas distribution (5 series, `data_type='NSA'`, Headline only, Dallas-style)

| bls_code | series_name |
|---|---|
| `PCE:altas_dist_0_2`   | PCE: Distribuicao de altas (0-2% MoM SAAR) |
| `PCE:altas_dist_2_3`   | PCE: Distribuicao de altas (2-3% MoM SAAR) |
| `PCE:altas_dist_3_5`   | PCE: Distribuicao de altas (3-5% MoM SAAR) |
| `PCE:altas_dist_5_10`  | PCE: Distribuicao de altas (5-10% MoM SAAR) |
| `PCE:altas_dist_gt_10` | PCE: Distribuicao de altas (>10% MoM SAAR) |

### Alt measures scraped (2 series, `data_type='SA'`, Index Jan/2000=100)

| bls_code | series_name |
|---|---|
| `PCE:alt_median_pce`       | PCE: Median (Cleveland Fed) (Index) |
| `PCE:alt_trimmed_mean_pce` | PCE: Trimmed Mean (Dallas Fed) (Index) |

### Alt measures proxy (6 series, `data_type='SA'`, bottom-up Itaú)

Headline (pair com scraped Fed oficial):

| bls_code | series_name |
|---|---|
| `PCE:alt_median_pce_proxy`       | PCE: Median PCE (Index, proxy bottom-up Itau) |
| `PCE:alt_trimmed_mean_pce_proxy` | PCE: Trimmed Mean PCE (Index, proxy bottom-up Itau) |

Goods / Services (**sem oficial** — Fed não decompõe):

| bls_code | series_name |
|---|---|
| `PCE:alt_median_pce_goods_proxy`           | PCE: Median PCE Goods (Index, proxy bottom-up Itau) |
| `PCE:alt_trimmed_mean_pce_goods_proxy`     | PCE: Trimmed Mean PCE Goods (Index, proxy bottom-up Itau) |
| `PCE:alt_median_pce_services_proxy`        | PCE: Median PCE Services (Index, proxy bottom-up Itau) |
| `PCE:alt_trimmed_mean_pce_services_proxy`  | PCE: Trimmed Mean PCE Services (Index, proxy bottom-up Itau) |

Cobertura: **2000-01/2001-01 → mês mais recente do release BEA** (~300 obs
por série, exceto alt measures scraped que vão até 1977+).

## Calendário de release

- **BEA Personal Income and Outlays** (inclui o PCE Price Index via NIPA
  Table 2.4.4/U20404 e U20405): aproximadamente **última sexta-feira do mês**
  (ou dias antes/depois), **08:30 ET**. Dado publicado é do mês anterior.
  Calendário oficial: https://www.bea.gov/news/schedule
- **Cleveland Fed Median PCE** (CSV): atualiza no mesmo dia ou dia seguinte
  ao release BEA.
- **Dallas Fed Trimmed Mean PCE** (FRED): atualiza no mesmo dia do release
  BEA, geralmente até 1-2 dias depois.

Pipeline inteiro pode rodar no mesmo dia do release BEA. Alt measures custom
+ breadth + altas distribution dependem de U20404 + U20405 do mesmo release,
então saem juntos.

## Fluxo de release day — pipeline completo

**Importante — timing BEA vs Fed**: BEA publica U20404/U20405 ~08:30 ET;
Cleveland CSV e Dallas FRED atualizam **algumas horas depois** (às vezes dia
seguinte). Isso tem implicação direta pros builds:

| Build | Depende de que fonte publicou? |
|---|---|
| `fetch_pce.py` + `build_diffusion.py` + `build_breadth_pce.py` + `build_altas_distribution_pce.py` | **só BEA** — podem rodar logo após 08:30 ET |
| `build_alt_measures_pce_proxy.py` | **só BEA** — mesma coisa, roda cedo |
| `build_alt_measures_pce.py` (scraped) | BEA + Cleveland + Dallas — **espera as 3 publicarem** |

Ou seja: **as 2 series proxy e todas as outras (diffusion, breadth, altas
dist) estão disponíveis já na manhã do release**, antes do scraped. É
exatamente o propósito do proxy: dar leitura das alt measures imediatamente,
sem esperar Fed. Scraped vem depois no mesmo dia como validação/overwrite.

```cmd
cd pareto_pce

:: Fase 1a — pos release BEA (manha, ~08:35 ET)
python scripts/fetch_pce.py                          :: ~30-60s (U20404 + U20405)
python scripts/build_diffusion.py                    :: <5s (gera leaves_detected.csv)
python scripts/build_breadth_pce.py                  :: <5s (precisa leaves_detected + nominais)
python scripts/build_altas_distribution_pce.py       :: <5s (idem)
python scripts/build_alt_measures_pce_proxy.py --skip-benchmark   :: <5s, bottom-up BEA puro
                                                     :: (--skip-benchmark pula print vs scraped stale)

:: Fase 1b — mais tarde no dia (Cleveland + Dallas ja publicaram)
python scripts/build_alt_measures_pce.py             :: ~30s (Cleveland CSV + Dallas FRED)
python scripts/build_alt_measures_pce_proxy.py       :: re-roda sem flag pra ver benchmark final
```

**Sanity automática** entre fase 1 e fase 2:

- Diffusion: Goods=90, Services=100, Cars=6 após MARKET_DRIVEN_EXCLUDE.
- Breadth: `n_bad = 0` no sanity (soma dos 3 bins = 100 em todas as datas).
- Altas distribution: `sanity` = 100.00±0.01 por data (6 bins incluindo
  `zero_or_below`).
- Alt measures: proxy mean|d| YoY vs scraped < 0.3pp (impresso no final do build).

**Fase 2 — loaders** (ordem flexível, cada um independente):

```cmd
:: Grupo A — sobem logo apos fase 1a (manha, independentes do Fed)
python script_itau/load_pce_to_sql.py --no-confirm                           :: 5 series diffusion
python script_itau/load_breadth_pce_to_sql.py --no-confirm --full            :: 3 series breadth
python script_itau/load_altas_distribution_pce_to_sql.py --no-confirm --full :: 5 series altas dist
python script_itau/load_alt_measures_pce_proxy_to_sql.py --no-confirm        :: 2 series proxy

:: Grupo B — sobem depois (precisa Cleveland + Dallas publicarem)
python script_itau/load_alt_measures_pce_to_sql.py --no-confirm              :: 2 series scraped + cleanup
```

Cada loader tem `--dry-run` pra listar o escopo sem abrir conexao SQL.

Total: 25 series × ~300 obs ≈ 7500 rows novas/atualizadas em
`OPT_Macro_Series_Data_2` por release. Cada loader faz `DELETE WHERE
series_id = ?` + re-escreve full (pattern HYC00-safe).

## Validação pós-carga

Após rodar os 5 loaders, confirmar no SQL:

```sql
-- Deve retornar 25 series
SELECT COUNT(*) FROM OPT_Macro_Series_2 WHERE bls_code LIKE 'PCE:%';

-- Breakdown por família (deve ser 9/3/5/2/6)
SELECT
    CASE
        WHEN bls_code LIKE 'PCE:diffusion_%' THEN 'diffusion'
        WHEN bls_code LIKE 'PCE:breadth_%'   THEN 'breadth'
        WHEN bls_code LIKE 'PCE:altas_dist_%' THEN 'altas_dist'
        WHEN bls_code LIKE 'PCE:alt_%_proxy'  THEN 'alt_proxy'
        WHEN bls_code LIKE 'PCE:alt_%'       THEN 'alt_scraped'
        ELSE 'other'
    END AS familia,
    COUNT(*) AS n
FROM OPT_Macro_Series_2
WHERE bls_code LIKE 'PCE:%'
GROUP BY 1;

-- Última data de cada série (deve bater com o release)
SELECT s.bls_code, MAX(d.date) AS last_date
FROM OPT_Macro_Series_2 s
JOIN OPT_Macro_Series_Data_2 d ON d.series_id = s.series_id
WHERE s.bls_code LIKE 'PCE:%'
GROUP BY s.bls_code
ORDER BY s.bls_code;
```

Dashboards locais pra sanity visual (regenera depois dos builds):

```cmd
python outputs/dashboards/_make_dashboard_pce_last_12m.py              :: snapshot mensal
python outputs/dashboards/_make_dashboard_pce_alt_index_check.py       :: chain fidelity alt scraped
python outputs/dashboards/_make_dashboard_pce_alt_proxy_vs_official.py :: proxy vs oficial
python outputs/dashboards/_make_dashboard_pce_breadth_check.py         :: breadth sanity
python outputs/dashboards/_make_dashboard_pce_altas_distribution.py    :: altas dist + Dallas
```

## Simulate (casa, sem SQL)

Testa mapping/labels do diffusion sem tocar em SQL corp:

```cmd
python script_itau/simulate_pce_to_sql.py --save
:: Gera script_itau/sim_output/OPT_Macro_Series_2.csv +
:: OPT_Macro_Series_Data_2.csv espelhando o schema corp.
```

(Simulate pros outros loaders é TODO não-urgente — ver backlog no CLAUDE.md.)

## Rollback

Não há rollback automático. Se precisar desfazer alguma coisa:

```sql
-- Lista tudo PCE
SELECT * FROM OPT_Macro_Series_2 WHERE bls_code LIKE 'PCE:%';

-- Rollback por família (ajuste o LIKE)
DELETE FROM OPT_Macro_Series_Data_2
WHERE series_id IN (
    SELECT series_id FROM OPT_Macro_Series_2
    WHERE bls_code LIKE 'PCE:altas_dist_%'
);
DELETE FROM OPT_Macro_Series_2 WHERE bls_code LIKE 'PCE:altas_dist_%';

-- Rollback apenas dos proxy (preservando scraped)
DELETE FROM OPT_Macro_Series_Data_2
WHERE series_id IN (
    SELECT series_id FROM OPT_Macro_Series_2
    WHERE bls_code LIKE 'PCE:alt_%_proxy'
);
DELETE FROM OPT_Macro_Series_2 WHERE bls_code LIKE 'PCE:alt_%_proxy';
```

Após rollback de dados, re-rodar o loader da família substitui limpo.

## Problemas conhecidos

- **Dallas FRED 404** (histórico 2026-10): IDs `PCETRIM1M680SFRBDAL` +
  `PCETRIM12M680SFRBDAL` sumiram do FRED. Agora usamos
  `PCETRIM1M158SFRBDAL` + `PCETRIM12M159SFRBDAL`. Se Dallas renomear de
  novo, ver fallback xlsx em `reference_fed_alt_measures_endpoints`
  (memory) — `dallasfed.org/-/media/documents/research/pce/pcedata.xlsx`.
- **HYC00 no DELETE** (histórico 2026-10): driver corp Microsoft ODBC
  rejeita `WHERE date>=? AND date<=?` com `datetime.date`. Loaders usam
  só `DELETE WHERE series_id = ?`.
- **Proxy senha vence**: builds têm guard anti-regressão silenciosa —
  se vier menos measures que esperado (ex.: FRED fora), preservam CSV
  principal e saem com `exit 2`. Jupyter/pipeline deve detectar o rc.

## Convenções

- **Namespace disjunto**: `PCE:%` no `bls_code` nunca colide com `IPCA:%`,
  `IPCA15:%`, `CPIUS:%`.
- **Alt measures scraped vs proxy**: suffix `_proxy` identifica a
  reconstrução bottom-up. Loaders são independentes; cleanup do scraped
  (`_cleanup_legacy_alt`) tem filtro `NOT LIKE '%\_proxy'` que protege
  as proxy de serem apagadas.
- **SA vs NSA**:
  - Alt measures (scraped + proxy): `SA` (fontes publicam SA; U20404
    confirmado SA via sanity).
  - Diffusion / breadth / altas distribution: `NSA` — métricas de
    composição, não de nível.
- **Sem Weight**: nenhuma métrica aqui é preço em si; são shares (%) ou
  indices derivados. Nenhum `Weight` companheiro.
- **haver_code = NULL** em todos os INSERTs novos (bls_code é a chave de
  proveniência).
