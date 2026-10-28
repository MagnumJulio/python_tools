# pareto_pce — TODO

## ~~Dallas Trimmed Mean PCE — IDs FRED 404~~ ✅ Fechado 2026-10-28

Dallas tinha renomeado os IDs no FRED (padrao `680SFRBDAL` virou `158SFRBDAL`
+ `159SFRBDAL`). Novos endpoints confirmados e no pipeline:
- `PCETRIM1M158SFRBDAL`  — 1-mo annualized SA
- `PCETRIM12M159SFRBDAL` — 12-mo YoY
- `PCETRIM6M680SFRBDAL`  — 6-mo annualized (ainda vivo, não usado)

Fallback xlsx nativo documentado em
`reference_fed_alt_measures_endpoints.md`: `dallasfed.org/-/media/documents/research/pce/pcedata.xlsx`.

## ~~Breadth ponderado por bins~~ ✅ Fechado 2026-10-28

Pattern CPI breadth replicado:
- `scripts/fetch_pce.py` ganhou U20405 (nominais) alem do U20404 (prices).
- `scripts/build_breadth_pce.py` + `script_itau/load_breadth_pce_to_sql.py`.
- 3 series SQL: `PCE:breadth_{above_3pct, 0_to_3pct, below_0pct}`, NSA.
- Peso = nominais BEA U20405 do proprio mes (nao RI Dez como CPI — PCE nao
  publica RI em arquivo historico, mas nominais sao disponiveis mensais).

**Dallas pcedata.xlsx NAO e benchmark comparavel direto**: Dallas mede MoM
annualized sobre universe Trimmed Mean customizado (~178 components com
exclusoes); nosso e YoY sobre 190 leaves U20404. Correlacao ~0 esperada
e observada. Fica como referencia conceitual, nao sanity check.

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
   ao count-based do diffusion. Chart BBA parece usar count ("Share of PCE
   Items"), mas versão weighted pode ser útil pra comparar com o breadth.
2. Validação amostral do breadth contra snapshots BBA (se existir).
3. Simulador local `simulate_breadth_pce_to_sql.py` seguindo padrão
   `simulate_pce_to_sql.py` (nao urgente — loader direto ja validado via
   dry-run).
