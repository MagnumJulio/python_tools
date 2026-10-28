# PCE breadth — validação e visão long-run

**Last date**: 2026-08. **Janela**: 2001-01 → 2026-08 (308 datas, 924 rows).

Fonte: `data/pce_breadth.csv` (gerado por `scripts/build_breadth_pce.py` em cima do BEA U20404 + U20405). 190 leaves do U20404, peso = nominais do próprio mês, 3 bins de YoY. Soma dos 3 bins = 100% por data (sanity automático).

Esse dashboard mostra:
1. **Last 24m detalhado** — valor exato por mês × bin.
2. **Médias anuais** — anchors long-run pra identificar regime shifts.
3. **Regimes** — pre-COVID vs COVID vs pós-COVID vs último ano.
4. **Sanity** — soma dos 3 bins em cada data.
5. **Cross-check vs diffusion Headline** — breadth usa peso (nominais BEA), diffusion usa count (fração de itens). Divergência esperada; a direção deve correlacionar.

### Breadth — últimos 24 meses (%)

Share do peso agregado dos 190 leaves em cada bin YoY. Nominais BEA U20405 do próprio mês como peso. Soma = 100 por coluna.

| Bin | 2024-09 | 2024-10 | 2024-11 | 2024-12 | 2025-01 | 2025-02 | 2025-03 | 2025-04 | 2025-05 | 2025-06 | 2025-07 | 2025-08 | 2025-09 | 2025-10 | 2025-11 | 2025-12 | 2026-01 | 2026-02 | 2026-03 | 2026-04 | 2026-05 | 2026-06 | 2026-07 | 2026-08 |
|:---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| YoY < 0% | 19.17 | 19.10 | 17.40 | 18.03 | 16.24 | 18.16 | 18.82 | 15.78 | 13.13 | 13.40 | 12.48 | 14.55 | 11.30 | 13.91 | 12.22 | 9.35 | 11.76 | 12.00 | 9.70 | 10.23 | 10.04 | 11.30 | 11.48 | 11.44 |
| 0% ≤ YoY ≤ 3% | 31.87 | 30.78 | 31.80 | 34.37 | 42.42 | 38.85 | 33.75 | 36.69 | 43.99 | 35.15 | 33.51 | 32.44 | 35.21 | 35.59 | 41.47 | 42.62 | 34.96 | 37.74 | 30.23 | 28.83 | 29.87 | 27.63 | 27.33 | 27.56 |
| YoY > 3% | 48.96 | 50.11 | 50.80 | 47.60 | 41.34 | 42.99 | 47.43 | 47.53 | 42.89 | 51.46 | 54.01 | 53.00 | 53.50 | 50.50 | 46.32 | 48.03 | 53.29 | 50.26 | 60.07 | 60.93 | 60.08 | 61.08 | 61.19 | 61.00 |

### Breadth — média anual por ano calendário (%)

Média simples dos valores mensais dentro de cada ano. Útil pra ver drift de longo prazo (ex.: expansão da região >3% em 2021-2022, retração em 2023+).

| Ano | YoY < 0% | 0% ≤ YoY ≤ 3% | YoY > 3% |
|:---|---:|---:|---:|
| 2001 | 17.99 | 25.61 | 56.40 |
| 2002 | 26.62 | 31.21 | 42.17 |
| 2003 | 23.62 | 43.52 | 32.86 |
| 2004 | 16.62 | 47.80 | 35.58 |
| 2005 | 13.97 | 42.97 | 43.06 |
| 2006 | 14.39 | 35.07 | 50.54 |
| 2007 | 15.69 | 31.12 | 53.20 |
| 2008 | 14.07 | 37.81 | 48.12 |
| 2009 | 18.64 | 50.32 | 31.04 |
| 2010 | 29.31 | 46.46 | 24.23 |
| 2011 | 13.36 | 60.42 | 26.22 |
| 2012 | 12.09 | 65.73 | 22.18 |
| 2013 | 19.37 | 67.91 | 12.72 |
| 2014 | 18.66 | 65.47 | 15.87 |
| 2015 | 25.75 | 52.47 | 21.78 |
| 2016 | 22.77 | 48.21 | 29.02 |
| 2017 | 20.25 | 50.39 | 29.36 |
| 2018 | 17.63 | 50.41 | 31.96 |
| 2019 | 16.88 | 51.14 | 31.98 |
| 2020 | 19.14 | 47.46 | 33.40 |
| 2021 | 12.54 | 43.66 | 43.79 |
| 2022 | 3.97 | 22.09 | 73.95 |
| 2023 | 12.34 | 27.83 | 59.83 |
| 2024 | 18.13 | 29.46 | 52.40 |
| 2025 | 14.11 | 37.64 | 48.25 |
| 2026 | 10.99 | 30.52 | 58.49 |

### Breadth — média por regime macro (%)

4 regimes: pré-COVID (2001-2019), COVID (2020-2021), pós-COVID (2022-corrente), último ano (12m rolling). Reposicionamento das 3 bins ao longo dos regimes.

| Regime | YoY < 0% | 0% ≤ YoY ≤ 3% | YoY > 3% |
|:---|---:|---:|---:|
| Pre-COVID (2001-2019) | 18.83 | 47.58 | 33.59 |
| COVID (2020-2021) | 15.84 | 45.56 | 38.60 |
| Pos-COVID (2022-corrente) | 11.98 | 29.43 | 58.59 |
| Ultimo ano (12m) | 11.23 | 33.25 | 55.52 |

### Sanity check — soma dos 3 bins deve ser 100

Valores próximos de 100 confirmam integridade da renormalização. `n_bad` = quantidade de datas com |soma−100| > 0.01.

| Série | min_sum | max_sum | mean_sum | n_datas | n_bad (|sum-100|>0.01) |
|:---|---:|---:|---:|---:|---:|
| Soma 3 bins por data | 100.0000 | 100.0000 | 100.0000 | 308.0000 | 0.0000 |

### Cross-check — breadth above_3 vs diffusion Headline YoY>3 (%)

Métrica diferente: breadth = share do PESO (nominais BEA), diffusion = share dos ITENS (count). Divergência esperada; **correlação histórica = +0.897** (toda a janela). Último ano:

| Mes | above_3_breadth_pct | yoy_gt_3_diffusion_pct | diff_pp |
|:---|---:|---:|---:|
| 2025-08 | 53.00 | 41.05 | 11.95 |
| 2025-09 | 53.50 | 42.63 | 10.86 |
| 2025-10 | 50.50 | 40.00 | 10.50 |
| 2025-11 | 46.32 | 42.63 | 3.69 |
| 2025-12 | 48.03 | 44.74 | 3.29 |
| 2026-01 | 53.29 | 47.37 | 5.92 |
| 2026-02 | 50.26 | 51.05 | -0.79 |
| 2026-03 | 60.07 | 52.63 | 7.43 |
| 2026-04 | 60.93 | 49.47 | 11.46 |
| 2026-05 | 60.08 | 49.47 | 10.61 |
| 2026-06 | 61.08 | 49.47 | 11.60 |
| 2026-07 | 61.19 | 53.16 | 8.04 |
