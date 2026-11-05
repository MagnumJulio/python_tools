# MacroScheduler — alterações para levar à máquina corporativa

Pasta de transporte: contém **só o que muda no MacroScheduler de produção** para ganhar a
aba **🧪 Rodagem Local** (rodar os pipelines IPCA / IPCA-15 / CPI-U / PCE deste repositório
de dentro do app). Nada de mock, nada de `run_dev.py`, nada de `dev_mocks/`.

Na corp: `git pull` neste repositório e copie os arquivos abaixo para a pasta do
MacroScheduler (onde estão `engine.py`, `gui.py`, `main.py`, `build.spec`).

## 1. O que copiar

| Arquivo aqui | Destino no MacroScheduler | Ação |
|---|---|---|
| `local_pipelines.py` | `local_pipelines.py` | **novo** — copiar inteiro |
| `gui.py` | `gui.py` | **substituir** o arquivo inteiro (ou aplicar o diff, seção 3) |
| `local_settings.example.json` | `local_settings.example.json` | novo — modelo da configuração |
| `RODAGEM_LOCAL.md` | `RODAGEM_LOCAL.md` | documentação da aba (opcional) |
| `gui.py.diff` | — | só referência: diff do `gui.py` original → novo |

Arquivos **não alterados**: `engine.py`, `uk_labor.py`, `styles.py`, `main.py`, `main.spec`,
`build.spec`, `requirements.txt`. O `local_pipelines.py` não tem dependência nova
(só stdlib: `subprocess`, `json`, `shlex`, `threading`).

## 2. Configurar na corp (uma vez)

1. Copie `local_settings.example.json` → `local_settings.json` **ao lado do exe** (ou do
   `main.py`, se rodar do fonte) e preencha, ou faça isso pela própria aba e clique em
   *Salvar configuração*:
   ```json
   {
     "python_tools_dir": "C:\\caminho\\python_tools",
     "python_exe": "",
     "rscript_cmd": "C:\\Program Files\\R\\R-4.4.3\\bin\\Rscript.exe",
     "BLS_API_KEY": "...",
     "BEA_API_KEY": "..."
   }
   ```
   - `python_tools_dir` é a pasta que **contém** `pareto_ipca`, `pareto_ipca15`, `pareto_cpius`
     e `pareto_pce`. O nome da pasta raiz não importa: na corp é `itau-ty9-testes-sqldash`.
     A pré-verificação só checa essas quatro subpastas.
   - `python_exe` vazio = o mesmo Python do app. **No exe (PyInstaller) isso não existe**:
     informe o caminho do `python.exe` do ambiente corp que tem `opt_utils`, `pandas`, etc.
     (o mesmo que você usa hoje para rodar `load_*_to_sql.py`).
   - `rscript_cmd`: `Rscript` basta se estiver no PATH.
   - O arquivo guarda as chaves: não versionar.
2. Proxy: os scripts Python do python_tools leem `HTTP_PROXY`/`HTTPS_PROXY`. Se o ambiente
   corp não os define, o app injeta o `_proxies` do `uk_labor.py`. Os scripts R continuam
   usando o `scripts/proxy_config.R` de cada projeto.
3. Teste primeiro com **Dry-run** marcado (loaders com `--dry-run`, nada gravado).

## 3. `gui.py` linha a linha (original de 832 linhas → novo de 1156)

Se preferir editar o `gui.py` original em vez de substituir, são 13 pontos. Os números são
linhas do **arquivo original**. O `gui.py.diff` tem o texto exato de cada trecho.

| # | Linha(s) orig. | O que fazer |
|---|---|---|
| 1 | 10-13 | No `from PyQt5.QtWidgets import (...)`, trocar `QInputDialog,` por `QInputDialog, QComboBox, QFileDialog,` |
| 2 | após 27 (fim do `from engine import (...)`) | Adicionar o bloco `from local_pipelines import (PIPELINES, PipelineOptions, LocalRunConfig, LocalPipelineRunner, load_settings, save_settings, plan_steps, settings_path, pipeline_display_name, pipeline_key_from_display,)` |
| 3 | após 80 (depois de `UpdateWorker.cancel`) | Adicionar a classe `LocalPipelineWorker(QThread)` (21 linhas: sinais `log_signal`, `progress_signal`, `finished_signal`; `run()` chama `self.runner.run(...)`; `cancel()`) |
| 4 | 86-99 (`ScheduleJob.__init__`) | Acrescentar o parâmetro `pipeline_key: str \| None = None`, a linha `self.pipeline_key = pipeline_key` e mudar a anotação `self.worker: UpdateWorker \| LocalPipelineWorker \| None = None` |
| 5 | 114-115 (`MainWindow.__init__`) | Depois de `self._conn_worker = None` acrescentar `self._local_worker: LocalPipelineWorker \| None = None` e `self._local_settings = load_settings()` |
| 6 | 193 (`_build_ui`) | Depois do `addTab(... "⏰ Schedule Runs")` acrescentar `self.tabs.addTab(self._build_local_tab(), "🧪 Rodagem Local")` |
| 7 | 500-502 (`_on_reports_loaded`) | Depois do laço que preenche `sched_report_list`, chamar `self._add_pipelines_to_sched_list()` |
| 8 | 506-508 (`_on_reports_error`) | Chamar `self._add_pipelines_to_sched_list()` no fim e adicionar o método `_add_pipelines_to_sched_list` (6 linhas) logo abaixo |
| 9 | 631-632 (`_add_schedule`) | Antes do "UK Labor month prompt": `pipeline_key = pipeline_key_from_display(report)` |
| 10 | 645-651 (`_add_schedule`, construção do `ScheduleJob`) | `delete_before=False if pipeline_key else self.sched_chk_delete.isChecked()`, `cutoff_date="—" if pipeline_key else ...`, e novo argumento `pipeline_key=pipeline_key` |
| 11 | 656-657 (`_add_schedule`) | Depois do log do UK month: `if pipeline_key: self._sched_log("  ⚙ Pipeline local: usa as opções da aba 'Rodagem Local' no momento da execução")` |
| 12 | 767-781 (`_run_scheduled_job`) | Envolver a criação do `UpdateWorker` num `if job.pipeline_key: ... else: ...` — no ramo `if`, `worker = LocalPipelineWorker(self._local_run_config([job.pipeline_key]))`, `job.worker = worker`, `worker.log_signal.connect(self._sched_log)` |
| 13 | antes de 815 (seção `# Helpers`) | Inserir o bloco inteiro da aba (≈275 linhas): `_build_local_tab`, `_local_options`, `_local_settings_from_form`, `_local_run_config`, `_selected_pipelines`, `_refresh_local_plan`, `_browse_python_tools`, `_save_local_settings`, `_start_local_run`, `_cancel_local_run`, `_on_local_progress`, `_on_local_finished`, `_set_local_running`, `_local_log` |

Na prática o caminho mais seguro é substituir o `gui.py` inteiro: o novo é o original com
exatamente essas 13 inserções, sem nenhuma outra mudança.

## 4. Gerar o exe

`build.spec` não precisa mudar: `gui.py` importa `local_pipelines`, então o PyInstaller o
inclui. Só lembre do `local_settings.json` ao lado do exe e de preencher `python_exe`
(o exe não consegue rodar os loaders com o Python embutido).

## 5. Conferência rápida depois de copiar

```
python -c "import local_pipelines, gui; print('ok')"
```
Abrir o app, aba Rodagem Local, marcar IPCA, Dry-run, Rodar. Esperado: SIDRA baixa, loaders
listam o que gravariam e nada é escrito.

## 6. Avisos conhecidos (do python_tools, não do MacroScheduler)

- `_fix_servicos_idx_sa.py` (IPCA e IPCA-15) termina com `[FAIL] Var SA de servicos nao
  encontrada`: procura a série de variação SA que o loader deixou de gravar em 27/08. A aba
  trata como aviso e segue.
- `build_alt_measures_cpi.py`: download do xlsx do Atlanta Fed deu erro HTTP em 05/11; o
  grupo alt measures é pulado e difusão/breadth seguem.
