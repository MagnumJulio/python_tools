# PCE categorias — validação vs Haver Analytics (ground truth)

**Last date**: 2026-09. Fonte: `pce_categorias_indice.csv` + `pce_categorias_pesos.csv` (bottom-up do BEA U20404+U20405 via `build_pce_categorias.py`).

Validação direto contra a tabela Haver que o usuário usa como referência. 33 categorias cobertas:
- **24 directs** — line_number do BEA U20404 (ex: `Services`=150, `Core PCE`=374)
- **4 customs** — álgebra Laspeyres via `bea_maps/pce_categorias.csv`
  (`Services ex Energy and Housing`, `Services ex Energy Airfare Healthcare`, `Services ex Energy Housing PubTrans Medical`, `PCE ex Food Energy Housing`)
- **5 outros** — `Food`, `Energy`, `Market-based PCE`, `Market-based PCE ex food energy`, `Household Consumption Expenditures (Services)`

Threshold mental: `max|d| < 0.02pp` em qualquer mês = **conta perfeita**. Diffs maiores indicam arredondamento na tabela Haver ou drift metodológico (improvável).

### Weight (último mês vs Haver)

Weight = share do nominal mensal U20405 vs headline. Para custom aggregates é a weight derivada da álgebra. All_items é sintético 100.0 fixo.

| Categoria | Nosso | Haver | Diff (pp) |
|:---|---:|---:|---:|
| Headline PCE | 100.00 | 100.00 | 0.00 |
| Core PCE | 88.88 | 88.88 | 0.00 |
| Goods | 31.08 | 31.08 | 0.00 |
| Core Goods | 21.64 | 21.64 | 0.00 |
| Durable Goods | 10.79 | 10.79 | 0.00 |
| Motor Vehicles & Parts | 3.54 | 3.54 | 0.00 |
| Furnishings & Durable Household Equipment | 2.39 | 2.39 | 0.00 |
| Recreational Goods & Vehicles | 3.41 | 3.41 | 0.00 |
| Other Durable Goods | 1.44 | 1.44 | 0.00 |
| Nondurable Goods | 20.29 | 20.29 | 0.00 |
| Food & Beverages Purchased for Off-Premises | 7.00 | 7.00 | 0.00 |
| Clothing & Footwear | 2.71 | 2.71 | 0.00 |
| Gasoline & Other Energy Goods | 2.44 | 2.44 | 0.00 |
| Other Nondurable Goods | 8.14 | 8.14 | 0.00 |
| Services | 68.92 | 68.92 | 0.00 |
| Services ex Energy | 67.24 | 67.24 | 0.00 |
| Services ex Energy and Housing | 51.63 | 51.63 | 0.00 |
| Services ex Energy, Airfare and Healthcare | 48.94 | 48.94 | 0.00 |
| Services ex Energy, Housing, Public Transportation and Medical Services | 30.88 | 30.88 | 0.00 |
| Housing | 15.61 | 15.61 | 0.00 |
| Household Consumption Expenditures (Services) | 65.96 | 65.96 | 0.00 |
| Housing & Utilities | 17.94 | 17.94 | 0.00 |
| Health Care | 17.24 | 17.24 | 0.00 |
| Transportation Services | 3.51 | 3.51 | 0.00 |
| Recreation Services | 3.82 | 3.82 | 0.00 |
| Food Services & Accommodations | 7.17 | 7.17 | 0.00 |
| Financial Services & Insurance | 8.05 | 8.05 | 0.00 |
| Other Services | 8.22 | 8.21 | 0.01 |
| PCE excluding Food Energy & Housing | 73.28 | 73.28 | 0.00 |
| Food | 7.00 | 7.00 | 0.00 |
| Energy | 4.12 | 4.12 | 0.00 |
| Market-based PCE | 86.37 | 86.36 | 0.01 |
| Market-based PCE excluding food and energy | 75.25 | 75.25 | 0.00 |

### Chain fidelity — max|d| MoM (12m overlap Oct/25-Sep/26)

max|d| por categoria sobre os 12 meses. Valores < 0.02pp = diff só de arredondamento da tabela Haver (2 decimais).

| Categoria | max|d| (pp) | mean|d| (pp) |
|:---|---:|---:|
| PCE excluding Food Energy & Housing | 0.0485 | 0.0103 |
| Services ex Energy, Housing, Public Transportation and Medical Services | 0.0062 | 0.0023 |
| Household Consumption Expenditures (Services) | 0.0050 | 0.0018 |
| Services ex Energy and Housing | 0.0050 | 0.0027 |
| Recreational Goods & Vehicles | 0.0050 | 0.0024 |
| Housing & Utilities | 0.0050 | 0.0027 |
| Other Durable Goods | 0.0049 | 0.0023 |
| Services ex Energy | 0.0049 | 0.0028 |
| Gasoline & Other Energy Goods | 0.0049 | 0.0025 |
| Services | 0.0049 | 0.0026 |
| Health Care | 0.0049 | 0.0026 |
| Motor Vehicles & Parts | 0.0049 | 0.0026 |
| Housing | 0.0048 | 0.0026 |
| Core Goods | 0.0048 | 0.0028 |
| Energy | 0.0048 | 0.0028 |
| Core PCE | 0.0047 | 0.0032 |
| Transportation Services | 0.0047 | 0.0031 |
| Durable Goods | 0.0046 | 0.0022 |
| Nondurable Goods | 0.0046 | 0.0028 |
| Goods | 0.0046 | 0.0022 |
| Recreation Services | 0.0046 | 0.0029 |
| Headline PCE | 0.0046 | 0.0023 |
| Clothing & Footwear | 0.0045 | 0.0023 |
| Market-based PCE | 0.0045 | 0.0028 |
| Furnishings & Durable Household Equipment | 0.0045 | 0.0020 |
| Other Services | 0.0045 | 0.0027 |
| Market-based PCE excluding food and energy | 0.0044 | 0.0026 |
| Financial Services & Insurance | 0.0043 | 0.0015 |
| Food Services & Accommodations | 0.0042 | 0.0020 |
| Other Nondurable Goods | 0.0042 | 0.0024 |
| Food & Beverages Purchased for Off-Premises | 0.0041 | 0.0020 |
| Food | 0.0041 | 0.0020 |
| Services ex Energy, Airfare and Healthcare | 0.0041 | 0.0025 |

### MoM SA % — nossos valores (bottom-up BEA)

Derivado de `pce_categorias_indice.csv`: `(idx[t]/idx[t-1] − 1) × 100`.

| Categoria (diff pp, nosso − Haver) | 2025-10 | 2025-11 | 2025-12 | 2026-01 | 2026-02 | 2026-03 | 2026-04 | 2026-05 | 2026-06 | 2026-07 | 2026-08 | 2026-09 |
|:---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Headline PCE | 0.15 | 0.20 | 0.32 | 0.30 | 0.35 | 0.63 | 0.44 | 0.44 | -0.10 | 0.06 | 0.32 | 0.49 |
| Core PCE | 0.18 | 0.16 | 0.32 | 0.40 | 0.34 | 0.26 | 0.28 | 0.31 | 0.13 | 0.14 | 0.26 | 0.32 |
| Goods | -0.08 | 0.12 | 0.33 | 0.04 | 0.60 | 1.38 | 0.63 | 0.46 | -0.65 | -0.10 | 0.35 | 0.80 |
| Core Goods | -0.01 | -0.05 | 0.36 | 0.29 | 0.65 | 0.16 | 0.19 | -0.05 | 0.03 | 0.16 | 0.05 | 0.20 |
| Durable Goods | 0.06 | -0.03 | 0.39 | 0.38 | 0.65 | 0.31 | 0.34 | 0.09 | -0.10 | 0.40 | 0.13 | 0.24 |
| Motor Vehicles & Parts | 0.19 | 0.08 | -0.25 | -0.69 | 0.22 | -0.08 | -0.09 | -0.19 | 0.05 | 0.41 | -0.02 | 0.26 |
| Furnishings & Durable Household Equipment | 0.00 | 0.00 | 0.79 | 0.89 | 0.30 | -0.50 | -0.13 | -0.43 | 0.14 | -0.90 | 0.03 | -0.01 |
| Recreational Goods & Vehicles | -0.27 | -0.45 | 1.31 | 1.49 | 1.03 | 1.19 | 0.85 | 0.43 | 0.52 | 1.25 | 0.54 | 0.18 |
| Other Durable Goods | 0.60 | 0.59 | -0.80 | -0.38 | 1.43 | 0.61 | 1.02 | 0.83 | -2.30 | 0.56 | -0.28 | 0.72 |
| Nondurable Goods | -0.15 | 0.20 | 0.30 | -0.14 | 0.58 | 1.96 | 0.79 | 0.66 | -0.94 | -0.36 | 0.47 | 1.11 |
| Food & Beverages Purchased for Off-Premises | -0.01 | -0.01 | 0.41 | 0.23 | 0.27 | -0.14 | 0.49 | 0.06 | 0.25 | -0.08 | 0.03 | -0.02 |
| Clothing & Footwear | -0.33 | -0.33 | 0.49 | 0.40 | 1.05 | 1.04 | 0.40 | 0.04 | -0.17 | -0.12 | 0.16 | 0.16 |
| Gasoline & Other Energy Goods | -1.08 | 2.53 | -0.32 | -3.37 | 1.37 | 20.92 | 5.49 | 6.47 | -9.24 | -2.68 | 4.36 | 9.24 |
| Other Nondurable Goods | 0.00 | 0.01 | 0.28 | 0.13 | 0.50 | -0.33 | -0.10 | -0.25 | 0.27 | -0.06 | -0.09 | 0.16 |
| Services | 0.25 | 0.24 | 0.32 | 0.42 | 0.23 | 0.29 | 0.35 | 0.42 | 0.14 | 0.13 | 0.31 | 0.35 |
| Services ex Energy | 0.24 | 0.22 | 0.30 | 0.43 | 0.24 | 0.29 | 0.31 | 0.42 | 0.17 | 0.13 | 0.33 | 0.36 |
| Services ex Energy and Housing | 0.27 | 0.25 | 0.30 | 0.49 | 0.25 | 0.29 | 0.25 | 0.46 | 0.15 | 0.09 | 0.37 | 0.37 |
| Services ex Energy, Airfare and Healthcare | 0.15 | 0.21 | 0.40 | 0.35 | 0.22 | 0.24 | 0.35 | 0.41 | 0.11 | 0.11 | 0.39 | 0.34 |
| Services ex Energy, Housing, Public Transportation and Medical Services | 0.14 | 0.24 | 0.50 | 0.42 | 0.20 | 0.16 | 0.31 | 0.51 | -0.00 | 0.03 | 0.46 | 0.29 |
| Housing | 0.14 | 0.14 | 0.30 | 0.23 | 0.20 | 0.26 | 0.53 | 0.31 | 0.22 | 0.26 | 0.19 | 0.32 |
| Household Consumption Expenditures (Services) | 0.28 | 0.26 | 0.33 | 0.40 | 0.24 | 0.32 | 0.33 | 0.41 | 0.20 | 0.13 | 0.31 | 0.37 |
| Housing & Utilities | 0.20 | 0.21 | 0.36 | 0.23 | 0.21 | 0.29 | 0.63 | 0.31 | 0.14 | 0.26 | 0.14 | 0.30 |
| Health Care | 0.46 | 0.25 | 0.01 | 0.57 | 0.20 | 0.35 | 0.12 | 0.29 | 0.34 | 0.18 | 0.08 | 0.14 |
| Transportation Services | 0.40 | 0.26 | -0.03 | 0.81 | 0.90 | 1.29 | 0.36 | 0.88 | 0.58 | 0.19 | 1.09 | 2.14 |
| Recreation Services | 0.02 | -0.04 | 2.33 | 0.42 | -0.50 | 0.25 | 0.33 | 0.20 | -0.14 | -0.04 | -0.05 | 0.39 |
| Food Services & Accommodations | 0.13 | 0.13 | 0.87 | 0.10 | 0.35 | 0.24 | 0.54 | 0.30 | -0.08 | -0.07 | 0.48 | 0.43 |
| Financial Services & Insurance | 0.34 | 0.49 | 0.40 | 0.55 | 0.12 | 0.33 | 0.46 | 0.58 | 0.32 | 0.06 | 0.28 | 0.39 |
| Other Services | 0.23 | 0.41 | -0.36 | 0.33 | 0.49 | 0.04 | -0.18 | 0.71 | 0.16 | 0.03 | 0.86 | 0.17 |
| PCE excluding Food Energy & Housing | 0.18 | 0.16 | 0.32 | 0.43 | 0.37 | 0.20 | 0.22 | 0.30 | 0.10 | 0.11 | 0.27 | 0.30 |
| Food | -0.01 | -0.01 | 0.41 | 0.23 | 0.27 | -0.14 | 0.49 | 0.06 | 0.25 | -0.08 | 0.03 | -0.02 |
| Energy | -0.24 | 1.72 | 0.23 | -1.78 | 0.77 | 11.51 | 3.86 | 3.95 | -5.84 | -1.41 | 2.30 | 5.36 |
| Market-based PCE | 0.16 | 0.19 | 0.33 | 0.26 | 0.38 | 0.71 | 0.45 | 0.40 | -0.11 | 0.05 | 0.32 | 0.54 |
| Market-based PCE excluding food and energy | 0.19 | 0.13 | 0.33 | 0.36 | 0.37 | 0.28 | 0.27 | 0.25 | 0.17 | 0.14 | 0.24 | 0.34 |

### MoM SA % — Haver reference

Tabela que o usuário usa como ground truth (Haver Analytics).

| Categoria (Haver MoM %) | 2025-10 | 2025-11 | 2025-12 | 2026-01 | 2026-02 | 2026-03 | 2026-04 | 2026-05 | 2026-06 | 2026-07 | 2026-08 | 2026-09 |
|:---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Headline PCE | 0.15 | 0.20 | 0.32 | 0.30 | 0.35 | 0.63 | 0.44 | 0.44 | -0.10 | 0.06 | 0.32 | 0.49 |
| Core PCE | 0.18 | 0.16 | 0.32 | 0.40 | 0.34 | 0.26 | 0.28 | 0.31 | 0.13 | 0.14 | 0.26 | 0.32 |
| Goods | -0.08 | 0.12 | 0.33 | 0.04 | 0.60 | 1.38 | 0.63 | 0.46 | -0.65 | -0.10 | 0.35 | 0.80 |
| Core Goods | -0.01 | -0.05 | 0.36 | 0.29 | 0.65 | 0.16 | 0.19 | -0.05 | 0.03 | 0.16 | 0.05 | 0.20 |
| Durable Goods | 0.06 | -0.03 | 0.39 | 0.38 | 0.65 | 0.31 | 0.34 | 0.09 | -0.10 | 0.40 | 0.13 | 0.24 |
| Motor Vehicles & Parts | 0.19 | 0.08 | -0.25 | -0.69 | 0.22 | -0.08 | -0.09 | -0.19 | 0.05 | 0.41 | -0.02 | 0.26 |
| Furnishings & Durable Household Equipment | 0.00 | 0.00 | 0.79 | 0.89 | 0.30 | -0.50 | -0.13 | -0.43 | 0.14 | -0.90 | 0.03 | -0.01 |
| Recreational Goods & Vehicles | -0.27 | -0.45 | 1.31 | 1.49 | 1.03 | 1.19 | 0.85 | 0.43 | 0.52 | 1.25 | 0.54 | 0.18 |
| Other Durable Goods | 0.60 | 0.59 | -0.80 | -0.38 | 1.43 | 0.61 | 1.02 | 0.83 | -2.30 | 0.56 | -0.28 | 0.72 |
| Nondurable Goods | -0.15 | 0.20 | 0.30 | -0.14 | 0.58 | 1.96 | 0.79 | 0.66 | -0.94 | -0.36 | 0.47 | 1.11 |
| Food & Beverages Purchased for Off-Premises | -0.01 | -0.01 | 0.41 | 0.23 | 0.27 | -0.14 | 0.49 | 0.06 | 0.25 | -0.08 | 0.03 | -0.02 |
| Clothing & Footwear | -0.33 | -0.33 | 0.49 | 0.40 | 1.05 | 1.04 | 0.40 | 0.04 | -0.17 | -0.12 | 0.16 | 0.16 |
| Gasoline & Other Energy Goods | -1.08 | 2.53 | -0.32 | -3.37 | 1.37 | 20.92 | 5.49 | 6.47 | -9.24 | -2.68 | 4.36 | 9.24 |
| Other Nondurable Goods | 0.00 | 0.01 | 0.28 | 0.13 | 0.50 | -0.33 | -0.10 | -0.25 | 0.27 | -0.06 | -0.09 | 0.16 |
| Services | 0.25 | 0.24 | 0.32 | 0.42 | 0.23 | 0.29 | 0.35 | 0.42 | 0.14 | 0.13 | 0.31 | 0.35 |
| Services ex Energy | 0.24 | 0.22 | 0.30 | 0.43 | 0.24 | 0.29 | 0.31 | 0.42 | 0.17 | 0.13 | 0.33 | 0.36 |
| Services ex Energy and Housing | 0.27 | 0.25 | 0.30 | 0.49 | 0.25 | 0.29 | 0.25 | 0.46 | 0.15 | 0.09 | 0.37 | 0.37 |
| Services ex Energy, Airfare and Healthcare | 0.15 | 0.21 | 0.40 | 0.35 | 0.22 | 0.24 | 0.35 | 0.41 | 0.11 | 0.11 | 0.39 | 0.34 |
| Services ex Energy, Housing, Public Transportation and Medical Services | 0.14 | 0.24 | 0.50 | 0.42 | 0.20 | 0.15 | 0.31 | 0.51 | -0.00 | 0.03 | 0.46 | 0.29 |
| Housing | 0.14 | 0.14 | 0.30 | 0.23 | 0.20 | 0.26 | 0.53 | 0.31 | 0.22 | 0.26 | 0.19 | 0.32 |
| Household Consumption Expenditures (Services) | 0.28 | 0.26 | 0.33 | 0.40 | 0.24 | 0.32 | 0.33 | 0.41 | 0.20 | 0.13 | 0.31 | 0.37 |
| Housing & Utilities | 0.20 | 0.21 | 0.36 | 0.23 | 0.21 | 0.29 | 0.63 | 0.31 | 0.14 | 0.26 | 0.14 | 0.30 |
| Health Care | 0.46 | 0.25 | 0.01 | 0.57 | 0.20 | 0.35 | 0.12 | 0.29 | 0.34 | 0.18 | 0.08 | 0.14 |
| Transportation Services | 0.40 | 0.26 | -0.03 | 0.81 | 0.90 | 1.29 | 0.36 | 0.88 | 0.58 | 0.19 | 1.09 | 2.14 |
| Recreation Services | 0.02 | -0.04 | 2.33 | 0.42 | -0.50 | 0.25 | 0.33 | 0.20 | -0.14 | -0.04 | -0.05 | 0.39 |
| Food Services & Accommodations | 0.13 | 0.13 | 0.87 | 0.10 | 0.35 | 0.24 | 0.54 | 0.30 | -0.08 | -0.07 | 0.48 | 0.43 |
| Financial Services & Insurance | 0.34 | 0.49 | 0.40 | 0.55 | 0.12 | 0.33 | 0.46 | 0.58 | 0.32 | 0.06 | 0.28 | 0.39 |
| Other Services | 0.23 | 0.41 | -0.36 | 0.33 | 0.49 | 0.04 | -0.18 | 0.71 | 0.16 | 0.03 | 0.86 | 0.17 |
| PCE excluding Food Energy & Housing | 0.18 | 0.16 | 0.32 | 0.43 | 0.37 | 0.25 | 0.23 | 0.31 | 0.12 | 0.11 | 0.28 | 0.32 |
| Food | -0.01 | -0.01 | 0.41 | 0.23 | 0.27 | -0.14 | 0.49 | 0.06 | 0.25 | -0.08 | 0.03 | -0.02 |
| Energy | -0.24 | 1.72 | 0.23 | -1.78 | 0.77 | 11.51 | 3.86 | 3.95 | -5.84 | -1.41 | 2.30 | 5.36 |
| Market-based PCE | 0.16 | 0.19 | 0.33 | 0.26 | 0.38 | 0.71 | 0.45 | 0.40 | -0.11 | 0.05 | 0.32 | 0.54 |
| Market-based PCE excluding food and energy | 0.19 | 0.13 | 0.33 | 0.36 | 0.37 | 0.28 | 0.27 | 0.25 | 0.17 | 0.14 | 0.24 | 0.34 |

### MoM SA — Diff (nosso − Haver, pp)

Valores próximos de 0 = reconstrução perfeita. Até 0.01pp é esperado pelo arredondamento da tabela Haver.

| Categoria (diff pp, nosso − Haver) | 2025-10 | 2025-11 | 2025-12 | 2026-01 | 2026-02 | 2026-03 | 2026-04 | 2026-05 | 2026-06 | 2026-07 | 2026-08 | 2026-09 |
|:---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Headline PCE | -0.00 | -0.00 | 0.00 | 0.00 | -0.00 | -0.00 | -0.00 | -0.00 | -0.00 | 0.00 | 0.00 | 0.00 |
| Core PCE | -0.00 | -0.00 | -0.00 | -0.00 | -0.00 | -0.00 | 0.00 | -0.00 | 0.00 | -0.00 | 0.00 | -0.00 |
| Goods | 0.00 | -0.00 | -0.00 | -0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | -0.00 | 0.00 |
| Core Goods | 0.00 | -0.00 | -0.00 | -0.00 | -0.00 | -0.00 | -0.00 | 0.00 | 0.00 | 0.00 | 0.00 | -0.00 |
| Durable Goods | 0.00 | -0.00 | -0.00 | -0.00 | 0.00 | 0.00 | 0.00 | -0.00 | 0.00 | 0.00 | -0.00 | -0.00 |
| Motor Vehicles & Parts | 0.00 | 0.00 | -0.00 | -0.00 | 0.00 | 0.00 | -0.00 | -0.00 | -0.00 | 0.00 | -0.00 | 0.00 |
| Furnishings & Durable Household Equipment | 0.00 | 0.00 | -0.00 | -0.00 | -0.00 | -0.00 | -0.00 | 0.00 | 0.00 | 0.00 | -0.00 | 0.00 |
| Recreational Goods & Vehicles | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | -0.00 | 0.00 | -0.00 | 0.00 | -0.00 | 0.00 | 0.00 |
| Other Durable Goods | 0.00 | 0.00 | -0.00 | 0.00 | 0.00 | 0.00 | -0.00 | -0.00 | 0.00 | 0.00 | -0.00 | -0.00 |
| Nondurable Goods | -0.00 | -0.00 | -0.00 | -0.00 | -0.00 | 0.00 | -0.00 | 0.00 | -0.00 | -0.00 | -0.00 | -0.00 |
| Food & Beverages Purchased for Off-Premises | -0.00 | -0.00 | 0.00 | 0.00 | -0.00 | -0.00 | 0.00 | -0.00 | 0.00 | -0.00 | 0.00 | 0.00 |
| Clothing & Footwear | -0.00 | -0.00 | -0.00 | -0.00 | -0.00 | -0.00 | 0.00 | 0.00 | -0.00 | 0.00 | 0.00 | -0.00 |
| Gasoline & Other Energy Goods | -0.00 | -0.00 | -0.00 | 0.00 | -0.00 | -0.00 | 0.00 | 0.00 | 0.00 | -0.00 | 0.00 | 0.00 |
| Other Nondurable Goods | 0.00 | 0.00 | -0.00 | -0.00 | 0.00 | -0.00 | 0.00 | -0.00 | 0.00 | 0.00 | 0.00 | -0.00 |
| Services | 0.00 | -0.00 | -0.00 | 0.00 | 0.00 | 0.00 | -0.00 | 0.00 | 0.00 | 0.00 | 0.00 | -0.00 |
| Services ex Energy | -0.00 | 0.00 | 0.00 | 0.00 | -0.00 | -0.00 | 0.00 | 0.00 | -0.00 | -0.00 | -0.00 | -0.00 |
| Services ex Energy and Housing | -0.00 | -0.00 | 0.00 | 0.00 | -0.00 | 0.00 | -0.00 | 0.00 | -0.00 | -0.00 | 0.00 | -0.00 |
| Services ex Energy, Airfare and Healthcare | -0.00 | -0.00 | -0.00 | 0.00 | 0.00 | 0.00 | -0.00 | 0.00 | 0.00 | -0.00 | -0.00 | 0.00 |
| Services ex Energy, Housing, Public Transportation and Medical Services | 0.00 | 0.00 | 0.00 | -0.00 | 0.00 | 0.01 | -0.00 | 0.00 | -0.00 | -0.00 | -0.00 | -0.00 |
| Housing | 0.00 | 0.00 | 0.00 | -0.00 | 0.00 | 0.00 | 0.00 | -0.00 | 0.00 | -0.00 | -0.00 | 0.00 |
| Household Consumption Expenditures (Services) | 0.00 | -0.00 | 0.00 | -0.00 | -0.00 | 0.00 | 0.00 | -0.00 | -0.00 | 0.00 | -0.00 | -0.00 |
| Housing & Utilities | 0.00 | -0.00 | 0.00 | 0.00 | 0.00 | -0.00 | -0.00 | 0.00 | 0.00 | 0.00 | 0.00 | -0.00 |
| Health Care | 0.00 | 0.00 | -0.00 | -0.00 | -0.00 | -0.00 | -0.00 | -0.00 | -0.00 | 0.00 | -0.00 | 0.00 |
| Transportation Services | -0.00 | 0.00 | 0.00 | -0.00 | -0.00 | -0.00 | -0.00 | -0.00 | -0.00 | 0.00 | 0.00 | -0.00 |
| Recreation Services | -0.00 | 0.00 | -0.00 | 0.00 | -0.00 | 0.00 | 0.00 | 0.00 | -0.00 | 0.00 | 0.00 | 0.00 |
| Food Services & Accommodations | 0.00 | 0.00 | 0.00 | 0.00 | -0.00 | 0.00 | -0.00 | -0.00 | 0.00 | -0.00 | -0.00 | -0.00 |
| Financial Services & Insurance | -0.00 | 0.00 | -0.00 | 0.00 | 0.00 | -0.00 | 0.00 | 0.00 | -0.00 | 0.00 | -0.00 | 0.00 |
| Other Services | -0.00 | 0.00 | 0.00 | -0.00 | -0.00 | 0.00 | 0.00 | -0.00 | 0.00 | -0.00 | 0.00 | 0.00 |
| PCE excluding Food Energy & Housing | 0.00 | -0.00 | -0.00 | 0.00 | -0.00 | -0.05 | -0.01 | -0.01 | -0.02 | 0.00 | -0.01 | -0.02 |
| Food | -0.00 | -0.00 | 0.00 | 0.00 | -0.00 | -0.00 | 0.00 | -0.00 | 0.00 | -0.00 | 0.00 | 0.00 |
| Energy | 0.00 | -0.00 | 0.00 | 0.00 | -0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | -0.00 |
| Market-based PCE | -0.00 | -0.00 | 0.00 | 0.00 | 0.00 | -0.00 | -0.00 | 0.00 | -0.00 | 0.00 | -0.00 | -0.00 |
| Market-based PCE excluding food and energy | 0.00 | 0.00 | -0.00 | 0.00 | 0.00 | -0.00 | -0.00 | -0.00 | -0.00 | 0.00 | 0.00 | -0.00 |
