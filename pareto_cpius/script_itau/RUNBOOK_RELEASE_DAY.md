# RUNBOOK — dia do release CPI-U (cheatsheet)

Versão curta pra release day. Full runbook em `RUNBOOK.md`.

**BLS solta 08:30 ET.**

---

## Passo 0 — Preflight (5 min antes)

```powershell
cd pareto_cpius
$env:BLS_API_KEY   # confirma que está setado
```

Se vazio: `$env:BLS_API_KEY = "<sua_chave>"`.

---

## Passo 1 — Update do release (padrão mensal)

```powershell
# Smoke test primeiro (não toca SQL)
python quick_update/update_cpius_lean.py --cats all --simulate
```

Confirmar no log:
- `API key ON`
- `[fetch] concluido: 82/82 series c/ dados (0 vazias)`
- `ultimo mes idx BLS = YYYY-MM` ← **o novo release**
- Nenhum `[WARN] RI_BASE_DATE`
- `[simulate] OPT_Macro_Series_2 = 147 rows`

Se OK, run real:

```powershell
python quick_update/update_cpius_lean.py --cats all > quick_update/logs/lean_$(Get-Date -Format yyyyMMdd).log 2>&1
```

Reescreve últimos 24 meses de cada série (49 cats × 3 datatypes = 147 séries).

---

## Passo 2 — Verificação SQL

```sql
-- 2a. Última data do release chegou?
SELECT s.data_type, MAX(d.date) AS last_date, COUNT(DISTINCT d.series_id) AS n_series
FROM OPT_Macro_Series_Data_2 d
JOIN OPT_Macro_Series_2 s ON s.series_id = d.series_id
WHERE s.bls_code LIKE 'CPIUS:%'
GROUP BY s.data_type;
-- esperado: NSA=49, SA=49, Weight=49; last_date = último dia do mês do release

-- 2b. Spot-check headline vs release BLS
SELECT TOP 3 d.date, d.value
FROM OPT_Macro_Series_Data_2 d
JOIN OPT_Macro_Series_2 s ON s.series_id = d.series_id
WHERE s.bls_code = 'CPIUS:all_items' AND s.data_type = 'NSA'
ORDER BY d.date DESC;
-- valor do mês novo tem que bater CUUR0000SA0 do release
```

---

## Alternativa — Full re-load histórico (raro)

Só usar em revisão SA anual (janeiro) ou pra reconstruir cats do zero. Reescreve jan/2000 → hoje via `replace=True`.

**Full (49 cats × 3 = 147 séries):**
```powershell
Rscript scripts/fetch_bls_cpiu.R
Rscript scripts/fetch_bls_pesos.R
Rscript scripts/build_custom_aggregations.R
python script_itau/load_cpius_to_sql.py --only all
```

**Priority subset (22 cats × 3 = 66 séries, dashboard):**
```powershell
Rscript scripts/fetch_bls_cpiu.R
Rscript scripts/fetch_bls_pesos.R
Rscript scripts/build_custom_aggregations.R
python script_itau/load_cpius_to_sql.py --only all_items,food,energy,core,core_goods,new_vehicles,used_cars_trucks,core_services,shelter,oer,rent,lodging_away,medical_care,transportation_services,airline_fares,car_truck_rental,core_ex_oer,cpi_ex_oer,core_services_ex_shelter,supercore_powell_old,super_super_core,core_services_ex_volatiles
```

---

## Se der pau

| Sintoma | Ação |
|---|---|
| `REQUEST_NOT_PROCESSED` | rate limit; esperar 1h e retentar |
| `Timeout` | rede; retentar. Persistir → full re-load (`RUNBOOK.md`) |
| `[WARN] sem dados: CUUR0000XXX` numa cat | BLS reestruturou item code; ver "Cat solta" no `RUNBOOK.md` |
| `[WARN] RI_BASE_DATE esta N meses atras` | bump anual da RI base; ver `RUNBOOK.md` |
| Valor headline diverge do release | ver "Comparação contra simulação local" no `RUNBOOK.md` |
| Rollback total | ver "Rollback" no `RUNBOOK.md` |
