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

## Passo 2 — Update do release novo (padrão mensal)

```powershell
# Smoke test primeiro (não toca SQL)
python quick_update/update_cpius_lean.py --cats all --simulate
```

Confirmar no log:
- `API key ON`
- `[fetch] concluido: 98/98 series c/ dados (0 vazias)` (49 cats × 2 sa_flag)
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
