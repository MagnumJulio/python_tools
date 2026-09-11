# pareto_pce — TODO

## Gap Services vs Itaú BBA (open)

Chart de referência (Itaú BBA research, foto celular) mostra pra jul-2026:
- Goods (91 items): 47.3%
- Services (109 items): 57.8%
- Goods ex cars (85 items): 49.4%

Prototype atual bate:
- Goods: 47.8% (Δ +0.5pp) ✓
- Goods ex cars: 50.0% (Δ +0.6pp) ✓
- Cars: 6 items exato ✓
- **Services: 61.5% (Δ +3.7pp)** ⚠

Contagem Services bate exato (109/109) mas composição não. Diagnóstico:
Portfolio management (line 268, YoY +20.8%) e Trust/fiduciary (line 269,
+18.8%) são imputações BEA baseadas em valor de mercado, não preços de
serviço observáveis. Excluí-los sozinho não fecha o gap.

**Ação pra fechar exato**: pegar a metodologia interna Itaú BBA
(pesquisa deve ter nota descrevendo quais items U20404 entram). Aí
ajustar SUBAGG_LINES / SERVICES_PRODUCT_LINE_LEAVES em
`scripts/build_diffusion.py`.

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
