# PCE alt measures — validação da série INDEX

**Last date**: 2026-08. Fonte: `data/pce_alt_measures.csv`. Index rebase: Jan/2000=100.

Esse dashboard foi gerado pra **conferir se o index está mantendo conta** depois do sync 2026-10-28 (SQL PCE alt agora só sobe level, não mais rate; Dallas FRED IDs renomeados — antigos `680SFRBDAL` retornavam 404, novos `158SFRBDAL` + `159SFRBDAL`).

**Metodologia do index**: `idx[t] = idx[t-1] * (1 + mom[t])` com `mom = (1+ann_1mo/100)^(1/12)−1`. Rebase final pra Jan/2000=100 por measure. Nenhuma das 2 fontes (Cleveland CSV, Dallas FRED) publica index level nativo — ambas publicam só os rates. Chain universal.

**Checks**:
1. **Chain fidelity**: max|diff| entre YoY/MoM derivado do index vs valor publicado — tem que ser `~0` pra toda measure com overlap.
2. **Anchors long-run**: idx em datas de referência (1980, 2000, 2010, 2020, last).
3. **Side-by-side último ano**: YoY derivado vs publicado em cada mês dos últimos 12m; coluna de diff tem que ser `0.00`-ish.

### Chain fidelity — diff entre derivado e publicado (TODA a história)

YoY: compara `yoy_derived = idx[t]/idx[t-12]-1` com `ann_12mo` publicado. MoM: compara `mom_derived = idx[t]/idx[t-1]-1` com `mom_sa` (proxy do ann_1mo pela inversão).

| Série | n_yoy_overlap | max_diff_yoy_pp | mean_diff_yoy_pp | n_mom_overlap | max_diff_mom_pp | mean_diff_mom_pp |
|:---|---:|---:|---:|---:|---:|---:|
| Median (Cleveland) | 584.0000 | 0.0000 | 0.0000 | 595.0000 | 0.0000 | 0.0000 |
| Trimmed Mean (Dallas) | 583.0000 | 0.0074 | 0.0025 | 594.0000 | 0.0000 | 0.0000 |

### Index level — anchors long-run

Jan/2000=100 por construção. Cleveland + Dallas começam 1977+ (ambas mostradas em 1980 pra ter buffer de histórico).

| Série | 1980-01 | 2000-01 | 2010-01 | 2020-01 | 2026-08 |
|:---|---:|---:|---:|---:|---:|
| Median (Cleveland) | 46.592 | 100.000 | 129.104 | 158.499 | 199.672 |
| Trimmed Mean (Dallas) | 50.482 | 100.000 | 124.422 | 147.109 | 178.841 |

### Index level — últimos 24 meses

Nível do índice (rebase Jan/2000=100). É isso que vai pro SQL (`PCE:alt_{measure}`, data_type=SA, 2 series).

| Série | 2024-09 | 2024-10 | 2024-11 | 2024-12 | 2025-01 | 2025-02 | 2025-03 | 2025-04 | 2025-05 | 2025-06 | 2025-07 | 2025-08 | 2025-09 | 2025-10 | 2025-11 | 2025-12 | 2026-01 | 2026-02 | 2026-03 | 2026-04 | 2026-05 | 2026-06 | 2026-07 | 2026-08 |
|:---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Median (Cleveland) | 188.645 | 189.258 | 189.761 | 190.356 | 190.913 | 191.462 | 192.016 | 192.547 | 193.022 | 193.616 | 194.046 | 194.675 | 195.016 | 195.329 | 195.644 | 196.173 | 196.602 | 197.040 | 197.512 | 197.984 | 198.562 | 198.861 | 199.293 | 199.672 |
| Trimmed Mean (Dallas) | 170.619 | 171.108 | 171.483 | 171.892 | 172.276 | 172.676 | 173.068 | 173.491 | 173.823 | 174.308 | 174.571 | 175.012 | 175.325 | 175.563 | 175.808 | 176.146 | 176.498 | 176.779 | 177.153 | 177.619 | 178.058 | 178.282 | 178.558 | 178.841 |

### YoY derivado do index — últimos 12 meses (%)

`yoy_derived[t] = idx[t]/idx[t-12] - 1`. Tem que bater YoY publicado.

| Série | 2025-09 | 2025-10 | 2025-11 | 2025-12 | 2026-01 | 2026-02 | 2026-03 | 2026-04 | 2026-05 | 2026-06 | 2026-07 | 2026-08 |
|:---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Median (Cleveland) | 3.377 | 3.208 | 3.100 | 3.056 | 2.980 | 2.914 | 2.862 | 2.824 | 2.870 | 2.709 | 2.704 | 2.567 |
| Trimmed Mean (Dallas) | 2.758 | 2.604 | 2.523 | 2.475 | 2.450 | 2.376 | 2.360 | 2.379 | 2.437 | 2.280 | 2.283 | 2.188 |

### YoY publicado — últimos 12 meses (%)

`ann_12mo` do CSV, direto de Cleveland CSV / Dallas FRED.

| Série | 2025-09 | 2025-10 | 2025-11 | 2025-12 | 2026-01 | 2026-02 | 2026-03 | 2026-04 | 2026-05 | 2026-06 | 2026-07 | 2026-08 |
|:---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Median (Cleveland) | 3.377 | 3.208 | 3.100 | 3.056 | 2.980 | 2.914 | 2.862 | 2.824 | 2.870 | 2.709 | 2.704 | 2.567 |
| Trimmed Mean (Dallas) | 2.760 | 2.600 | 2.520 | 2.470 | 2.450 | 2.380 | 2.360 | 2.380 | 2.440 | 2.280 | 2.280 | 2.190 |

### YoY — diff (derivado − publicado), últimos 12 meses (pp)

Dallas FRED publica com 2 casas decimais → round-trip de ~0.01pp esperado. Cleveland CSV preserva precisão.

| Série | 2025-09 | 2025-10 | 2025-11 | 2025-12 | 2026-01 | 2026-02 | 2026-03 | 2026-04 | 2026-05 | 2026-06 | 2026-07 | 2026-08 |
|:---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Median (Cleveland) | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 |
| Trimmed Mean (Dallas) | -0.0019 | 0.0038 | 0.0027 | 0.0052 | 0.0002 | -0.0040 | 0.0003 | -0.0007 | -0.0034 | 0.0001 | 0.0035 | -0.0021 |

### MoM derivado do index — últimos 12 meses (%)

`mom_derived[t] = idx[t]/idx[t-1] - 1`.

| Série | 2025-09 | 2025-10 | 2025-11 | 2025-12 | 2026-01 | 2026-02 | 2026-03 | 2026-04 | 2026-05 | 2026-06 | 2026-07 | 2026-08 |
|:---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Median (Cleveland) | 0.1753 | 0.1606 | 0.1611 | 0.2702 | 0.2187 | 0.2231 | 0.2391 | 0.2392 | 0.2917 | 0.1506 | 0.2177 | 0.1902 |
| Trimmed Mean (Dallas) | 0.1791 | 0.1357 | 0.1398 | 0.1921 | 0.1995 | 0.1594 | 0.2117 | 0.2628 | 0.2474 | 0.1258 | 0.1545 | 0.1586 |

### MoM publicado (mom_sa proxy) — últimos 12 meses (%)

`mom_sa = (1+ann_1mo/100)^(1/12) - 1` do CSV.

| Série | 2025-09 | 2025-10 | 2025-11 | 2025-12 | 2026-01 | 2026-02 | 2026-03 | 2026-04 | 2026-05 | 2026-06 | 2026-07 | 2026-08 |
|:---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Median (Cleveland) | 0.1753 | 0.1606 | 0.1611 | 0.2702 | 0.2187 | 0.2231 | 0.2391 | 0.2392 | 0.2917 | 0.1506 | 0.2177 | 0.1902 |
| Trimmed Mean (Dallas) | 0.1791 | 0.1357 | 0.1398 | 0.1921 | 0.1995 | 0.1594 | 0.2117 | 0.2628 | 0.2474 | 0.1258 | 0.1545 | 0.1586 |

### MoM — diff (derivado − publicado), últimos 12 meses (pp)

Deve ser `0.0000` exato (chain usa o mesmo mom_sa pra encadear).

| Série | 2025-09 | 2025-10 | 2025-11 | 2025-12 | 2026-01 | 2026-02 | 2026-03 | 2026-04 | 2026-05 | 2026-06 | 2026-07 | 2026-08 |
|:---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Median (Cleveland) | -0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | -0.0000 | 0.0000 | -0.0000 | 0.0000 |
| Trimmed Mean (Dallas) | -0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | -0.0000 | 0.0000 | -0.0000 | 0.0000 | 0.0000 | 0.0000 | -0.0000 |
