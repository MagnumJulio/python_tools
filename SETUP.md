# SETUP — pipelines pareto_* em máquina nova

Checklist pra rodar os 4 pipelines (IPCA, IPCA-15, CPI-U, PCE) numa máquina
nova — casa ou corp. ~15min end-to-end se tudo correr liso.

## 1. Pré-requisitos de sistema

| Dep | Versão mín. | Pra quê |
|---|---|---|
| **Python** | 3.10+ | todos os scripts build/load/simulate |
| **R** | 4.0+ | pipeline primário IPCA/IPCA-15/CPI-U (fetch + reconstruct) |
| **curl** | qualquer | shell-out dos scripts PCE/difusão CPI-U quando atrás de proxy corp |
| **ODBC driver SQL Server** | 17+ | só corp — pra `pyodbc` conectar ao SQL Itaú |

**Windows (via winget)**:
```powershell
winget install Python.Python.3.12
winget install RProject.R
winget install curl.curl
# ODBC driver: baixa de aka.ms/downloadmsodbcsql
```

## 2. Clone + deps

```bash
git clone https://github.com/MagnumJulio/python_tools.git
cd python_tools

# Python
pip install -r requirements.txt

# R (3 pacotes)
Rscript -e "install.packages(c('httr','jsonlite'), repos='https://cran.r-project.org')"
# Opcional (só IPCA/IPCA-15 full load com fix DP/medio SA):
Rscript -e "install.packages('seasonal', repos='https://cran.r-project.org')"
```

**Corp**: `opt_utils` já vem com o ambiente corporativo (não é pip-installable). Confere `python -c "from opt_utils.database import SQLConnector"`.

## 3. Env vars obrigatórios

| Env | Pra que | Onde pegar |
|---|---|---|
| `BLS_API_KEY` | CPI-U fetch (sem key, trava em rate limit 25/dia) | https://data.bls.gov/registrationEngine/ |
| `BEA_API_KEY` | PCE fetch | https://apps.bea.gov/API/signup/ |
| `HTTP_PROXY` / `HTTPS_PROXY` | **Corp only** — já setadas no corp Itau por default pelo profile. Scripts Python que shell-out curl leem automaticamente. | TI corp (já configurado) |
| `CORP_PROXY_URL` | **Opcional override** — só se quiser forçar um proxy específico diferente do `HTTPS_PROXY` default. | — |

**Bash** (`~/.bashrc` ou `~/.profile`):
```bash
export BLS_API_KEY="<sua_chave_bls>"
export BEA_API_KEY="<sua_chave_bea>"
# HTTP_PROXY/HTTPS_PROXY: corp já tem; casa deixa vazio
```

**PowerShell** (`$PROFILE`):
```powershell
$env:BLS_API_KEY = "<sua_chave_bls>"
$env:BEA_API_KEY = "<sua_chave_bea>"
```

## 4. Proxy R (corp only)

Scripts R têm `proxy_config.R` opcional em cada projeto. Em casa funciona
com `PROXY_HOST=""` (default — no-op). Corp: edita 3 arquivos pra apontar
pro proxy:

```r
# pareto_ipca/scripts/proxy_config.R
# pareto_ipca15/scripts/proxy_config.R
# pareto_cpius/scripts/proxy_config.R
PROXY_HOST <- "proxynew.itau"
PROXY_PORT <- 8443
PROXY_USER <- "<user>"
PROXY_PASS <- "<pass>"
```

## 5. Smoke test (valida tudo)

```bash
# Confere Python deps
python -c "import pandas, numpy, requests, openpyxl, statsmodels; print('OK Python')"

# Confere R deps
Rscript -e "library(httr); library(jsonlite); cat('OK R\n')"

# Confere APIs (vai pela internet):
#   BLS
Rscript pareto_cpius/scripts/fetch_bls_cpiu.R 2>&1 | tail -3
#   SIDRA (sem key, só confirma conectividade)
Rscript pareto_ipca/scripts/reconstruct_ipca.R --no-bcb 2>&1 | tail -3
#   BEA + Cleveland (via alt measures)
python pareto_pce/scripts/build_alt_measures_pce.py 2>&1 | tail -3

# Smoke SQL corp
python pareto_cpius/script_itau/load_cpius_to_sql.py --check   # read-only preflight
```

Se cada um imprime "OK" ou "[OK]", setup está completo.

## 6. ALTER TABLE no SQL corp (uma vez só)

Loaders esperam coluna `bls_code` em `OPT_Macro_Series_2`. Se é a primeira
vez usando esse schema em outro DB corp, rode:

```sql
ALTER TABLE OPT_Macro_Series_2 ADD bls_code VARCHAR(255) NULL;
```

`--check` dos loaders falha com `[FAIL] coluna bls_code NAO existe` se não
estiver.

## 7. Fluxo mensal

Depois do setup, release day:

```bash
# IPCA cheio
cd pareto_ipca
# → segue pareto_ipca/script_itau/RUNBOOK_ATUALIZACAO_DASHBOARD.md

# IPCA-15
cd ../pareto_ipca15
# → segue pareto_ipca15/script_itau/RUNBOOK_ATUALIZACAO_21_CATS.md

# CPI-U
cd ../pareto_cpius
# → segue pareto_cpius/script_itau/RUNBOOK_ATUALIZACAO_DASHBOARD.md

# PCE (fim do mês)
cd ../pareto_pce
# → segue pareto_pce/script_itau/RUNBOOK.md
```

Master com calendário + prioridade em `RUNBOOK_RELEASE_DAY.md` na raiz.

## 8. Troubleshooting

| Sintoma | Causa | Fix |
|---|---|---|
| `curl rc=5`/`rc=22`/`rc=28` ou `407 Authentication Required` | Proxy não detectado ou credenciais inválidas | Confirma `echo $HTTPS_PROXY` tem user:pass; se corp e tá vazio, falar com TI. Pra forçar: `export CORP_PROXY_URL=http://user:pass@proxy:port` |
| `REQUEST_NOT_PROCESSED` BLS | rate limit | esperar 5-10min; confere `BLS_API_KEY` válida |
| `[FAIL] coluna bls_code` | ALTER TABLE não rodado | seção 6 |
| `Violation of UNIQUE KEY ... UQ_OPT_Macro_Series_2_Code` | migração não idempotente em DB legado | atualizar p/ commit `f9cccf6`+ (migração agora tem SKIP) |
| Loader SA diverge em algumas cats IPCA | wrapper corp X-13 bugado em `servicos`/`alim_dom`/`DP`/`nucleo_medio` | rodar `_fix_*.py` conforme RUNBOOK IPCA Estágio 5.1 |
| SIDRA truncado logo no release | IBGE ainda publicando | re-rodar após 2-5min |
| FRED timing-out local | edge Akamai lento, varia por dia/rede | corp funciona; local tenta retry 3× ou pula p/ fallback |

## Documentos adicionais

- `pareto_*/CLAUDE.md` — arquitetura, convenções, histórico de cada pipeline
- `pareto_cpius/ALT_MEASURES.md` — doc das 10 medidas alternativas (Sticky, Median, Trimmed etc)
- `RUNBOOK_RELEASE_DAY.md` — master com calendário e ordem de prioridade
- RUNBOOKs de cada projeto em `pareto_*/script_itau/`
