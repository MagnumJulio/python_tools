# RUNBOOK — dia do release CPI-U (cheatsheet)

Versão curta pra release day. Full runbook em `RUNBOOK.md`.

**BLS solta 08:30 ET.** Este release: Jul/2026 CPI-U.

---

## Passo 0 — 5 min antes (pré-flight)

```powershell
cd pareto_cpius
$env:BLS_API_KEY   # confirma que está setado
```

Se vazio: `$env:BLS_API_KEY = "<sua_chave>"`. Sem chave o rate limit derruba no 2º run.

---

## Passo 1 — Full re-load pós-fix SASL5 (⚠️ SÓ HOJE, primeira vez pós-fix)

Bug SASL5→SASLE foi corrigido 2026-08-11. SQL corp ainda tem contaminação em history > 24 meses pras 6 cats abaixo. Reset completo é `replace=True` do loader (pipeline R full → load `--only`).

```powershell
# 1a. Regenera CSVs com SASLE correto (~35s)
Rscript scripts/fetch_bls_cpiu.R
Rscript scripts/fetch_bls_pesos.R
Rscript scripts/build_custom_aggregations.R

# 1b. Full re-load das 6 cats contaminadas (jan/2000 → hoje)
python script_itau/load_cpius_to_sql.py --only core_services,core_services_ex_shelter,supercore_powell_old,super_super_core,core_services_ex_shelter_pubtrans_medical,core_services_ex_volatiles
```

Confirma `Confirma gravacao de ate 18 series no SQL? [s/N]` → `s`.

Depois de HOJE, próximos releases usam só Passo 2.

---

## Passo 1b — Full re-load pós-fix SETA03→SETA04 car_truck_rental (⚠️ SÓ HOJE)

Bug análogo ao SASL5 achado 2026-08-20: `car_truck_rental` estava fetching **SETA03 = Leased cars and trucks** em vez de **SETA04 = Car and truck rental**. Fix aplicado em `quick_update/update_cpius_lean.py` + `scripts/bls_maps/cpiu_table_1.csv` (reconstruct_cpius.py já estava certo — mesmo padrão SASL5, fix não propagou). Validado contra Haver: 11 de 12 mm SA batem exato pós-fix.

**Bônus:** SETA04 tem 318 obs desde 2000-01, contra 258 do SETA03 (começava só 2001-12) — 60 meses a mais de história.

```powershell
# 1c. Regenera CSVs (mesmo passo do 1a — pipeline R lê cpiu_table_1.csv atualizado)
Rscript scripts/fetch_bls_cpiu.R
Rscript scripts/fetch_bls_pesos.R
Rscript scripts/build_custom_aggregations.R

# 1d. Full re-load só da cat car_truck_rental (jan/2000 → hoje)
python script_itau/load_cpius_to_sql.py --only car_truck_rental
```

Confirma `Confirma gravacao de ate 3 series no SQL? [s/N]` → `s`.

Não afeta customs (nenhuma das 8 recipes usa car_truck_rental).

---

## Passo 1d — Full re-load pós-fix pesos Dez (⚠️ SÓ HOJE)

Bug em `scripts/fetch_bls_pesos.R:106-121` achado 2026-08-20: `choose_base` sempre retornava `y-1` como base, então pra Dez/2025 usava `RI(Dez/2024) × I(Dez/2025)/I(Dez/2024) + renorm`, divergindo do RI publicado pra 2025 (Table 1). Fix: se `m` é Dez de ano `y` e `y ∈ anos_base`, retorna `y` (identidade, ratio=1, w=RI publicado direto). Validado: 41 cats bateram exato com BLS Table 1 (super_super_core weight passou de 18.0259 → 17.5950, off era +0.43pp).

**Impacto na corp SQL**: `update_cpius_lean.py` usa Dez-anchor Laspeyres (`wrow_p = peso_wide.loc[pivot]`), então o peso Dez/2025 é pivô pra todo 2026. Custom aggregations (8 recipes) recebem o fix cascateado. Weight rows das 41 base cats no SQL também mudam em Dez de cada ano — precisam full re-load histórico das 49 cats.

```powershell
# 1e. Regenera CSVs (pipeline R full, mesmo passo 1a/1c)
Rscript scripts/fetch_bls_cpiu.R
Rscript scripts/fetch_bls_pesos.R
Rscript scripts/build_custom_aggregations.R

# 1f. Full re-load histórico das 49 cats (jan/2000 → hoje)
python script_itau/load_cpius_to_sql.py --only all
```

Confirma `Confirma gravacao de ate 147 series no SQL? [s/N]` → `s`.

Bias residual pós-fix vs Haver (super_super_core mm SA ~0.01pp médio / max 0.03pp; core_services_ex_shelter ~0.003pp médio / max 0.06pp) é padrão BLS (renorm top-3=100 vs BLS internal, precisão de índice unrounded) — não vira pra zero. Checagem 2026-08-20: série nativa `SASL2RS` (Services less rent of shelter) bate MUITO pior que nosso derivado (max 0.30pp vs Haver, ex.: Jan/26 -0.30pp, Mai/26 +0.30pp) — Haver não serve SASL2RS, nosso derivado é o mais fiel.

---

## Passo 2 — Update do release novo (padrão mensal)

```powershell
# Smoke test primeiro (não toca SQL)
python quick_update/update_cpius_lean.py --cats all --simulate
```

Confirmar no log:
- `API key ON`
- `[fetch] concluido: 82/82 series c/ dados (0 vazias)` (41 base cats × 2 sa_flag; customs derivam via Laspeyres, não vão pro fetch)
- `ultimo mes idx BLS = 2026-07` ← **o novo release**
- Nenhum `[WARN] RI_BASE_DATE`
- `[simulate] OPT_Macro_Series_2 = 147 rows`

Se OK, run real:

```powershell
python quick_update/update_cpius_lean.py --cats all > quick_update/logs/lean_$(Get-Date -Format yyyyMMdd).log 2>&1
```

Reescreve últimos 24 meses de cada série (49 cats × 3 datatypes = 147 séries).

---

## Passo 3 — Verificação SQL (2 queries)

```sql
-- 3a. Última data do release chegou?
SELECT s.data_type, MAX(d.date) AS last_date, COUNT(DISTINCT d.series_id) AS n_series
FROM OPT_Macro_Series_Data_2 d
JOIN OPT_Macro_Series_2 s ON s.series_id = d.series_id
WHERE s.bls_code LIKE 'CPIUS:%'
GROUP BY s.data_type;
-- esperado: NSA=49, SA=49, Weight=49; last_date = 2026-07-31

-- 3b. Spot-check headline (bate release BLS?)
SELECT TOP 3 d.date, d.value
FROM OPT_Macro_Series_Data_2 d
JOIN OPT_Macro_Series_2 s ON s.series_id = d.series_id
WHERE s.bls_code = 'CPIUS:all_items' AND s.data_type = 'NSA'
ORDER BY d.date DESC;
-- valor Jul/2026 tem que bater CUUR0000SA0 do release
```

---

## Se der pau

| Sintoma | Ação |
|---|---|
| `REQUEST_NOT_PROCESSED` | rate limit; esperar 1h e retentar |
| `Timeout` | rede; retentar. Persistir → Opção B do `RUNBOOK.md` |
| `[WARN] sem dados: CUUR0000XXX` numa cat | BLS reestruturou item code; ver "Cat solta" no `RUNBOOK.md` |
| Valor headline diverge do release | ver "Comparação contra simulação local" no `RUNBOOK.md` |
| Rollback total | ver "Rollback completo" no `RUNBOOK.md` |

---

## Post-release (nice to have)

- Atualiza dashboard Highcharts (backup JSON antes — ver memory `reference_corp_dashboards.md`).
- Se release completou o gap Out+Nov/2025 do shutdown, revisita `_diff_mom_sa.py` — talvez os 4 NaN cells agora bateram Haver.
