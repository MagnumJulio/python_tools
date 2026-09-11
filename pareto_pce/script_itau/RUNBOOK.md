# RUNBOOK — pareto_pce carga no SQL corp

## Pré-requisitos

- Máquina corp com `opt_utils` no PYTHONPATH.
- Env `BEA_API_KEY` setada (registro grátis em https://apps.bea.gov/API/signup/).
- Coluna `bls_code` já criada no `OPT_Macro_Series_2` (compartilhada com IPCA/CPI-US).

## Escopo servido

5 séries no SQL corp, todas `country='US'`, `subject='Prices'`,
`indicator='PCE'`, `data_type='NSA'`, `frequency='M'`:

| bls_code | series_name |
|---|---|
| `PCE:diffusion_headline_yoy` | PCE: Diffusion Headline (YoY > 3%) |
| `PCE:diffusion_headline_6ma_ann` | PCE: Diffusion Headline (6m annualized > 3%) |
| `PCE:diffusion_goods_yoy` | PCE: Diffusion Goods (YoY > 3%) |
| `PCE:diffusion_services_yoy` | PCE: Diffusion Services (YoY > 3%) |
| `PCE:diffusion_goods_ex_cars_yoy` | PCE: Diffusion Goods ex Cars (YoY > 3%) |

Cobertura: **2001-01 → mês mais recente do release BEA** (~300 obs por série).

## Fluxo de release day

BEA publica PCE ~último dia útil do mês, ~08:30 EST. Roda pipeline logo depois:

```bash
cd pareto_pce
python scripts/fetch_pce.py         # ~30-60s, puxa U20404 completo
python scripts/build_diffusion.py   # <5s, gera data/pce_diffusion.csv
```

Verifica sanity:
- Contagem: Goods=90, Services=100, Cars=6 (após MARKET_DRIVEN_EXCLUDE).
- Julho 2026 esperado (referência atual): Goods ~47.8%, Services ~58%, Goods_ex_cars ~50%, Cars exato.

## Carga corp

```bash
# 1. Dry-run: confirma escopo, não abre conexão SQL
python script_itau/load_pce_to_sql.py --dry-run

# 2. Check: preflight read-only (conexão, tabelas, coluna bls_code)
python script_itau/load_pce_to_sql.py --check

# 3. Carga real
python script_itau/load_pce_to_sql.py
# Pede confirmação [s/N]. Grava 5 séries em OPT_Macro_Series_2 + ~1500 rows
# em OPT_Macro_Series_Data_2. Substitui data existente por series_id
# (replace=True), preserva metadados. haver_code = NULL nos INSERTs novos.
```

## Simulate (casa, sem SQL)

Testa mapping/labels sem tocar em SQL corp:

```bash
python script_itau/simulate_pce_to_sql.py --save
# Gera script_itau/sim_output/OPT_Macro_Series_2.csv e
# OPT_Macro_Series_Data_2.csv espelhando o schema corp.
```

## Rollback

Não há rollback automático. Se a carga der errado:

```sql
-- Lista as 5 séries PCE
SELECT * FROM OPT_Macro_Series_2 WHERE bls_code LIKE 'PCE:%';

-- Deleta dados (substitui na próxima corrida do loader)
DELETE FROM OPT_Macro_Series_Data_2
WHERE series_id IN (SELECT series_id FROM OPT_Macro_Series_2 WHERE bls_code LIKE 'PCE:%');

-- Deleta metadados (nunca fazer sem consenso — quebra dashboards)
-- DELETE FROM OPT_Macro_Series_2 WHERE bls_code LIKE 'PCE:%';
```

## Convenções

- **Namespace disjunto**: `PCE:%` no `bls_code` nunca colide com `IPCA:%`,
  `IPCA15:%`, `CPIUS:%`. Migração `_migrate_pce_to_current` filtra
  estritamente `PCE:%` ou `PARETO_PCE:%` — nunca toca outros projetos.
- **Sem SA**: BEA U20404 é publicado apenas em versão NSA. As séries de
  difusão são medidas de composição e não sofrem tratamento X-13.
- **Sem Weight**: métrica não é preço, é share (%). Nenhum Weight
  companheiro.
