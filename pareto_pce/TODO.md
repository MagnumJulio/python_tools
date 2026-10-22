# pareto_pce — TODO

## Dallas Trimmed Mean PCE — IDs FRED 404 (bloqueante alt_measures)

Em 2026-10-22, `scripts/build_alt_measures_pce.py` passou a falhar com
`404 Not Found` nos dois IDs FRED hard-coded:

- `PCETRIM1M680SFRBDAL`  → 1-mo annualized
- `PCETRIM12M680SFRBDAL` → 12-mo (YoY)

Página FRED `/series/PCETRIM1M680SFRBDAL` também retorna 404 — não é só
proxy/CDN, o ID sumiu do catálogo. Antes funcionava (CSVs antigos de
`cpi_cpius_alt_measures.csv` tinham valores). Dallas pode ter:
(a) renomeado IDs no FRED (comum em revisões de metodologia),
(b) movido pra endpoint próprio Dallas (ex: xlsx em dallasfed.org),
(c) consolidado no `PCETRIM1M158SFRBDAL`/variantes.

Impacto: Cleveland Median PCE continua OK (3 series: 1mo, mom_sa, 12mo).
Dallas sumiu — perdemos 2 das 3 measures PCE no SQL corp.

Passos pra fechar:
1. Buscar no FRED (fredaccount.stlouisfed.org/public) por "Dallas Trimmed
   Mean PCE" e capturar os IDs atuais.
2. Alternativa: baixar xlsx direto Dallas em `dallasfed.org/research/pce`
   (análogo ao Atlanta Sticky xlsx em `pareto_cpius/data/raw/atlanta/`).
3. Ajustar `fetch_fred_csv` ou criar `fetch_dallas_pce_xlsx` conforme
   a fonte escolhida.
4. Smoke test local + `--dry-run` do loader pra confirmar 5-6 series.

## Gap contagem leaves vs Itaú BBA (parcial, não crítico)

Chart de referência (Itaú BBA research, foto celular) mostra pra jul-2026:
- Goods (91 items): 47.3%
- Services (109 items): 57.8%
- Goods ex cars (85 items): 49.4%

Prototype pós-calibração (commit `183c7ee`) bate:
- Cars: 6 items exato ✓
- Goods: 47.8% (Δ +0.5pp) ✓
- Goods ex cars: 50.0% (Δ +0.6pp) ✓
- Services: 58.0% (Δ +0.2pp) ✓

Gap resolvido via `MARKET_DRIVEN_EXCLUDE` (9 items Services com YoY
anômalo: 207 Air, 224 Video streaming, 225 Audio streaming, 255 Commercial
banks, 260 Securities commissions, 268 Portfolio mgmt, 269 Trust,
287 First-class postal, 288 Other delivery).

Contagem final 190 leaves vs 200 alvo BBA (1 Goods + 9 Services faltando).
% agregado se compensa (Δ ≤0.6pp em todos os 3 buckets), mas source ainda
diverge. Fechar contagem exata exige nota interna Itaú BBA com lista de
leaves — sem ela, iteração é chute.

## Next steps (não urgente)

1. Adicionar peso por expenditure share (T20405) como opção alternativa
   ao count-based. Chart BBA parece usar count ("Share of PCE Items"),
   mas versão weighted pode ser útil.
2. Se subir pro SQL corp: criar `script_itau/` seguindo padrão
   pareto_cpius/pareto_ipca (load + simulate + RUNBOOK). Requer decisão
   de indicator/namespace SQL — sugestão: `indicator="PCE"`,
   `bls_code="PCE:diffusion_yoy_headline"` etc.
3. Adicionar validação amostral contra série histórica (dá pra checar
   pontos passados do chart BBA se tivermos snapshots).

## Breadth ponderado por bins (análogo ao CPI, pendente)

CPI ganhou breadth 3-bins em 2026-10-09 (via `pareto_cpius/scripts/build_breadth_cpi.py`
usando pesos subitem RI time-varying). PCE ficou pendente porque não temos
pesos subitem oficiais nos CSVs.

Pra fechar o paralelo:
1. Fetch BEA **U20405** (Personal Consumption Expenditures by Type of Product
   em nominais mensais) via `fetch_pce.py` ou script novo.
2. Peso implícito mensal = `nominal_i(m) / Σ_i nominal_i(m)` por leaf.
3. Replicar lógica do `build_breadth_cpi.py` com pesos BEA + os 190 leaves já
   detectados em `data/leaves_detected.csv`.
4. 3 séries SQL: `PCE:breadth_above_3pct`, `PCE:breadth_0_to_3pct`, `PCE:breadth_below_0pct`.
5. Loader + RUNBOOK edit.

Benchmark pros números: Dallas Fed publica a mesma métrica (xlsx `pcedata.xlsx`
com 5 bins — ver `data/raw/dallas/`). Nossos 3 bins podem agregar os 5 Dallas
(`<0%` ⊃ nada direto, mas `0-3%` ⊃ `0-2%+2-3%` e `>3%` ⊃ `3-5%+5-10%+>10%`).
