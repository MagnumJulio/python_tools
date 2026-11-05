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
   - `python_exe` vazio = o app descobre sozinho: o próprio Python quando roda do fonte; no
     exe, `python` no PATH e depois o launcher `py -3`. Só preencha se o botão **Testar
     ambiente** disser que o Python encontrado não tem `opt_utils` (aí aponte para o
     `python.exe` que roda os `load_*_to_sql.py` hoje).
   - `rscript_cmd`: `Rscript` basta se estiver no PATH.
   - O arquivo guarda as chaves: não versionar.
2. Proxy: os scripts Python do python_tools leem `HTTP_PROXY`/`HTTPS_PROXY`. Se o ambiente
   corp não os define, o app injeta o `_proxies` do `uk_labor.py`. Os scripts R continuam
   usando o `scripts/proxy_config.R` de cada projeto.
3. Clique em **🔍 Testar ambiente**: ele roda o Python e o Rscript de verdade e lista, item a
   item, o que está ok e o que falta (pasta, Python com opt_utils, Rscript, chaves). Corrija os
   ✗ e teste de novo.
4. Depois teste uma rodada com **Dry-run** marcado (loaders com `--dry-run`, nada gravado).

## 3. `gui.py` linha a linha (original de 832 linhas → novo de 1198)

Se preferir editar o `gui.py` original em vez de substituir, são 13 pontos. Os números são
linhas do **arquivo original**. O `gui.py.diff` tem o texto exato de cada trecho.

| # | Linha(s) orig. | O que fazer |
|---|---|---|
| 1 | 10-13 | No `from PyQt5.QtWidgets import (...)`, trocar `QInputDialog,` por `QInputDialog, QComboBox, QFileDialog,` |
| 2 | após 27 (fim do `from engine import (...)`) | Adicionar o bloco `from local_pipelines import (PIPELINES, PipelineOptions, LocalRunConfig, LocalPipelineRunner, load_settings, save_settings, plan_steps, settings_path, check_environment, pipeline_display_name, pipeline_key_from_display,)` |
| 3 | após 80 (depois de `UpdateWorker.cancel`) | Adicionar as classes `LocalPipelineWorker(QThread)` (sinais `log_signal`, `progress_signal`, `finished_signal`; `run()` chama `self.runner.run(...)`; `cancel()`) e `_EnvCheckWorker(QThread)` (sinal `result`; `run()` emite `check_environment(...)`) |
| 4 | 86-99 (`ScheduleJob.__init__`) | Acrescentar o parâmetro `pipeline_key: str \| None = None`, a linha `self.pipeline_key = pipeline_key` e mudar a anotação `self.worker: UpdateWorker \| LocalPipelineWorker \| None = None` |
| 5 | 114-115 (`MainWindow.__init__`) | Depois de `self._conn_worker = None` acrescentar `self._local_worker: LocalPipelineWorker \| None = None`, `self._env_worker: _EnvCheckWorker \| None = None` e `self._local_settings = load_settings()` |
| 6 | 193 (`_build_ui`) | Depois do `addTab(... "⏰ Schedule Runs")` acrescentar `self.tabs.addTab(self._build_local_tab(), "🧪 Rodagem Local")` |
| 7 | 500-502 (`_on_reports_loaded`) | Depois do laço que preenche `sched_report_list`, chamar `self._add_pipelines_to_sched_list()` |
| 8 | 506-508 (`_on_reports_error`) | Chamar `self._add_pipelines_to_sched_list()` no fim e adicionar o método `_add_pipelines_to_sched_list` (6 linhas) logo abaixo |
| 9 | 631-632 (`_add_schedule`) | Antes do "UK Labor month prompt": `pipeline_key = pipeline_key_from_display(report)` |
| 10 | 645-651 (`_add_schedule`, construção do `ScheduleJob`) | `delete_before=False if pipeline_key else self.sched_chk_delete.isChecked()`, `cutoff_date="—" if pipeline_key else ...`, e novo argumento `pipeline_key=pipeline_key` |
| 11 | 656-657 (`_add_schedule`) | Depois do log do UK month: `if pipeline_key: self._sched_log("  ⚙ Pipeline local: usa as opções da aba 'Rodagem Local' no momento da execução")` |
| 12 | 767-781 (`_run_scheduled_job`) | Envolver a criação do `UpdateWorker` num `if job.pipeline_key: ... else: ...` — no ramo `if`, `worker = LocalPipelineWorker(self._local_run_config([job.pipeline_key]))`, `job.worker = worker`, `worker.log_signal.connect(self._sched_log)` |
| 13 | antes de 815 (seção `# Helpers`) | Inserir o bloco inteiro da aba (≈300 linhas): `_build_local_tab`, `_local_options`, `_local_settings_from_form`, `_local_run_config`, `_selected_pipelines`, `_refresh_local_plan`, `_browse_python_tools`, `_check_local_environment`, `_on_local_env_checked`, `_save_local_settings`, `_start_local_run`, `_cancel_local_run`, `_on_local_progress`, `_on_local_finished`, `_set_local_running`, `_local_log` |

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
- `build_alt_measures_cpi.py`: se FRED/Atlanta/Cleveland falhar, só o grupo alt measures é
  pulado; bottom-up (Trimmed Sym 25%), difusão e breadth seguem.

## 7. Bottom-up do CPI-U (desde 05/11)

O Trimmed Sym 25% custom saiu do `build_alt_measures_cpi.py` e virou par próprio no
python_tools: `scripts/build_alt_bottomup_cpi.py` + `script_itau/load_alt_bottomup_cpi_to_sql.py`.
A aba já roda esse par como grupo independente dentro de "CPI-U: alt measures + bottom-up +
difusão + breadth". Precisa do `git pull` do python_tools na corp (PR "bottom-up") — sem ele
o passo "build bottom-up" falha com arquivo não encontrado e a aba segue com aviso.

## 8. Aba 📅 Calendário (desde 05/11) — atualizar books pelo calendário Bloomberg

Lê os releases do dia em `OPT_Macro_Calendar` (mesma query do site) e atualiza/agenda os
books ligados a cada indicador. Uso e manutenção: `CALENDARIO.md`. Pressupõe a aba Rodagem
Local já copiada (seções 1-7); se for copiar tudo de uma vez, o `gui.py` daqui já tem as duas.

### O que copiar

| Arquivo aqui | Destino no MacroScheduler | Ação |
|---|---|---|
| `calendar_books.py` | `calendar_books.py` | **novo** — copiar inteiro |
| `calendar_books.csv` | `calendar_books.csv` **ao lado do exe** (e do `main.py`) | **novo** — mapeamento indicador → book |
| `gui.py` | `gui.py` | **substituir** inteiro (ou seção abaixo) |
| `local_pipelines.py` | `local_pipelines.py` | **substituir** (só ganhou 4 chaves em `DEFAULT_SETTINGS`) |
| `local_settings.example.json` | idem | substituir (modelo com as chaves novas) |
| `CALENDARIO.md` | `CALENDARIO.md` | documentação (opcional) |
| `gui_calendario.diff` | — | referência: diff do `gui.py` da Rodagem Local → este |

Sem dependência nova; `build.spec` não muda (o PyInstaller inclui `calendar_books.py` porque o
`gui.py` importa). Se o `calendar_books.csv` não estiver ao lado do exe, o app cria um com
os 4 indicadores de payroll/Michigan.

### `local_pipelines.py` linha a linha

Dentro de `DEFAULT_SETTINGS = {...}`, depois de `"BEA_API_KEY": "",` acrescentar:
```python
    "calendar_auto": False,
    "calendar_auto_time": "07:00",
    "calendar_delay_min": 1,
    "calendar_only_relevant": True,
```

### `gui.py` linha a linha (a partir do `gui.py` da Rodagem Local, 1198 linhas → 1662)

| # | Onde | O que fazer |
|---|---|---|
| 1 | `from PyQt5.QtWidgets import (...)` | acrescentar `QListWidgetItem` e `QSpinBox` |
| 2 | `from PyQt5.QtCore import (...)` | acrescentar `QUrl` |
| 3 | `from PyQt5.QtGui import ...` | acrescentar `QDesktopServices` |
| 4 | depois do bloco `from local_pipelines import (...)` | `import calendar_books as cal` |
| 5 | antes de `class ScheduleJob` | colar a classe `CalendarLoadWorker(QThread)` (25 linhas, no diff) |
| 6 | `ScheduleJob.__init__` | novo parâmetro `reports: list[str] \| None = None` e a linha `self.reports = reports or [report]` |
| 7 | `MainWindow.__init__`, depois de `self._local_settings = load_settings()` | bloco `# Calendário` (9 linhas: `_cal_worker`, `_cal_update_worker`, `_cal_df`, `_cal_plans`, `_cal_after_load`, `_cal_auto_done_for`, `_cal_auto_timer`) |
| 8 | `_build_ui`, depois do `addTab(... "🧪 Rodagem Local")` | `self.tabs.addTab(self._build_calendar_tab(), "📅 Calendário")` |
| 9 | `_run_scheduled_job`, no `UpdateConfig(` | trocar `reports=[job.report],` por `reports=list(job.reports),` |
| 10 | antes da seção `# Helpers` | colar o bloco inteiro `# TAB 4: Calendário` (≈430 linhas, do `_CAL_COLORS` até `_cal_log`) |

Mais seguro: substituir o `gui.py` inteiro.

### Conferência rápida

```
python -c "import calendar_books, gui; print('ok')"
```
Abrir o app → aba Calendário → Carregar calendário. Esperado: os releases de hoje com a
coluna Book colorida e, em dia de payroll, `US Payroll` na lista da direita. A query usa
`?` (pyodbc), igual ao resto do engine.

### A conferir na corp
- **Fuso**: o app usa `release_date_time` como está no banco, como hora local da máquina. Se
  a tabela guardar outro fuso (coluna `timezone`), os agendamentos ficam deslocados: avisar.
- **Nomes**: os países precisam bater com `country_name` (ex.: `United States`) e os books
  com `OPT_Macro_Reports` (book inexistente aparece em vermelho na aba).
