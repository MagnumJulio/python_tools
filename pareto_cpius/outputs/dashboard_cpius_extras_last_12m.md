# CPI-U dashboard extras — últimos 12 meses

**Alt measures/Breadth last date**: 2026-09. **Diffusion last date**: 2026-09 (pode defasar vs alt — depende de todas as subitens leaves estarem no cache).

Gerado por `outputs/_make_dashboard_extras_last_12m.py` em cima de `cpi_cpius_alt_measures.csv` (Atlanta xlsx + Cleveland CSV + custom), `cpi_cpius_breadth.csv` (cross-section 177 subitens pesados pela RI) e `cpiu_diffusion.csv` (item-level ponderado, 4 aggregates).

> **Notas de cobertura**:
> - Cleveland Median/Trimmed Mean 16% publicam **só YoY** (sem 1-mo annualized) — células de 1mo aparecem `n/a`.
> - Trimmed Sym 25% custom tem **só 1-mo annualized** (construção não produz YoY) — células de YoY aparecem `n/a`.
> - Breadth em **2025-10 descartado** (cobertura 11% < 70% threshold): release BLS incompleto no shutdown. Guard aplicado em `build_breadth_cpi.py` descarta datas com cobertura abaixo do limiar.
> - Diffusion 6m-ann > 3% só é publicada para Headline (bate `build_diffusion_cpius.py`); Goods/Services não têm essa métrica.

### Alt measures — 1-mo annualized (%)

Núcleos alternativos de inflação, taxa anualizada do mês. Family Atlanta Sticky/Flex (1967+), Cleveland Median/Trimmed (1983+), Trimmed Sym 25% custom.

| Série | 2025-10 | 2025-11 | 2025-12 | 2026-01 | 2026-02 | 2026-03 | 2026-04 | 2026-05 | 2026-06 | 2026-07 | 2026-08 | 2026-09 |
|:---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Median (Cleveland) | 1.40 | 1.40 | 3.13 | 2.35 | 2.06 | 2.31 | 4.93 | 3.66 | 2.11 | 3.11 | 2.10 | 2.81 |
| Trimmed Mean 16% (Cleveland) | 1.79 | 1.80 | 3.60 | 2.34 | 2.82 | 2.26 | 5.23 | 3.18 | 0.13 | 2.71 | 2.67 | 3.53 |
| Trimmed Sym 25% (custom) | n/a | 3.74 | 4.02 | 2.56 | 2.92 | 2.59 | 5.01 | 3.47 | 1.84 | 2.91 | 2.00 | 3.70 |
| Sticky-Price (Atlanta) | 1.40 | 1.40 | 3.45 | 4.37 | 2.50 | 2.44 | 4.62 | 2.90 | 0.81 | 3.49 | 3.09 | 3.40 |
| Core Sticky-Price (Atlanta) | 1.27 | 1.27 | 3.06 | 4.61 | 2.41 | 2.39 | 4.78 | 2.87 | 0.67 | 3.48 | 3.11 | 3.49 |
| Sticky-Price ex Shelter (Atlanta) | 1.07 | 1.07 | 3.09 | 5.84 | 2.54 | 1.74 | 2.95 | 2.10 | -0.76 | 3.81 | 3.87 | 2.91 |
| Core Sticky-Price ex Shelter (Atlanta) | 0.74 | 0.74 | 2.18 | 6.60 | 2.36 | 1.51 | 2.97 | 1.89 | -1.35 | 3.85 | 4.06 | 3.00 |
| Flexible-Price (Atlanta) | 2.11 | 1.72 | 3.95 | -4.52 | 5.67 | 36.61 | 17.65 | 14.13 | -19.33 | -6.00 | 10.17 | 22.22 |
| Core Flexible-Price (Atlanta) | 0.76 | -0.11 | 1.22 | -2.14 | 4.65 | 2.66 | 4.38 | 0.10 | -5.01 | -2.25 | 6.36 | 7.91 |

### Alt measures — proxy MoM SA (%)

Variação mensal SA derivada do 1-mo annualized: `mom_sa = (1 + ann_1mo/100)^(1/12) - 1`. Mesma unidade dos MoM SA do dash CPI principal (comparação direta com all_items/core).

| Série | 2025-10 | 2025-11 | 2025-12 | 2026-01 | 2026-02 | 2026-03 | 2026-04 | 2026-05 | 2026-06 | 2026-07 | 2026-08 | 2026-09 |
|:---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Median (Cleveland) | 0.12 | 0.12 | 0.26 | 0.19 | 0.17 | 0.19 | 0.40 | 0.30 | 0.17 | 0.26 | 0.17 | 0.23 |
| Trimmed Mean 16% (Cleveland) | 0.15 | 0.15 | 0.30 | 0.19 | 0.23 | 0.19 | 0.43 | 0.26 | 0.01 | 0.22 | 0.22 | 0.29 |
| Trimmed Sym 25% (custom) | n/a | 0.31 | 0.33 | 0.21 | 0.24 | 0.21 | 0.41 | 0.28 | 0.15 | 0.24 | 0.16 | 0.30 |
| Sticky-Price (Atlanta) | 0.12 | 0.12 | 0.28 | 0.36 | 0.21 | 0.20 | 0.38 | 0.24 | 0.07 | 0.29 | 0.25 | 0.28 |
| Core Sticky-Price (Atlanta) | 0.11 | 0.11 | 0.25 | 0.38 | 0.20 | 0.20 | 0.39 | 0.24 | 0.06 | 0.29 | 0.26 | 0.29 |
| Sticky-Price ex Shelter (Atlanta) | 0.09 | 0.09 | 0.25 | 0.47 | 0.21 | 0.14 | 0.24 | 0.17 | -0.06 | 0.31 | 0.32 | 0.24 |
| Core Sticky-Price ex Shelter (Atlanta) | 0.06 | 0.06 | 0.18 | 0.53 | 0.19 | 0.13 | 0.24 | 0.16 | -0.11 | 0.32 | 0.33 | 0.25 |
| Flexible-Price (Atlanta) | 0.17 | 0.14 | 0.32 | -0.38 | 0.46 | 2.63 | 1.36 | 1.11 | -1.77 | -0.51 | 0.81 | 1.69 |
| Core Flexible-Price (Atlanta) | 0.06 | -0.01 | 0.10 | -0.18 | 0.38 | 0.22 | 0.36 | 0.01 | -0.43 | -0.19 | 0.52 | 0.64 |

### Alt measures — YoY (%)

Mesmas 9 séries, variação 12 meses.

| Série | 2025-10 | 2025-11 | 2025-12 | 2026-01 | 2026-02 | 2026-03 | 2026-04 | 2026-05 | 2026-06 | 2026-07 | 2026-08 | 2026-09 |
|:---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Median (Cleveland) | 3.28 | 3.10 | 3.10 | 2.97 | 2.85 | 2.72 | 2.80 | 2.85 | 2.71 | 2.69 | 2.58 | 2.61 |
| Trimmed Mean 16% (Cleveland) | 2.99 | 2.86 | 2.91 | 2.72 | 2.67 | 2.64 | 2.83 | 2.91 | 2.63 | 2.60 | 2.57 | 2.66 |
| Trimmed Sym 25% (custom) | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a |
| Sticky-Price (Atlanta) | 3.11 | 3.00 | 3.08 | 3.05 | 2.97 | 2.98 | 3.07 | 3.12 | 2.84 | 2.76 | 2.74 | 2.82 |
| Core Sticky-Price (Atlanta) | 3.08 | 2.95 | 3.01 | 2.98 | 2.90 | 2.93 | 3.04 | 3.09 | 2.81 | 2.72 | 2.70 | 2.78 |
| Sticky-Price ex Shelter (Atlanta) | 2.82 | 2.71 | 2.87 | 2.90 | 2.84 | 2.94 | 2.92 | 2.98 | 2.53 | 2.40 | 2.49 | 2.51 |
| Core Sticky-Price ex Shelter (Atlanta) | 2.70 | 2.56 | 2.67 | 2.72 | 2.68 | 2.81 | 2.82 | 2.89 | 2.40 | 2.23 | 2.36 | 2.36 |
| Flexible-Price (Atlanta) | 2.30 | 1.99 | 1.56 | 0.67 | 0.99 | 3.99 | 5.62 | 6.99 | 5.06 | 4.68 | 4.94 | 6.12 |
| Core Flexible-Price (Atlanta) | 1.40 | 0.70 | 0.66 | 0.11 | 0.19 | 0.82 | 1.16 | 1.39 | 1.26 | 1.09 | 1.09 | 1.48 |

### Inflation breadth — share do peso por bin YoY (%)

Cross-section de 177 subitens leaves CPI-U, agrupados em 3 bins de YoY e ponderados pelo peso RI Dez do ano anterior. Soma dos 3 bins = 100 em cada mês.

| Série | 2025-10 | 2025-11 | 2025-12 | 2026-01 | 2026-02 | 2026-03 | 2026-04 | 2026-05 | 2026-06 | 2026-07 | 2026-08 | 2026-09 |
|:---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| YoY < 0% | n/a | 11.39 | 12.53 | 14.62 | 15.90 | 12.65 | 11.21 | 14.52 | 14.51 | 14.63 | 13.22 | 14.44 |
| 0% ≤ YoY ≤ 3% | n/a | 25.51 | 23.45 | 21.61 | 26.95 | 28.00 | 19.01 | 16.14 | 16.24 | 17.59 | 17.52 | 14.12 |
| YoY > 3% | n/a | 63.10 | 64.01 | 63.77 | 57.15 | 59.35 | 69.78 | 69.34 | 69.25 | 67.78 | 69.25 | 71.44 |

### Diffusion — share de itens com YoY > 3% (%)

Difusão item-level ponderada. Fração do peso agregado em subitens com YoY acima de 3%, por bloco. Headline = todos os itens; Goods, Services, Goods ex cars são subsets.

| Série | 2025-10 | 2025-11 | 2025-12 | 2026-01 | 2026-02 | 2026-03 | 2026-04 | 2026-05 | 2026-06 | 2026-07 | 2026-08 | 2026-09 |
|:---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Headline (todos itens) | n/a | 37.50 | 43.27 | 54.12 | 56.47 | 54.12 | 54.07 | 54.91 | 53.76 | 49.71 | 50.29 | 54.34 |
| Goods | n/a | 28.33 | 32.50 | 45.38 | 52.10 | 49.17 | 47.90 | 50.00 | 46.67 | 42.50 | 44.17 | 45.83 |
| Goods ex cars | n/a | 28.45 | 32.76 | 46.09 | 53.91 | 50.00 | 47.83 | 50.86 | 48.28 | 43.10 | 44.83 | 46.55 |
| Services | n/a | 60.42 | 68.63 | 74.51 | 66.67 | 66.00 | 67.92 | 66.04 | 69.81 | 66.04 | 64.15 | 73.58 |

### Diffusion — share de itens com 6m-ann > 3% (%)

Mesma difusão mas usando variação 6 meses anualizada (sinal mais tempestivo que YoY).

| Série | 2025-10 | 2025-11 | 2025-12 | 2026-01 | 2026-02 | 2026-03 | 2026-04 | 2026-05 | 2026-06 | 2026-07 | 2026-08 | 2026-09 |
|:---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Headline (todos itens) | n/a | 43.45 | 44.44 | 52.94 | 61.76 | 58.24 | 51.74 | 60.69 | 57.23 | 49.71 | 43.35 | 44.51 |
