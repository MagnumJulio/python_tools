# PCE distribuição de altas — estilo Dallas Fed

**Last date**: 2026-08. **Janela**: 2000-02 → 2026-08 (319 datas). **Overlap Dallas**: 13 meses (2025-08 → 2026-08).

Fonte: `data/pce_altas_distribution.csv` (gerado por `scripts/build_altas_distribution_pce.py` em cima do BEA U20404 + U20405). 190 leaves do U20404, peso = nominais BEA do mês, bins de **MoM SAAR** (`((idx[t]/idx[t-1])^12 - 1)*100`). U20404 é SA — chain direto sem STL.

**5 bins Dallas-style sobem pro SQL** (`PCE:dist_{0_2, 2_3, 3_5, 5_10, gt_10}`). O 6º bin `zero_or_below` (deflationary) fica só no CSV; o analista deriva via `(100 - soma dos 5)` se precisar.

**Benchmark Dallas pcedata.xlsx**: dessa vez a métrica é a MESMA (MoM SAAR, 5 bins); diferença é só o universo (190 leaves U20404 vs ~178 components do Trimmed Mean Dallas). Correlação por bin alta esperada e observada.

### Distribuição de altas — últimos 24 meses (%)

Share do peso dos 190 leaves em cada bin de MoM SAAR. Soma 6 bins = 100 por coluna.

| Bin | 2024-09 | 2024-10 | 2024-11 | 2024-12 | 2025-01 | 2025-02 | 2025-03 | 2025-04 | 2025-05 | 2025-06 | 2025-07 | 2025-08 | 2025-09 | 2025-10 | 2025-11 | 2025-12 | 2026-01 | 2026-02 | 2026-03 | 2026-04 | 2026-05 | 2026-06 | 2026-07 | 2026-08 |
|:---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0-2% MoM SAAR | 8.21 | 4.51 | 10.97 | 9.49 | 24.08 | 18.28 | 12.16 | 13.38 | 24.81 | 11.95 | 27.03 | 12.59 | 33.28 | 36.06 | 32.01 | 19.89 | 15.88 | 11.45 | 11.71 | 16.07 | 14.81 | 23.46 | 19.68 | 15.09 |
| 2-3% MoM SAAR | 15.58 | 20.10 | 3.06 | 11.85 | 4.78 | 7.14 | 6.46 | 13.10 | 8.12 | 10.36 | 7.29 | 5.74 | 18.02 | 6.78 | 8.89 | 2.69 | 17.46 | 20.57 | 14.90 | 12.64 | 11.49 | 13.92 | 4.06 | 23.09 |
| 3-5% MoM SAAR | 26.65 | 11.93 | 40.01 | 41.97 | 24.42 | 29.47 | 37.52 | 27.54 | 28.33 | 20.88 | 19.08 | 34.87 | 12.27 | 13.77 | 11.85 | 23.96 | 16.97 | 11.90 | 22.73 | 6.62 | 25.92 | 7.32 | 26.31 | 6.05 |
| 5-10% MoM SAAR | 14.62 | 22.96 | 11.75 | 8.01 | 8.45 | 16.09 | 9.48 | 19.24 | 9.94 | 31.34 | 10.67 | 8.27 | 11.44 | 4.68 | 12.82 | 11.61 | 8.79 | 7.48 | 13.99 | 24.17 | 13.08 | 16.35 | 14.71 | 16.44 |
| >10% MoM SAAR | 12.37 | 15.07 | 7.42 | 5.90 | 18.84 | 9.59 | 8.91 | 7.01 | 7.13 | 9.25 | 9.31 | 11.00 | 10.39 | 13.09 | 7.79 | 14.90 | 18.38 | 18.53 | 16.13 | 12.42 | 11.69 | 8.62 | 7.26 | 12.13 |
| <= 0% (deflationary) | 22.56 | 25.43 | 26.80 | 22.79 | 19.42 | 19.42 | 25.47 | 19.73 | 21.67 | 16.21 | 26.62 | 27.53 | 14.60 | 25.63 | 26.65 | 26.94 | 22.51 | 30.06 | 20.55 | 28.08 | 23.01 | 30.32 | 27.96 | 27.20 |

### Side-by-side nosso vs Dallas (2026-08, último overlap)

Diff positivo = nosso bin tem mais peso que Dallas. Diff ~0 pra bins altos (3-5, 5-10, >10) e zero_or_below; diferença concentra em 0-2 e 2-3 por universo.

| Bin (2026-08) | Nosso (190 leaves U20404) | Dallas (Trimmed Mean universe) | Diff (pp) |
|:---|---:|---:|---:|
| 0-2% MoM SAAR | 15.09 | 12.48 | 2.61 |
| 2-3% MoM SAAR | 23.09 | 27.39 | -4.30 |
| 3-5% MoM SAAR | 6.05 | 5.44 | 0.61 |
| 5-10% MoM SAAR | 16.44 | 15.71 | 0.73 |
| >10% MoM SAAR | 12.13 | 13.18 | -1.04 |
| <= 0% (deflationary) | 27.20 | 25.81 | 1.39 |

### Médias históricas (janela overlap, 13 meses)

Média dos valores mensais na janela de overlap com Dallas.

| Bin | Nossa media (janela overlap) | Dallas media (janela overlap) | Diff (pp) |
|:---|---:|---:|---:|
| 0-2% MoM SAAR | 20.15 | 18.76 | 1.40 |
| 2-3% MoM SAAR | 12.33 | 13.66 | -1.33 |
| 3-5% MoM SAAR | 16.97 | 15.27 | 1.69 |
| 5-10% MoM SAAR | 12.60 | 14.95 | -2.35 |
| >10% MoM SAAR | 12.49 | 12.87 | -0.39 |
| <= 0% (deflationary) | 25.46 | 24.49 | 0.98 |

### Correlação histórica por bin (overlap Dallas)

Correlação de Pearson entre nossa serie e a serie Dallas pcedata.xlsx na janela de overlap. Valores altos (>0.85) confirmam que ambas medem o mesmo signal; diferença só no universo.

| Bin | Correlacao | n_overlap |
|:---|---:|---:|
| 0-2% MoM SAAR | 0.916 | 13.000 |
| 2-3% MoM SAAR | 0.897 | 13.000 |
| 3-5% MoM SAAR | 0.977 | 13.000 |
| 5-10% MoM SAAR | 0.865 | 13.000 |
| >10% MoM SAAR | 0.849 | 13.000 |
| <= 0% (deflationary) | 0.924 | 13.000 |

### Distribuição por regime macro

Média simples dos valores mensais em cada regime. Mostra reposição das 6 bins ao longo do tempo (ex.: `>10%` saiu de ~3% pré-COVID pra ~17% em 2022, caiu pra ~12% em 2025).

| Regime | 0-2% MoM SAAR | 2-3% MoM SAAR | 3-5% MoM SAAR | 5-10% MoM SAAR | >10% MoM SAAR | <= 0% (deflationary) |
|:---|---:|---:|---:|---:|---:|---:|
| Pre-COVID (2001-2019) | 19.98 | 14.56 | 19.87 | 11.78 | 7.48 | 26.33 |
| COVID (2020-2021) | 19.93 | 14.57 | 14.02 | 14.47 | 14.73 | 22.27 |
| Pos-COVID (2022-atual) | 15.92 | 8.35 | 16.83 | 22.46 | 12.92 | 23.51 |
| Ultimo ano (12m) | 20.78 | 12.88 | 15.47 | 12.96 | 12.61 | 25.29 |

### Sanity check — soma das 6 bins deve ser 100

`n_bad` = quantidade de datas com |soma−100| > 0.01.

| Série | min_sum | max_sum | mean_sum | n_datas | n_bad |
|:---|---:|---:|---:|---:|---:|
| Soma 6 bins por data | 100.0000 | 100.0000 | 100.0000 | 319.0000 | 0.0000 |

### Distribuição anual (média por ano calendário, %)

Média mensal por ano. Útil pra ver drift long-run das 6 bins.

| Ano | 0-2% MoM SAAR | 2-3% MoM SAAR | 3-5% MoM SAAR | 5-10% MoM SAAR | >10% MoM SAAR | <= 0% (deflationary) |
|:---|---:|---:|---:|---:|---:|---:|
| 2000 | 14.02 | 15.21 | 26.28 | 12.99 | 8.47 | 23.02 |
| 2001 | 10.27 | 8.38 | 29.65 | 18.47 | 6.43 | 26.80 |
| 2002 | 12.70 | 14.46 | 22.91 | 15.46 | 6.62 | 27.84 |
| 2003 | 17.65 | 13.32 | 17.80 | 13.41 | 8.75 | 29.07 |
| 2004 | 14.44 | 19.80 | 19.57 | 14.64 | 8.36 | 23.19 |
| 2005 | 16.14 | 16.20 | 19.91 | 15.78 | 8.95 | 23.02 |
| 2006 | 12.77 | 8.63 | 30.63 | 16.41 | 6.68 | 24.88 |
| 2007 | 16.72 | 13.12 | 22.85 | 15.85 | 9.86 | 21.60 |
| 2008 | 20.91 | 12.85 | 16.89 | 15.73 | 10.87 | 22.76 |
| 2009 | 22.76 | 14.66 | 12.62 | 11.15 | 8.69 | 30.12 |
| 2010 | 31.17 | 12.50 | 10.46 | 8.67 | 5.92 | 31.29 |
| 2011 | 28.06 | 15.24 | 16.70 | 11.21 | 8.90 | 19.89 |
| 2012 | 28.75 | 17.59 | 12.71 | 9.57 | 6.77 | 24.60 |
| 2013 | 22.22 | 21.54 | 17.32 | 8.66 | 4.29 | 25.97 |
| 2014 | 21.44 | 22.61 | 13.72 | 8.92 | 5.25 | 28.05 |
| 2015 | 22.80 | 13.87 | 22.49 | 6.73 | 4.76 | 29.35 |
| 2016 | 20.48 | 11.94 | 24.05 | 8.25 | 7.15 | 28.13 |
| 2017 | 22.67 | 12.14 | 20.85 | 7.19 | 7.41 | 29.74 |
| 2018 | 21.21 | 14.67 | 21.81 | 7.99 | 8.82 | 25.51 |
| 2019 | 16.46 | 13.14 | 24.66 | 9.71 | 7.56 | 28.48 |
| 2020 | 23.01 | 17.23 | 11.66 | 12.73 | 9.99 | 25.38 |
| 2021 | 16.86 | 11.92 | 16.38 | 16.22 | 19.47 | 19.15 |
| 2022 | 13.24 | 4.52 | 8.27 | 32.40 | 21.43 | 20.14 |
| 2023 | 15.89 | 6.93 | 12.82 | 30.47 | 10.15 | 23.75 |
| 2024 | 12.38 | 9.39 | 23.45 | 19.54 | 9.37 | 25.87 |
| 2025 | 22.13 | 8.28 | 23.66 | 12.84 | 10.60 | 22.49 |
| 2026 | 16.02 | 14.77 | 15.48 | 14.38 | 13.15 | 26.21 |
