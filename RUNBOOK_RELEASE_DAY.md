# RUNBOOK — release day (template)

Master runbook pros 4 pipelines de inflação. Delega os detalhes pros RUNBOOKs específicos de cada projeto; aqui ficam só calendário, pré-reqs globais e ordem de prioridade.

## Calendário dos releases

| Fonte | Dado | Dia típico | Horário BRT |
|---|---|---|---|
| IBGE | IPCA cheio | dia 8-10 do mês seguinte | ~09:00 |
| IBGE | IPCA-15 | dia 24 do próprio mês | ~09:00 |
| BLS  | CPI-U | dia 10-15 do mês seguinte | ~09:30 (08:30 EST) |
| BEA  | PCE | último dia útil do mês | ~09:30 (08:30 EST) |

## Pré-requisitos (corp, uma vez por sessão)

```bash
# Rede
#   VPN corp ativa, opt_utils no PYTHONPATH

# Env vars (bash — PowerShell usa $env:NOME = "valor")
export BLS_API_KEY=<sua_chave>           # CPI-U
export BEA_API_KEY=<sua_chave>           # PCE
export CORP_PROXY_URL=http://<user>:<pass>@proxynew.itau:8443   # CPI-U difusão + PCE fetch
# Opcional, só se portas HTTP/HTTPS diferirem:
# export CORP_PROXY_URL_HTTP=http://<user>:<pass>@proxynew.itau:8080

# git pull em python_tools (confere que está no main atualizado)
cd python_tools && git pull
```

**Coluna SQL `bls_code`** (uma vez só, se nunca rodou neste corp):
```sql
ALTER TABLE OPT_Macro_Series_2 ADD bls_code VARCHAR(255) NULL;
```

## Blocos (um por release)

Cada bloco é delegado ao RUNBOOK do próprio projeto. Rode sequencial no dia:

| Bloco | Ativar quando | RUNBOOK |
|---|---|---|
| **A — IPCA cheio** | release IBGE do mês saiu | `pareto_ipca/script_itau/RUNBOOK_ATUALIZACAO_DASHBOARD.md` |
| **B — IPCA-15** | release IPCA-15 do mês saiu (~dia 24) | `pareto_ipca15/script_itau/RUNBOOK_ATUALIZACAO_21_CATS.md` |
| **C — CPI-U** | release BLS do mês saiu | `pareto_cpius/script_itau/RUNBOOK_ATUALIZACAO_DASHBOARD.md` |
| **D — PCE** | release BEA do mês saiu | `pareto_pce/script_itau/RUNBOOK.md` |

**Dica**: full load (não `--only`) é desnecessário no release day. Dashboard roda com o subset. Full só vale quando mexeu em cat nova / backfill.

## Fixes SA obrigatórios — IPCA (sempre)

Wrapper corp `x13_custom` tem bugs conhecidos. Após o load SA do IPCA cheio (`load_pareto_to_sql.py --sa`):

```bash
python pareto_ipca/script_itau/_fix_servicos_idx_sa.py    # SEMPRE (dashboard e full)
python pareto_ipca/script_itau/_fix_alim_dom_sa.py        # SEMPRE (dashboard e full)
```

**Full load só**: adicionar DP + nucleo_medio SA (fora do dashboard 21-cats):
```bash
Rscript pareto_ipca/scripts/_sa_dp_nucleo_medio.R         # gera CSV via R `seasonal`
python  pareto_ipca/script_itau/_fix_dp_medio_sa.py       # grava SQL
python  pareto_ipca/script_itau/_fix_nucleo_medio_sa.py   # opcional refinement
```

Detalhes em `pareto_ipca/script_itau/RUNBOOK.md` Estágio 5.1 ou `pareto_ipca_sa_workarounds` da memória.

## Ordem preferencial se atrasar

1. **IPCA cheio** — mais visível internamente
2. **CPI-U** — dashboards ativos dependem
3. **IPCA-15** — só se houve reprocessing pedido
4. **PCE** — menor consumo diário

## Troubleshooting

| Sintoma | Causa provável | Fix |
|---|---|---|
| `curl rc=5` no CPI-U difusão ou PCE fetch | `CORP_PROXY_URL` não setada | export conforme pré-reqs |
| `REQUEST_NOT_PROCESSED` BLS | rate limit | esperar 5-10min; conferir `BLS_API_KEY` |
| SIDRA retorna dado truncado no release | IBGE ainda publicando | re-rodar step 1 do bloco após 2-5min |
| Preflight `[FAIL] coluna bls_code` | ALTER TABLE não rodado | SQL do pré-req acima |
| Difusão IPCA sobe lixo (10^50) | regressão do special-case | confirmar commit `300f6e6` no branch |
| X-13 passthrough em cat específica | wrapper corp bug | se for `servicos`, `_fix_servicos_idx_sa.py` resolve; outras: aceitar NSA=SA |
| Row órfã CPI-U/IPCA com `haver_code='PARETO_%'` | formato legado | migração idempotente dos loaders cobre — não deletar manual |

## Sanity final

Após cada bloco, 1 spot check mental vs release oficial:
- **IPCA cheio**: `total` NSA vs print IBGE
- **IPCA-15**: `total` NSA vs BCB SGS 7478
- **CPI-U**: `all_items` NSA vs Table 1 BLS
- **PCE**: `diffusion_services_yoy` vs chart BBA

Divergência >0.3pp → investigar antes de considerar carga concluída.
