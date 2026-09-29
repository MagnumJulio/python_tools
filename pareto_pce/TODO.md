# pareto_pce — TODO

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
