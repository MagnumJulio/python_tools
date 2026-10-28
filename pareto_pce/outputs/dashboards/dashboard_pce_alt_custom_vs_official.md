# PCE alt measures — custom bottom-up vs oficial (Cleveland/Dallas)

**Last date**: 2026-08. Fonte: `pce_alt_measures.csv` (official) + `pce_alt_measures_custom.csv` (bottom-up Itau).

Pedido 2026-10-28: ter os 2 lado-a-lado no SQL pra decomposição e sensibilidade — **não substitui o oficial**. O custom permite:
- Perguntar "se eu mudasse o universo / o trim, o que aconteceria?"
- Decompor quais itens explicam o gap com o oficial
- Entender a sensibilidade da métrica a mudanças metodológicas

**Metodologia custom** (bottom-up em cima dos 190 leaves U20404 + U20405):
- **Median**: weighted 50th percentile de MoM SAAR (peso = nominais U20405 do mês)
- **Trimmed Mean**: trim **24% low + 31% high** (asimétrico Dallas, calibrado pra bater headline no long run)
- Chain universal pra value_index (idx[t] = idx[t-1]·(1+mom[t])), rebase Jan/2000=100

**Threshold mental**:
- `mean|d_yoy|` < 0.3pp → bom, custom é tool de análise confiável
- `mean|d_yoy|` < 0.5pp → aceitável, mas custom diverge o suficiente pra ser citado como "estimativa Itaú"
- `mean|d_yoy|` > 1pp → vira só análise interna, não deliverable

### Chain fidelity custom vs oficial — stats globais

YoY: ambas rebase Jan/2000=100 por construção. Index diff relativo (%) mede desvio acumulado da reconstrução.

| Pair | n_overlap | mean|d_yoy| (pp) | max|d_yoy| (pp) | corr_yoy | mean|d_idx| (%) | corr_idx |
|:---|---:|---:|---:|---:|---:|---:|
| Median PCE | 307.000 | 0.106 | 0.548 | 0.993 | 0.571 | 1.000 |
| Trimmed Mean PCE | 307.000 | 0.090 | 0.343 | 0.990 | 0.361 | 1.000 |

### YoY last 24m — side-by-side custom vs official

Cada par (Measure × Pipeline) aparece como linha separada pra comparação visual direta.

| Serie (YoY %) | 2024-09 | 2024-10 | 2024-11 | 2024-12 | 2025-01 | 2025-02 | 2025-03 | 2025-04 | 2025-05 | 2025-06 | 2025-07 | 2025-08 | 2025-09 | 2025-10 | 2025-11 | 2025-12 | 2026-01 | 2026-02 | 2026-03 | 2026-04 | 2026-05 | 2026-06 | 2026-07 | 2026-08 |
|:---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Median PCE — official | 3.38 | 3.42 | 3.35 | 3.53 | 3.30 | 3.35 | 3.35 | 3.35 | 3.28 | 3.39 | 3.46 | 3.51 | 3.38 | 3.21 | 3.10 | 3.06 | 2.98 | 2.91 | 2.86 | 2.82 | 2.87 | 2.71 | 2.70 | 2.57 |
| Median PCE — custom | 3.18 | 3.13 | 3.11 | 3.26 | 3.08 | 3.16 | 3.15 | 3.20 | 3.15 | 3.26 | 3.23 | 3.31 | 3.17 | 3.09 | 2.98 | 2.96 | 2.87 | 2.80 | 2.78 | 2.64 | 2.69 | 2.53 | 2.63 | 2.53 |
| Trimmed Mean PCE — official | 2.88 | 2.93 | 2.94 | 3.03 | 2.80 | 2.78 | 2.73 | 2.76 | 2.72 | 2.80 | 2.79 | 2.85 | 2.76 | 2.60 | 2.52 | 2.47 | 2.45 | 2.38 | 2.36 | 2.38 | 2.44 | 2.28 | 2.28 | 2.19 |
| Trimmed Mean PCE — custom | 2.69 | 2.67 | 2.69 | 2.78 | 2.56 | 2.56 | 2.51 | 2.57 | 2.55 | 2.66 | 2.65 | 2.71 | 2.62 | 2.48 | 2.38 | 2.33 | 2.32 | 2.26 | 2.26 | 2.21 | 2.25 | 2.07 | 2.11 | 2.03 |

### YoY diff last 24m (custom − official, em pp)

Valores próximos de 0 = reconstrução perfeita. Positivo = nosso está acima do oficial.

| Pair (diff YoY %, custom − official) | 2024-09 | 2024-10 | 2024-11 | 2024-12 | 2025-01 | 2025-02 | 2025-03 | 2025-04 | 2025-05 | 2025-06 | 2025-07 | 2025-08 | 2025-09 | 2025-10 | 2025-11 | 2025-12 | 2026-01 | 2026-02 | 2026-03 | 2026-04 | 2026-05 | 2026-06 | 2026-07 | 2026-08 |
|:---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Median PCE | -0.197 | -0.292 | -0.246 | -0.265 | -0.229 | -0.193 | -0.202 | -0.153 | -0.127 | -0.127 | -0.231 | -0.205 | -0.205 | -0.118 | -0.119 | -0.100 | -0.113 | -0.112 | -0.079 | -0.179 | -0.181 | -0.182 | -0.079 | -0.039 |
| Trimmed Mean PCE | -0.190 | -0.256 | -0.246 | -0.246 | -0.243 | -0.222 | -0.222 | -0.192 | -0.171 | -0.138 | -0.143 | -0.137 | -0.143 | -0.124 | -0.142 | -0.143 | -0.125 | -0.123 | -0.097 | -0.174 | -0.192 | -0.206 | -0.175 | -0.155 |

### YoY médio por regime macro — custom vs oficial

Média do YoY em cada regime macro. Mostra se a divergência varia por contexto (ex.: custom pode subestimar em COVID se nominais trimestrais atrasam, ou se trim/median comportam diferente em cauda larga).

| Regime | Median PCE off | Median PCE cst | Trimmed Mean PCE off | Trimmed Mean PCE cst |
|:---|---:|---:|---:|---:|
| Pre-COVID (2001-2019) | 2.317 | 2.272 | 1.941 | 1.954 |
| COVID (2020-2021) | 2.408 | 2.388 | 2.028 | 2.000 |
| Pos-COVID (2022-atual) | 4.041 | 3.830 | 3.383 | 3.248 |
| Ultimo ano (12m) | 2.931 | 2.805 | 2.426 | 2.276 |
