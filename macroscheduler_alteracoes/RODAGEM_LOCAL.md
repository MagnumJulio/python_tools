# Rodagem Local — pipelines do `python_tools` dentro do MacroScheduler

A aba **🧪 Rodagem Local** roda os 4 pipelines de inflação do repositório
[python_tools](https://github.com/MagnumJulio/python_tools) (IPCA, IPCA-15,
CPI-U, PCE) sem sair do MacroScheduler. Os scripts continuam sendo os do
`python_tools` (não há cópia aqui): o app só executa, na ordem dos RUNBOOKs,
cada `Rscript ...` / `python ...` como subprocesso, mostra o stdout no log e
para no primeiro erro.

## Pré-requisitos (máquina corp)

1. `python_tools` clonado e atualizado (`git pull`), com `pip install -r requirements.txt`.
2. R instalado (`Rscript` no PATH ou caminho completo na aba) + pacotes `httr`, `jsonlite`
   (IPCA/IPCA-15/CPI-U usam R; PCE é só Python).
3. `opt_utils` disponível no Python que vai rodar os loaders (o mesmo do MacroScheduler, ou
   outro informado no campo *Python*).
4. Chaves `BLS_API_KEY` (CPI-U) e `BEA_API_KEY` (PCE): preencha na aba ou deixe no ambiente.
5. Proxy: os scripts leem `HTTP_PROXY`/`HTTPS_PROXY`. Se não estiverem no ambiente, o app
   injeta o proxy do `proxy_config.py` (o mesmo do ONS). Os scripts R usam o
   `scripts/proxy_config.R` de cada projeto, como antes.

A configuração fica em `local_settings.json` ao lado do exe (modelo em
`local_settings.example.json`; o arquivo real é gitignored porque guarda as chaves).

## O que cada pipeline executa

| Pipeline | Passos (escopo *Dashboard*) | Fonte do roteiro |
|---|---|---|
| IPCA | `reconstruct_ipca.R --no-bcb` → `build_pareto_indice.R` → `load_pareto_to_sql.py --only <21 cats>` → idem `--sa` → `_fix_servicos_idx_sa.py` → `_fix_alim_dom_sa.py` | `pareto_ipca/script_itau/RUNBOOK_ATUALIZACAO_DASHBOARD.md` + `RUNBOOK_RELEASE_DAY.md` |
| IPCA-15 | mesmo esqueleto em `pareto_ipca15` (fix só `servicos`) | `pareto_ipca15/script_itau/RUNBOOK_ATUALIZACAO_21_CATS.md` |
| CPI-U | `fetch_bls_cpiu.R` → `fetch_bls_pesos.R` → `build_custom_aggregations.R` → `load_cpius_to_sql.py --only <22 cats>` → (extras) alt measures, difusão, breadth → (opcional) OER regional | `pareto_cpius/script_itau/RUNBOOK_ATUALIZACAO_DASHBOARD.md` |
| PCE | `fetch_pce.py` → builds (categorias, difusão, breadth, altas, proxy) → 5 loaders do grupo A → (opcional) scraped Cleveland/Dallas | `pareto_pce/script_itau/RUNBOOK.md` |

Opções:

- **Escopo Full** tira o `--only` (carrega todas as categorias) e, no IPCA/IPCA-15 com SA,
  acrescenta `_sa_dp_nucleo_medio.R` + fixes DP/núcleo médio (marcados como opcionais:
  falha vira aviso).
- **Dry-run** passa `--dry-run` aos loaders (nada é gravado) e pula os `_fix_*`. Os fetches
  rodam normalmente, então ainda precisa de internet/proxy.
- Os extras do CPI-U (alt measures, difusão, breadth, OER) e o scraped do PCE são grupos
  opcionais build+load: se o build falha (fonte externa fora do ar, URL mudou), a carga
  correspondente é pulada e o pipeline segue. Os builds do python_tools já preservam o CSV
  anterior nesse caso, e recarregar dado velho não ajuda.
- Os `_fix_*` pós-carga são opcionais: se falharem, o pipeline segue e termina "com avisos"
  (hoje `_fix_servicos_idx_sa.py` procura a série de *variação* SA, que o loader deixou de
  gravar no sync 2026-08-27 do python_tools; é um ajuste a fazer lá).
- No modo dev (`run_dev.py`), os loaders do python_tools rodam contra o SQLite mock
  (`MACRO_DEV_MOCKS` entra no `PYTHONPATH` dos subprocessos), então dá para testar a carga
  inteira em casa; o `INFORMATION_SCHEMA.COLUMNS` do preflight é emulado.
- Todos os loaders recebem `--no-confirm`; o stdin do subprocesso é fechado, então um
  script que ainda pedisse confirmação falha em vez de travar a GUI.

A lista "Passos planejados" mostra exatamente o que vai rodar antes de clicar em Rodar.

## Para quem vai herdar o sistema

- **Testar ambiente** (botão na Configuração) roda de verdade o Python e o Rscript
  configurados e lista, item a item, o que está ok e o que falta: pasta dos pipelines,
  Python com `pandas`/`requests`/`opt_utils`, Rscript, chaves BLS/BEA. Corrija os ✗ e teste
  de novo. Nada é gravado no SQL nesse teste.
- O campo **Python** pode ficar vazio: o app usa o próprio interpretador quando roda do
  fonte e, no exe, procura `python` no PATH e depois o launcher `py -3`. Preencha só se o
  teste disser que o Python encontrado não tem `opt_utils`.
- O campo **Rscript** pode ficar `Rscript`: no Windows, se não estiver no PATH, o app
  procura em `C:\Program Files\R\R-*\bin\Rscript.exe`.
- Em caso de erro no meio de uma rodada, o log mostra o comando exato, a pasta e o código de
  saída do passo; o cabeçalho da rodada mostra qual Python e qual Rscript foram usados.

## Agendamento

Na aba **Schedule Runs** os pipelines aparecem na lista como
`⚙ Pipeline local: IPCA (IBGE)` etc., junto dos relatórios Haver/BBG. Um agendamento de
pipeline usa as opções que estiverem marcadas na aba Rodagem Local na hora de executar.

## Modo headless / desenvolvimento

```bash
python run_dev.py --pipeline ipca,cpius --dry-run     # roda com a configuração do local_settings.json
python run_dev.py --pipeline pce --full
```

Para testar sem R, sem internet e sem SQL, `dev_mocks/fake_python_tools.py` gera um
`python_tools` falso com stubs de todos os scripts:

```bash
python dev_mocks/fake_python_tools.py
MACRO_LOCAL_SETTINGS=dev_mocks/fake_python_tools/local_settings.json \
    python run_dev.py --pipeline ipca,ipca15,cpius,pce --dry-run
# FAKE_FAIL=load_pareto_to_sql.py simula erro num passo; FAKE_SLEEP=5 testa o Cancelar
```

## Onde mexer

- `local_pipelines.py` — registro dos passos (`_ipca`, `_cpius`, …) e o runner. Para
  acrescentar um passo ou pipeline, edite só aqui; a GUI e o headless leem `PIPELINES`.
- `gui.py::_build_local_tab` — a aba; `ScheduleJob.pipeline_key` — agendamento.
