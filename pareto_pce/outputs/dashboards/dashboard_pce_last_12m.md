# PCE dashboard — últimos 12 meses

**Alt measures last date**: 2026-08. **Diffusion last date**: 2026-07 (pode defasar vs alt — depende do release BEA U20404).

Gerado por `outputs/dashboards/_make_dashboard_pce_last_12m.py` em cima de `pce_alt_measures.csv` (Cleveland CSV + Dallas FRED) e `pce_diffusion.csv` (BEA U20404, 190 leaves ponderados por count).

> **Notas de cobertura**:
> - Alt measures no SQL: 2 series `PCE:alt_{median_pce,trimmed_mean_pce}` (Index SA, rebase Jan/2000=100, sync 2026-10-28).
> - Diffusion no SQL: 5 series `PCE:diffusion_{headline,goods,services,goods_ex_cars}_yoy` + `PCE:diffusion_headline_6ma_ann` (count-based, nao ponderado).
> - Dallas IDs renomeados em 2026-10 (`PCETRIM1M158SFRBDAL` + `PCETRIM12M159SFRBDAL`) — antigos `680SFRBDAL` retornavam 404.
> - Diffusion 6m-ann > 3% so e publicada pra Headline (bate `build_diffusion.py`); Goods/Services nao tem essa metrica.

### Alt measures — Index level (SA, Jan/2000=100)

Nível do índice que vai pro SQL (`PCE:alt_{measure}`, data_type=SA). Derivadas: YoY = idx[t]/idx[t-12]-1, MoM = idx[t]/idx[t-1]-1.

| Série | 2025-09 | 2025-10 | 2025-11 | 2025-12 | 2026-01 | 2026-02 | 2026-03 | 2026-04 | 2026-05 | 2026-06 | 2026-07 | 2026-08 |
|:---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Median (Cleveland) | 195.016 | 195.329 | 195.644 | 196.173 | 196.602 | 197.040 | 197.512 | 197.984 | 198.562 | 198.861 | 199.293 | 199.672 |
| Trimmed Mean (Dallas) | 175.325 | 175.563 | 175.808 | 176.146 | 176.498 | 176.779 | 177.153 | 177.619 | 178.058 | 178.282 | 178.558 | 178.841 |

### Alt measures — 1-mo annualized (%)

Taxa anualizada do mês. Cleveland Median (1977+ full history), Dallas Trimmed Mean (1977+ full history).

| Série | 2025-09 | 2025-10 | 2025-11 | 2025-12 | 2026-01 | 2026-02 | 2026-03 | 2026-04 | 2026-05 | 2026-06 | 2026-07 | 2026-08 |
|:---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Median (Cleveland) | 2.12 | 1.94 | 1.95 | 3.29 | 2.66 | 2.71 | 2.91 | 2.91 | 3.56 | 1.82 | 2.64 | 2.31 |
| Trimmed Mean (Dallas) | 2.17 | 1.64 | 1.69 | 2.33 | 2.42 | 1.93 | 2.57 | 3.20 | 3.01 | 1.52 | 1.87 | 1.92 |

### Alt measures — proxy MoM SA (%)

Variação mensal SA derivada do 1-mo annualized: `mom_sa = (1+ann_1mo/100)^(1/12)-1`. Mesma unidade do MoM SA do dash PCE principal (Haver).

| Série | 2025-09 | 2025-10 | 2025-11 | 2025-12 | 2026-01 | 2026-02 | 2026-03 | 2026-04 | 2026-05 | 2026-06 | 2026-07 | 2026-08 |
|:---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Median (Cleveland) | 0.18 | 0.16 | 0.16 | 0.27 | 0.22 | 0.22 | 0.24 | 0.24 | 0.29 | 0.15 | 0.22 | 0.19 |
| Trimmed Mean (Dallas) | 0.18 | 0.14 | 0.14 | 0.19 | 0.20 | 0.16 | 0.21 | 0.26 | 0.25 | 0.13 | 0.15 | 0.16 |

### Alt measures — YoY (%)

Variação 12 meses. Cleveland sai do CSV direto, Dallas do FRED `PCETRIM12M159SFRBDAL` (round-trip de 2 decimais pode criar diff ~0.01pp vs derivado do index).

| Série | 2025-09 | 2025-10 | 2025-11 | 2025-12 | 2026-01 | 2026-02 | 2026-03 | 2026-04 | 2026-05 | 2026-06 | 2026-07 | 2026-08 |
|:---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Median (Cleveland) | 3.38 | 3.21 | 3.10 | 3.06 | 2.98 | 2.91 | 2.86 | 2.82 | 2.87 | 2.71 | 2.70 | 2.57 |
| Trimmed Mean (Dallas) | 2.76 | 2.60 | 2.52 | 2.47 | 2.45 | 2.38 | 2.36 | 2.38 | 2.44 | 2.28 | 2.28 | 2.19 |

### Diffusion — share de itens com YoY > 3% (%)

Difusão item-level sobre 190 leaves do BEA U20404. Fração de itens com YoY acima de 3%, por bloco. Count-based, não ponderado.

| Série | 2025-08 | 2025-09 | 2025-10 | 2025-11 | 2025-12 | 2026-01 | 2026-02 | 2026-03 | 2026-04 | 2026-05 | 2026-06 | 2026-07 |
|:---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Headline (todos itens) | 41.05 | 42.63 | 40.00 | 42.63 | 44.74 | 47.37 | 51.05 | 52.63 | 49.47 | 49.47 | 49.47 | 53.16 |
| Goods | 25.56 | 28.89 | 27.78 | 26.67 | 33.33 | 33.33 | 47.78 | 45.56 | 46.67 | 43.33 | 43.33 | 47.78 |
| Goods ex cars | 23.81 | 27.38 | 26.19 | 25.00 | 33.33 | 35.71 | 48.81 | 46.43 | 47.62 | 46.43 | 45.24 | 50.00 |
| Services | 55.00 | 55.00 | 51.00 | 57.00 | 55.00 | 60.00 | 54.00 | 59.00 | 52.00 | 55.00 | 55.00 | 58.00 |

### Diffusion — share de itens com 6m-ann > 3% (%)

Mesma difusão mas usando variação 6 meses anualizada (sinal mais tempestivo que YoY).

| Série | 2025-08 | 2025-09 | 2025-10 | 2025-11 | 2025-12 | 2026-01 | 2026-02 | 2026-03 | 2026-04 | 2026-05 | 2026-06 | 2026-07 |
|:---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Headline (todos itens) | 42.63 | 44.21 | 42.63 | 41.05 | 44.21 | 42.63 | 50.53 | 50.53 | 51.05 | 51.58 | 47.89 | 47.89 |
