# PCE dashboard — últimos 12 meses

**Alt measures last date**: 2026-08. **Diffusion last date**: 2026-08. **Breadth last date**: 2026-08 (pode defasar vs alt — depende do release BEA U20404+U20405).

Gerado por `outputs/dashboards/_make_dashboard_pce_last_12m.py` em cima de `pce_alt_measures.csv` (Cleveland CSV + Dallas FRED, scraped), `pce_alt_measures_proxy.csv` (bottom-up Itaú), `pce_diffusion.csv` e `pce_breadth.csv` (BEA U20404 + nominais U20405, 190 leaves).

> **Notas de cobertura**:
> - Alt measures scraped no SQL: 2 series `PCE:alt_{median_pce,trimmed_mean_pce}` (Index SA, rebase Jan/2000=100, sync 2026-10-28).
> - Alt measures proxy no SQL: **6 series** (2 headline + 4 Goods/Services). Headline validado 2026-10-28: mean|d| YoY = 0.09-0.11pp vs scraped. G/S sao proxy puro — Cleveland/Dallas nao publicam decomposicao.
> - Diffusion no SQL: **9 series** = 4 YoY>3% + 1 6m-ann>3% (headline) + 4 MoM>0% (adicionado 2026-10-29). MoM>0 mede impulso corrente, YoY>3 mede escala estrutural — analises diferentes.
> - Breadth no SQL: 3 series `PCE:breadth_{above_3pct,0_to_3pct,below_0pct}` (peso = nominais BEA U20405 do proprio mes; soma = 100% por data).
> - Dallas IDs renomeados em 2026-10 (`PCETRIM1M158SFRBDAL` + `PCETRIM12M159SFRBDAL`) — antigos `680SFRBDAL` retornavam 404.
> - Dallas `pcedata.xlsx` NAO e benchmark comparavel direto do breadth: Dallas mede MoM annualized sobre universe Trimmed Mean customizado (nao YoY sobre U20404). Correlacao observada ~0 em 2026-10-28.
> - Diffusion 6m-ann > 3% so e publicada pra Headline (bate `build_diffusion.py`); Goods/Services nao tem essa metrica.

### Alt measures — Index level (SA, Jan/2000=100)

Nível do índice que vai pro SQL. **4 series**: 2 scraped (Cleveland CSV + Dallas FRED) + 2 proxy (bottom-up Itaú em cima dos 190 leaves). Jan/2000=100 por construção.

| Série | 2025-09 | 2025-10 | 2025-11 | 2025-12 | 2026-01 | 2026-02 | 2026-03 | 2026-04 | 2026-05 | 2026-06 | 2026-07 | 2026-08 |
|:---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Median (Cleveland) | 195.016 | 195.329 | 195.644 | 196.173 | 196.602 | 197.040 | 197.512 | 197.984 | 198.562 | 198.861 | 199.293 | 199.672 |
| Trimmed Mean (Dallas) | 175.325 | 175.563 | 175.808 | 176.146 | 176.498 | 176.779 | 177.153 | 177.619 | 178.058 | 178.282 | 178.558 | 178.841 |
| Median (proxy bottom-up) | 191.246 | 191.554 | 191.861 | 192.380 | 192.801 | 193.231 | 193.753 | 194.120 | 194.650 | 194.941 | 195.366 | 195.737 |
| Trimmed Mean (proxy bottom-up) | 174.482 | 174.676 | 174.883 | 175.213 | 175.563 | 175.851 | 176.240 | 176.585 | 176.975 | 177.194 | 177.478 | 177.734 |

### Alt measures — 1-mo annualized (%)

Taxa anualizada do mês. Scraped vs proxy em paralelo — proximidade mês-a-mês indica se o universe/metodologia bota conta parecida.

| Série | 2025-09 | 2025-10 | 2025-11 | 2025-12 | 2026-01 | 2026-02 | 2026-03 | 2026-04 | 2026-05 | 2026-06 | 2026-07 | 2026-08 |
|:---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Median (Cleveland) | 2.12 | 1.94 | 1.95 | 3.29 | 2.66 | 2.71 | 2.91 | 2.91 | 3.56 | 1.82 | 2.64 | 2.31 |
| Trimmed Mean (Dallas) | 2.17 | 1.64 | 1.69 | 2.33 | 2.42 | 1.93 | 2.57 | 3.20 | 3.01 | 1.52 | 1.87 | 1.92 |
| Median (proxy bottom-up) | 2.12 | 1.95 | 1.94 | 3.29 | 2.66 | 2.71 | 3.29 | 2.29 | 3.32 | 1.81 | 2.65 | 2.31 |
| Trimmed Mean (proxy bottom-up) | 2.03 | 1.34 | 1.43 | 2.29 | 2.43 | 1.99 | 2.68 | 2.38 | 2.69 | 1.49 | 1.94 | 1.75 |

### Alt measures — proxy MoM SA (%)

Variação mensal SA derivada do 1-mo annualized: `mom_sa = (1+ann_1mo/100)^(1/12)-1`.

| Série | 2025-09 | 2025-10 | 2025-11 | 2025-12 | 2026-01 | 2026-02 | 2026-03 | 2026-04 | 2026-05 | 2026-06 | 2026-07 | 2026-08 |
|:---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Median (Cleveland) | 0.175 | 0.161 | 0.161 | 0.270 | 0.219 | 0.223 | 0.239 | 0.239 | 0.292 | 0.151 | 0.218 | 0.190 |
| Trimmed Mean (Dallas) | 0.179 | 0.136 | 0.140 | 0.192 | 0.199 | 0.159 | 0.212 | 0.263 | 0.247 | 0.126 | 0.155 | 0.159 |
| Median (proxy bottom-up) | 0.175 | 0.161 | 0.160 | 0.270 | 0.219 | 0.223 | 0.270 | 0.189 | 0.273 | 0.150 | 0.218 | 0.190 |
| Trimmed Mean (proxy bottom-up) | 0.167 | 0.111 | 0.119 | 0.189 | 0.200 | 0.164 | 0.221 | 0.196 | 0.221 | 0.123 | 0.161 | 0.144 |

### Alt measures — YoY (%)

Variação 12 meses. Scraped vs proxy: diffs esperados < 0.5pp mês-a-mês (mean|d| global = 0.09pp Trim Mean / 0.11pp Median — validado em `dashboard_pce_alt_proxy_vs_official.md`).

| Série | 2025-09 | 2025-10 | 2025-11 | 2025-12 | 2026-01 | 2026-02 | 2026-03 | 2026-04 | 2026-05 | 2026-06 | 2026-07 | 2026-08 |
|:---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Median (Cleveland) | 3.38 | 3.21 | 3.10 | 3.06 | 2.98 | 2.91 | 2.86 | 2.82 | 2.87 | 2.71 | 2.70 | 2.57 |
| Trimmed Mean (Dallas) | 2.76 | 2.60 | 2.52 | 2.47 | 2.45 | 2.38 | 2.36 | 2.38 | 2.44 | 2.28 | 2.28 | 2.19 |
| Median (proxy bottom-up) | 3.17 | 3.09 | 2.98 | 2.96 | 2.87 | 2.80 | 2.78 | 2.64 | 2.69 | 2.53 | 2.63 | 2.53 |
| Trimmed Mean (proxy bottom-up) | 2.62 | 2.48 | 2.38 | 2.33 | 2.32 | 2.26 | 2.26 | 2.21 | 2.25 | 2.07 | 2.11 | 2.03 |

### Alt measures proxy Goods/Services — YoY (%)

Reconstrução bottom-up aplicada só nos leaves Goods (90) ou Services (100). **Sem oficial Fed pra comparar** — Cleveland/Dallas só publicam headline. Esperado Services > Goods em YoY (sticky vs cíclico).

| Série | 2025-09 | 2025-10 | 2025-11 | 2025-12 | 2026-01 | 2026-02 | 2026-03 | 2026-04 | 2026-05 | 2026-06 | 2026-07 | 2026-08 |
|:---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Median Goods (proxy) | 1.28 | 1.21 | 1.18 | 1.27 | 1.28 | 1.41 | 1.43 | 1.37 | 1.28 | 1.00 | 1.03 | 1.01 |
| Median Services (proxy) | 3.45 | 3.28 | 3.17 | 3.13 | 3.04 | 2.96 | 2.94 | 2.79 | 2.86 | 2.79 | 2.82 | 2.67 |
| Trimmed Mean Goods (proxy) | 0.78 | 0.69 | 0.65 | 0.72 | 0.57 | 0.69 | 0.74 | 0.83 | 0.71 | 0.43 | 0.38 | 0.40 |
| Trimmed Mean Services (proxy) | 3.01 | 2.86 | 2.77 | 2.71 | 2.70 | 2.62 | 2.59 | 2.52 | 2.57 | 2.43 | 2.48 | 2.38 |

### Alt measures proxy Goods/Services — 1-mo annualized (%)

Mesma decomposição em taxa anualizada mensal.

| Série | 2025-09 | 2025-10 | 2025-11 | 2025-12 | 2026-01 | 2026-02 | 2026-03 | 2026-04 | 2026-05 | 2026-06 | 2026-07 | 2026-08 |
|:---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Median Goods (proxy) | 4.16 | -0.18 | -0.15 | 1.63 | 2.62 | 1.80 | 0.39 | 0.31 | -0.56 | 0.00 | 0.31 | 1.93 |
| Median Services (proxy) | 1.82 | 1.95 | 1.94 | 3.29 | 2.66 | 2.71 | 3.46 | 2.29 | 3.55 | 2.94 | 3.11 | 2.31 |
| Trimmed Mean Goods (proxy) | 3.91 | -1.18 | -0.66 | 0.89 | 1.62 | 1.77 | -0.51 | 1.26 | -1.03 | -0.57 | -1.28 | 0.71 |
| Trimmed Mean Services (proxy) | 1.75 | 1.86 | 1.94 | 2.76 | 2.50 | 2.27 | 3.12 | 2.86 | 3.13 | 2.00 | 2.44 | 1.90 |

### Diffusion — share de itens com YoY > 3% (%)

Difusão item-level sobre 190 leaves do BEA U20404. Fração de itens com YoY acima de 3%, por bloco. Count-based, não ponderado.

| Série | 2025-09 | 2025-10 | 2025-11 | 2025-12 | 2026-01 | 2026-02 | 2026-03 | 2026-04 | 2026-05 | 2026-06 | 2026-07 | 2026-08 |
|:---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Headline (todos itens) | 43.16 | 40.00 | 40.53 | 44.74 | 45.79 | 51.05 | 51.58 | 52.11 | 51.05 | 50.53 | 51.58 | 51.05 |
| Goods | 28.89 | 26.67 | 26.67 | 32.22 | 32.22 | 45.56 | 43.33 | 46.67 | 42.22 | 42.22 | 46.67 | 43.33 |
| Goods ex cars | 27.38 | 25.00 | 25.00 | 32.14 | 34.52 | 46.43 | 44.05 | 47.62 | 45.24 | 44.05 | 48.81 | 46.43 |
| Services | 56.00 | 52.00 | 53.00 | 56.00 | 58.00 | 56.00 | 59.00 | 57.00 | 59.00 | 58.00 | 56.00 | 58.00 |

### Diffusion — share de itens com 6m-ann > 3% (%)

Mesma difusão mas usando variação 6 meses anualizada (sinal mais tempestivo que YoY).

| Série | 2025-09 | 2025-10 | 2025-11 | 2025-12 | 2026-01 | 2026-02 | 2026-03 | 2026-04 | 2026-05 | 2026-06 | 2026-07 | 2026-08 |
|:---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Headline (todos itens) | 45.26 | 42.11 | 43.16 | 45.79 | 45.26 | 50.00 | 51.05 | 51.05 | 52.11 | 48.42 | 48.42 | 43.16 |

### Diffusion — share de itens com MoM > 0% (%)

**Impulso corrente do mês**: fração de leaves com MoM positiva vs deflationary. Threshold 0 (não 3) — mede quão **amplo** é o aumento de preço, independente de magnitude. Sinal mais tempestivo que YoY (que carrega 12m de bagagem).

| Série | 2025-09 | 2025-10 | 2025-11 | 2025-12 | 2026-01 | 2026-02 | 2026-03 | 2026-04 | 2026-05 | 2026-06 | 2026-07 | 2026-08 |
|:---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Headline (todos itens) | 70.53 | 64.74 | 62.63 | 68.42 | 67.37 | 64.21 | 63.16 | 64.21 | 61.58 | 57.89 | 64.21 | 64.74 |
| Goods | 64.44 | 51.11 | 50.00 | 58.89 | 62.22 | 58.89 | 50.00 | 61.11 | 50.00 | 51.11 | 54.44 | 61.11 |
| Goods ex cars | 64.29 | 48.81 | 47.62 | 60.71 | 64.29 | 60.71 | 50.00 | 61.90 | 51.19 | 51.19 | 51.19 | 59.52 |
| Services | 76.00 | 77.00 | 74.00 | 77.00 | 72.00 | 69.00 | 75.00 | 67.00 | 72.00 | 64.00 | 73.00 | 68.00 |

### Breadth — share do peso por bin YoY (%)

Cross-section de 190 leaves BEA U20404, agrupados em 3 bins de YoY e ponderados por nominais BEA U20405 do próprio mês. Soma dos 3 bins = 100 em cada mês. Guard de cobertura 70% descarta releases parciais.

| Série | 2025-09 | 2025-10 | 2025-11 | 2025-12 | 2026-01 | 2026-02 | 2026-03 | 2026-04 | 2026-05 | 2026-06 | 2026-07 | 2026-08 |
|:---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| YoY < 0% | 11.30 | 13.91 | 12.22 | 9.35 | 11.76 | 12.00 | 9.70 | 10.23 | 10.04 | 11.30 | 11.48 | 11.44 |
| 0% ≤ YoY ≤ 3% | 35.21 | 35.59 | 41.47 | 42.62 | 34.96 | 37.74 | 30.23 | 28.83 | 29.87 | 27.63 | 27.33 | 27.56 |
| YoY > 3% | 53.50 | 50.50 | 46.32 | 48.03 | 53.29 | 50.26 | 60.07 | 60.93 | 60.08 | 61.08 | 61.19 | 61.00 |
