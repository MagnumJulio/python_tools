# gui.py
from __future__ import annotations

import uuid
from datetime import datetime, date as ddate, time as dtime

from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QPushButton, QCheckBox, QDateEdit,
    QTextEdit, QProgressBar, QGroupBox, QAbstractItemView,
    QSplitter, QMessageBox, QTabWidget, QTimeEdit,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QInputDialog, QComboBox, QFileDialog,
)
from PyQt5.QtCore import (
    Qt, QDate, QTime, QThread, QTimer,
    pyqtSignal,
)
from PyQt5.QtGui import QTextCursor, QColor

from styles import DARK_STYLE
from engine import (
    UpdateConfig, UpdateEngine, get_session, fetch_available_reports,
    test_haver_connection, test_bbg_connection,
    UK_LABOR_REPORT_NAME,
)
from local_pipelines import (
    PIPELINES, PipelineOptions, LocalRunConfig, LocalPipelineRunner,
    load_settings, save_settings, plan_steps, settings_path, check_environment,
    pipeline_display_name, pipeline_key_from_display,
)


# ──────────────────────────────────────────────────────────────────────
# Workers
# ──────────────────────────────────────────────────────────────────────

class LoadReportsWorker(QThread):
    finished = pyqtSignal(list)
    error = pyqtSignal(str)

    def run(self):
        try:
            session = get_session()
            reports = fetch_available_reports(session)
            session.close()
            self.finished.emit(reports)
        except Exception as e:
            self.error.emit(str(e))


class ConnectionTestWorker(QThread):
    haver_result = pyqtSignal(bool, str)
    bbg_result = pyqtSignal(bool, str)

    def run(self):
        ok_h, msg_h = test_haver_connection()
        self.haver_result.emit(ok_h, msg_h)

        ok_b, msg_b = test_bbg_connection()
        self.bbg_result.emit(ok_b, msg_b)


class UpdateWorker(QThread):
    log_signal = pyqtSignal(str)
    progress_signal = pyqtSignal(int, int)
    finished_signal = pyqtSignal(bool, str)
    summary_signal = pyqtSignal(str)

    def __init__(self, config: UpdateConfig, parent=None):
        super().__init__(parent)
        self.engine = UpdateEngine(config)

    def run(self):
        self.engine.run(
            on_log=self.log_signal.emit,
            on_progress=self.progress_signal.emit,
            on_finished=self.finished_signal.emit,
            on_summary=self.summary_signal.emit,
        )

    def cancel(self):
        self.engine.cancel()


class LocalPipelineWorker(QThread):
    """Roda os pipelines do python_tools (subprocessos) fora da thread da GUI."""
    log_signal = pyqtSignal(str)
    progress_signal = pyqtSignal(int, int)
    finished_signal = pyqtSignal(bool, str)

    def __init__(self, config: LocalRunConfig, parent=None):
        super().__init__(parent)
        self.runner = LocalPipelineRunner(config)

    def run(self):
        self.runner.run(
            on_log=self.log_signal.emit,
            on_progress=self.progress_signal.emit,
            on_finished=self.finished_signal.emit,
        )

    def cancel(self):
        self.runner.cancel()


class _EnvCheckWorker(QThread):
    """check_environment() fora da thread da GUI (roda subprocessos)."""
    result = pyqtSignal(list)

    def __init__(self, settings: dict, pipelines, parent=None):
        super().__init__(parent)
        self._settings = settings
        self._pipelines = pipelines

    def run(self):
        try:
            self.result.emit(check_environment(self._settings, self._pipelines))
        except Exception as e:
            self.result.emit([(False, f"erro ao testar: {e}")])


# ──────────────────────────────────────────────────────────────────────
# Schedule Job data class
# ──────────────────────────────────────────────────────────────────────

class ScheduleJob:
    def __init__(self, job_id: str, report: str, scheduled_date: ddate,
                 scheduled_time: dtime, delete_before: bool, cutoff_date: str,
                 uk_labor_month: str | None = None, pipeline_key: str | None = None):
        self.job_id = job_id
        self.report = report
        self.pipeline_key = pipeline_key   # != None → rodagem local (python_tools)
        self.scheduled_date = scheduled_date
        self.scheduled_time = scheduled_time
        self.delete_before = delete_before
        self.cutoff_date = cutoff_date
        self.uk_labor_month = uk_labor_month
        self.status = "Aguardando"
        self.worker: UpdateWorker | LocalPipelineWorker | None = None
        self.has_run = False


# ──────────────────────────────────────────────────────────────────────
# Main Window
# ──────────────────────────────────────────────────────────────────────

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Macro Reports")
        self.setMinimumSize(1000, 750)
        self.resize(1150, 830)
        self.setStyleSheet(DARK_STYLE)

        self._all_reports: list[str] = []
        self._worker: UpdateWorker | None = None
        self._conn_worker: ConnectionTestWorker | None = None
        self._local_worker: LocalPipelineWorker | None = None
        self._env_worker: _EnvCheckWorker | None = None
        self._local_settings = load_settings()

        # Schedule state
        self._jobs: dict[str, ScheduleJob] = {}
        self._schedule_timer = QTimer(self)
        self._schedule_timer.setInterval(15_000)
        self._schedule_timer.timeout.connect(self._tick_schedule)

        self._build_ui()
        self._load_reports()
        self._run_connection_tests()

    # ── UK Labor month choices ────────────────────────────────────────

    _MONTH_CHOICES = [
        "jan", "feb", "mar", "apr", "may", "jun",
        "jul", "aug", "sep", "oct", "nov", "dec",
    ]

    def _ask_uk_month(self) -> str | None:
        month, ok = QInputDialog.getItem(
            self,
            "UK Employment — Mês de Referência",
            "Selecione o mês para montar as URLs do ONS:",
            self._MONTH_CHOICES,
            0,
            False,
        )
        if not ok:
            return None
        return month

    # ── Build UI ──────────────────────────────────────────────────────

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(24, 16, 24, 16)
        root.setSpacing(12)

        # Title
        title = QLabel("Macro Reports")
        title.setObjectName("title")
        title.setAlignment(Qt.AlignCenter)
        root.addWidget(title)

        subtitle = QLabel("Selecione relatórios, configure e execute a atualização")
        subtitle.setObjectName("subtitle")
        subtitle.setAlignment(Qt.AlignCenter)
        root.addWidget(subtitle)

        # Connection status bar
        conn_row = QHBoxLayout()
        conn_row.setSpacing(16)

        self.lbl_haver_status = QLabel("⏳ Haver: testando...")
        self.lbl_haver_status.setObjectName("connTesting")
        conn_row.addWidget(self.lbl_haver_status)

        self.lbl_bbg_status = QLabel("⏳ Bloomberg: testando...")
        self.lbl_bbg_status.setObjectName("connTesting")
        conn_row.addWidget(self.lbl_bbg_status)

        conn_row.addStretch()

        self.btn_test_conn = QPushButton("🔄 Testar Conexão")
        self.btn_test_conn.setObjectName("testConn")
        self.btn_test_conn.clicked.connect(self._run_connection_tests)
        conn_row.addWidget(self.btn_test_conn)

        root.addLayout(conn_row)

        # Tabs
        self.tabs = QTabWidget()
        root.addWidget(self.tabs, stretch=1)

        self.tabs.addTab(self._build_run_once_tab(), "▶ Run Once")
        self.tabs.addTab(self._build_schedule_tab(), "⏰ Schedule Runs")
        self.tabs.addTab(self._build_local_tab(), "🧪 Rodagem Local")

    # ── Connection Tests ──────────────────────────────────────────────

    def _run_connection_tests(self):
        self.btn_test_conn.setEnabled(False)

        self.lbl_haver_status.setText("⏳ Haver: testando...")
        self.lbl_haver_status.setObjectName("connTesting")
        self.lbl_haver_status.style().unpolish(self.lbl_haver_status)
        self.lbl_haver_status.style().polish(self.lbl_haver_status)

        self.lbl_bbg_status.setText("⏳ Bloomberg: testando...")
        self.lbl_bbg_status.setObjectName("connTesting")
        self.lbl_bbg_status.style().unpolish(self.lbl_bbg_status)
        self.lbl_bbg_status.style().polish(self.lbl_bbg_status)

        self._conn_worker = ConnectionTestWorker()
        self._conn_worker.haver_result.connect(self._on_haver_test)
        self._conn_worker.bbg_result.connect(self._on_bbg_test)
        self._conn_worker.finished.connect(self._on_conn_tests_done)
        self._conn_worker.start()

    def _on_haver_test(self, ok: bool, msg: str):
        if ok:
            self.lbl_haver_status.setText("✓ Haver: conectado")
            self.lbl_haver_status.setObjectName("connOk")
        else:
            self.lbl_haver_status.setText("✗ Haver: offline")
            self.lbl_haver_status.setToolTip(msg)
            self.lbl_haver_status.setObjectName("connFail")
        self.lbl_haver_status.style().unpolish(self.lbl_haver_status)
        self.lbl_haver_status.style().polish(self.lbl_haver_status)

    def _on_bbg_test(self, ok: bool, msg: str):
        if ok:
            self.lbl_bbg_status.setText("✓ Bloomberg: conectado")
            self.lbl_bbg_status.setObjectName("connOk")
        else:
            self.lbl_bbg_status.setText("✗ Bloomberg: offline")
            self.lbl_bbg_status.setToolTip(msg)
            self.lbl_bbg_status.setObjectName("connFail")
        self.lbl_bbg_status.style().unpolish(self.lbl_bbg_status)
        self.lbl_bbg_status.style().polish(self.lbl_bbg_status)

    def _on_conn_tests_done(self):
        self.btn_test_conn.setEnabled(True)

    # ── TAB 1: Run Once ───────────────────────────────────────────────

    def _build_run_once_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(8, 12, 8, 8)

        splitter = QSplitter(Qt.Horizontal)
        layout.addWidget(splitter, stretch=1)

        # LEFT — report selection
        left = QWidget()
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(0, 0, 8, 0)

        grp = QGroupBox("Relatórios")
        grp_lay = QVBoxLayout(grp)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("🔍 Buscar relatório...")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.textChanged.connect(self._filter_reports)
        grp_lay.addWidget(self.search_input)

        self.report_list = QListWidget()
        self.report_list.setSelectionMode(QAbstractItemView.MultiSelection)
        self.report_list.setMinimumHeight(200)
        grp_lay.addWidget(self.report_list)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.btn_clear_sel = QPushButton("Limpar Seleção")
        self.btn_clear_sel.setObjectName("secondary")
        self.btn_clear_sel.clicked.connect(self._clear_selection)
        btn_row.addWidget(self.btn_clear_sel)
        grp_lay.addLayout(btn_row)

        self.lbl_count = QLabel("0 selecionados")
        self.lbl_count.setAlignment(Qt.AlignRight)
        grp_lay.addWidget(self.lbl_count)
        self.report_list.itemSelectionChanged.connect(self._update_count)

        left_lay.addWidget(grp)
        splitter.addWidget(left)

        # RIGHT — config + log
        right = QWidget()
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(8, 0, 0, 0)

        # Options
        grp_opt = QGroupBox("Opções")
        opt_lay = QVBoxLayout(grp_opt)

        self.chk_delete = QCheckBox("Deletar dados existentes antes de atualizar")
        opt_lay.addWidget(self.chk_delete)

        date_row = QHBoxLayout()
        date_row.addWidget(QLabel("Cutoff Date:"))
        self.date_edit = QDateEdit()
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDate(QDate(1900, 1, 1))
        self.date_edit.setDisplayFormat("yyyy-MM-dd")
        date_row.addWidget(self.date_edit)
        date_row.addStretch()
        opt_lay.addLayout(date_row)

        right_lay.addWidget(grp_opt)

        # Buttons
        action_row = QHBoxLayout()

        self.btn_run = QPushButton("▶ Executar Atualização")
        self.btn_run.setObjectName("primary")
        self.btn_run.clicked.connect(self._start_update)
        action_row.addWidget(self.btn_run)

        self.btn_cancel = QPushButton("■ Cancelar")
        self.btn_cancel.setObjectName("danger")
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self._cancel_update)
        action_row.addWidget(self.btn_cancel)

        action_row.addStretch()
        right_lay.addLayout(action_row)

        # Progress
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("%v / %m  (%p%)")
        right_lay.addWidget(self.progress_bar)

        # Status
        self.lbl_status = QLabel("Pronto")
        self.lbl_status.setObjectName("status")
        self.lbl_status.setAlignment(Qt.AlignCenter)
        right_lay.addWidget(self.lbl_status)

        # Log
        grp_log = QGroupBox("Log")
        log_lay = QVBoxLayout(grp_log)

        self.log_box = QTextEdit()
        self.log_box.setObjectName("logBox")
        self.log_box.setReadOnly(True)
        log_lay.addWidget(self.log_box)

        btn_clear_log = QPushButton("Limpar Log")
        btn_clear_log.setObjectName("secondary")
        btn_clear_log.clicked.connect(self.log_box.clear)
        log_lay.addWidget(btn_clear_log, alignment=Qt.AlignRight)

        right_lay.addWidget(grp_log, stretch=1)

        splitter.addWidget(right)
        splitter.setSizes([280, 720])

        return tab

    # ── TAB 2: Schedule Runs ──────────────────────────────────────────

    def _build_schedule_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(8, 12, 8, 8)

        splitter = QSplitter(Qt.Horizontal)
        layout.addWidget(splitter, stretch=1)

        # LEFT — add new schedule
        left = QWidget()
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(0, 0, 8, 0)

        grp_add = QGroupBox("Novo Agendamento")
        add_lay = QVBoxLayout(grp_add)

        self.sched_search = QLineEdit()
        self.sched_search.setPlaceholderText("🔍 Buscar relatório...")
        self.sched_search.setClearButtonEnabled(True)
        self.sched_search.textChanged.connect(self._filter_sched_reports)
        add_lay.addWidget(self.sched_search)

        self.sched_report_list = QListWidget()
        self.sched_report_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.sched_report_list.setMinimumHeight(150)
        add_lay.addWidget(self.sched_report_list)

        # Date
        sched_run_date_row = QHBoxLayout()
        sched_run_date_row.addWidget(QLabel("Data:"))
        self.sched_run_date = QDateEdit()
        self.sched_run_date.setCalendarPopup(True)
        self.sched_run_date.setDate(QDate.currentDate())
        self.sched_run_date.setDisplayFormat("yyyy-MM-dd")
        self.sched_run_date.setMinimumDate(QDate.currentDate())
        sched_run_date_row.addWidget(self.sched_run_date)
        sched_run_date_row.addStretch()
        add_lay.addLayout(sched_run_date_row)

        # Time
        time_row = QHBoxLayout()
        time_row.addWidget(QLabel("Horário:"))
        self.sched_time = QTimeEdit()
        self.sched_time.setDisplayFormat("HH:mm")
        self.sched_time.setTime(QTime(8, 0))
        time_row.addWidget(self.sched_time)
        time_row.addStretch()
        add_lay.addLayout(time_row)

        # Options
        self.sched_chk_delete = QCheckBox("Deletar dados antes")
        add_lay.addWidget(self.sched_chk_delete)

        sched_date_row = QHBoxLayout()
        sched_date_row.addWidget(QLabel("Cutoff:"))
        self.sched_date_edit = QDateEdit()
        self.sched_date_edit.setCalendarPopup(True)
        self.sched_date_edit.setDate(QDate(1900, 1, 1))
        self.sched_date_edit.setDisplayFormat("yyyy-MM-dd")
        sched_date_row.addWidget(self.sched_date_edit)
        sched_date_row.addStretch()
        add_lay.addLayout(sched_date_row)

        # Add button
        self.btn_add_schedule = QPushButton("➕ Adicionar Agendamento")
        self.btn_add_schedule.setObjectName("primary")
        self.btn_add_schedule.clicked.connect(self._add_schedule)
        add_lay.addWidget(self.btn_add_schedule)

        left_lay.addWidget(grp_add)
        splitter.addWidget(left)

        # RIGHT — schedule table + log
        right = QWidget()
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(8, 0, 0, 0)

        # Table
        grp_table = QGroupBox("Agendamentos Ativos")
        table_lay = QVBoxLayout(grp_table)

        self.sched_table = QTableWidget()
        self.sched_table.setColumnCount(8)
        self.sched_table.setHorizontalHeaderLabels([
            "Relatório", "Data", "Horário", "Deletar", "Cutoff", "Status", "", ""
        ])
        self.sched_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.sched_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.Stretch)
        for col in [1, 2, 3, 4]:
            self.sched_table.horizontalHeader().setSectionResizeMode(col, QHeaderView.ResizeToContents)
        for col in [6, 7]:
            self.sched_table.horizontalHeader().setSectionResizeMode(col, QHeaderView.Fixed)
            self.sched_table.setColumnWidth(col, 90)
        self.sched_table.verticalHeader().setVisible(False)
        self.sched_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.sched_table.setEditTriggers(QTableWidget.NoEditTriggers)
        table_lay.addWidget(self.sched_table)

        right_lay.addWidget(grp_table)

        # Schedule log
        grp_slog = QGroupBox("Log de Agendamentos")
        slog_lay = QVBoxLayout(grp_slog)

        self.sched_log_box = QTextEdit()
        self.sched_log_box.setObjectName("logBox")
        self.sched_log_box.setReadOnly(True)
        slog_lay.addWidget(self.sched_log_box)

        btn_clear_slog = QPushButton("Limpar Log")
        btn_clear_slog.setObjectName("secondary")
        btn_clear_slog.clicked.connect(self.sched_log_box.clear)
        slog_lay.addWidget(btn_clear_slog, alignment=Qt.AlignRight)

        right_lay.addWidget(grp_slog, stretch=1)

        splitter.addWidget(right)
        splitter.setSizes([280, 720])

        return tab

    # ── Report Loading ────────────────────────────────────────────────

    def _load_reports(self):
        self._set_status("Carregando relatórios...", error=False)
        self._loader = LoadReportsWorker()
        self._loader.finished.connect(self._on_reports_loaded)
        self._loader.error.connect(self._on_reports_error)
        self._loader.start()

    def _on_reports_loaded(self, reports: list[str]):
        self._all_reports = reports

        self.report_list.clear()
        for name in reports:
            self.report_list.addItem(name)

        self.sched_report_list.clear()
        for name in reports:
            self.sched_report_list.addItem(name)
        self._add_pipelines_to_sched_list()

        self._set_status(f"Pronto — {len(reports)} relatórios disponíveis")
        self._log(f"✓ {len(reports)} relatórios carregados do banco.")

    def _on_reports_error(self, error: str):
        self._set_status("Erro ao carregar relatórios", error=True)
        self._log(f"✗ Erro: {error}")
        self._add_pipelines_to_sched_list()

    def _add_pipelines_to_sched_list(self):
        existing = {self.sched_report_list.item(i).text() for i in range(self.sched_report_list.count())}
        for key in PIPELINES:
            name = pipeline_display_name(key)
            if name not in existing:
                self.sched_report_list.addItem(name)

    # ── Filtering / selection (Run Once) ──────────────────────────────

    def _filter_reports(self, text: str):
        t = text.lower()
        for i in range(self.report_list.count()):
            item = self.report_list.item(i)
            item.setHidden(t not in item.text().lower())

    def _filter_sched_reports(self, text: str):
        t = text.lower()
        for i in range(self.sched_report_list.count()):
            item = self.sched_report_list.item(i)
            item.setHidden(t not in item.text().lower())

    def _clear_selection(self):
        self.report_list.clearSelection()

    def _update_count(self):
        n = len(self.report_list.selectedItems())
        self.lbl_count.setText(f"{n} selecionado{'s' if n != 1 else ''}")

    # ──────────────────────────────────────────────────────────────────────
    # RUN ONCE
    # ──────────────────────────────────────────────────────────────────────

    def _start_update(self):
        selected = [item.text() for item in self.report_list.selectedItems()]
        if not selected:
            QMessageBox.warning(self, "Atenção", "Selecione ao menos um relatório.")
            return

        if self.chk_delete.isChecked():
            reply = QMessageBox.question(
                self, "Confirmar Deleção",
                "Você marcou para DELETAR dados existentes antes de atualizar.\n\n"
                "Isso é irreversível. Deseja continuar?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return

        # UK Labor month prompt
        uk_month: str | None = None
        if UK_LABOR_REPORT_NAME in selected:
            uk_month = self._ask_uk_month()
            if uk_month is None:
                return

        config = UpdateConfig(
            reports=selected,
            delete_before_update=self.chk_delete.isChecked(),
            cutoff_date=self.date_edit.date().toString("yyyy-MM-dd"),
            uk_labor_month=uk_month,
        )

        self.log_box.clear()
        self.progress_bar.setValue(0)
        self.progress_bar.setMaximum(0)

        self._log(f"Iniciando atualização de {len(selected)} relatório(s)...")
        for r in selected:
            self._log(f"  • {r}")
        if uk_month:
            self._log(f"  🇬🇧 UK Employment month: {uk_month}")

        # Create worker (engine is built immediately inside __init__)
        self._worker = UpdateWorker(config)
        self._worker.log_signal.connect(self._log)
        self._worker.progress_signal.connect(self._on_progress)
        self._worker.finished_signal.connect(self._on_finished)
        self._worker.summary_signal.connect(self._log)

        # Enable cancel BEFORE starting the thread
        self._set_running(True)
        self._worker.start()

    def _cancel_update(self):
        if self._worker:
            self._log("\n⏳ Solicitando cancelamento...")
            self._worker.cancel()

    def _on_progress(self, current: int, total: int):
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(current)

    def _on_finished(self, success: bool, message: str):
        self._set_running(False)
        if not success:
            self.progress_bar.setMaximum(1)
            self.progress_bar.setValue(0)
        self._set_status(
            f"✓ {message}" if success else f"✗ {message}",
            error=not success,
        )

    def _set_running(self, running: bool):
        self.btn_run.setEnabled(not running)
        self.btn_cancel.setEnabled(running)
        self.report_list.setEnabled(not running)
        self.search_input.setEnabled(not running)
        self.chk_delete.setEnabled(not running)
        self.date_edit.setEnabled(not running)
        self.btn_clear_sel.setEnabled(not running)
        if running:
            self._set_status("Executando...")

    # ──────────────────────────────────────────────────────────────────────
    # SCHEDULE RUNS
    # ──────────────────────────────────────────────────────────────────────

    def _add_schedule(self):
        selected = self.sched_report_list.selectedItems()
        if not selected:
            QMessageBox.warning(self, "Atenção", "Selecione um relatório.")
            return

        report = selected[0].text()
        t = self.sched_time.time()
        scheduled_time = dtime(t.hour(), t.minute())

        qd = self.sched_run_date.date()
        scheduled_date = ddate(qd.year(), qd.month(), qd.day())

        pipeline_key = pipeline_key_from_display(report)

        # UK Labor month prompt
        uk_month: str | None = None
        if report == UK_LABOR_REPORT_NAME:
            uk_month = self._ask_uk_month()
            if uk_month is None:
                return

        job_id = uuid.uuid4().hex[:8]
        job = ScheduleJob(
            job_id=job_id,
            report=report,
            scheduled_date=scheduled_date,
            scheduled_time=scheduled_time,
            delete_before=False if pipeline_key else self.sched_chk_delete.isChecked(),
            cutoff_date="—" if pipeline_key else self.sched_date_edit.date().toString("yyyy-MM-dd"),
            uk_labor_month=uk_month,
            pipeline_key=pipeline_key,
        )
        self._jobs[job_id] = job
        self._refresh_schedule_table()
        self._sched_log(
            f"✓ Agendamento criado: '{report}' em "
            f"{scheduled_date.strftime('%Y-%m-%d')} às {scheduled_time.strftime('%H:%M')}"
        )
        if uk_month:
            self._sched_log(f"  🇬🇧 UK month: {uk_month}")
        if pipeline_key:
            self._sched_log("  ⚙ Pipeline local: usa as opções da aba 'Rodagem Local' no momento da execução")

        if not self._schedule_timer.isActive():
            self._schedule_timer.start()
            self._sched_log("⏰ Scheduler iniciado.")

    def _remove_schedule(self, job_id: str):
        job = self._jobs.get(job_id)
        if not job:
            return

        if job.worker and job.worker.isRunning():
            job.worker.cancel()
            job.worker.wait(3000)

        name = job.report
        del self._jobs[job_id]
        self._refresh_schedule_table()
        self._sched_log(f"✗ Agendamento removido: '{name}'")

        if not self._jobs:
            self._schedule_timer.stop()
            self._sched_log("⏰ Scheduler parado (nenhum agendamento ativo).")

    def _stop_schedule_job(self, job_id: str):
        job = self._jobs.get(job_id)
        if not job:
            return
        if job.worker:
            self._sched_log(f"⏳ Cancelando execução de '{job.report}'...")
            job.worker.cancel()
            job.status = "Cancelando..."
            self._refresh_schedule_table()

    def _refresh_schedule_table(self):
        self.sched_table.setRowCount(0)
        for job in self._jobs.values():
            row = self.sched_table.rowCount()
            self.sched_table.insertRow(row)

            self.sched_table.setItem(row, 0, QTableWidgetItem(job.report))
            self.sched_table.setItem(row, 1, QTableWidgetItem(job.scheduled_date.strftime("%Y-%m-%d")))
            self.sched_table.setItem(row, 2, QTableWidgetItem(job.scheduled_time.strftime("%H:%M")))
            self.sched_table.setItem(row, 3, QTableWidgetItem("Sim" if job.delete_before else "Não"))
            self.sched_table.setItem(row, 4, QTableWidgetItem(job.cutoff_date))

            status_item = QTableWidgetItem(job.status)
            if "Executando" in job.status:
                status_item.setForeground(QColor("#89b4fa"))
            elif "Concluído" in job.status:
                status_item.setForeground(QColor("#a6e3a1"))
            elif "Erro" in job.status or "Cancelado" in job.status:
                status_item.setForeground(QColor("#f38ba8"))
            else:
                status_item.setForeground(QColor("#6c7086"))
            self.sched_table.setItem(row, 5, status_item)

            # Stop button — enabled whenever the job has a worker and is executing
            btn_stop = QPushButton("Parar")
            btn_stop.setObjectName("stop")
            is_active = job.worker is not None and job.status.startswith("Executando")
            btn_stop.setEnabled(is_active)
            jid = job.job_id
            btn_stop.clicked.connect(lambda _, j=jid: self._stop_schedule_job(j))
            self.sched_table.setCellWidget(row, 6, btn_stop)

            # Remove button
            btn_remove = QPushButton("Remover")
            btn_remove.setObjectName("remove")
            btn_remove.clicked.connect(lambda _, j=jid: self._remove_schedule(j))
            self.sched_table.setCellWidget(row, 7, btn_remove)

    def _tick_schedule(self):
        now = datetime.now()
        now_date = now.date()
        now_time = now.time().replace(second=0, microsecond=0)

        expired_ids = [
            jid for jid, job in self._jobs.items()
            if job.has_run and job.scheduled_date < now_date
            and (job.worker is None or not job.worker.isRunning())
        ]
        for jid in expired_ids:
            del self._jobs[jid]
        if expired_ids:
            self._refresh_schedule_table()

        for job in list(self._jobs.values()):
            if job.worker and job.worker.isRunning():
                continue
            if job.has_run:
                continue
            if job.scheduled_date != now_date:
                continue

            sched = job.scheduled_time
            diff_seconds = abs(
                (now_time.hour * 3600 + now_time.minute * 60)
                - (sched.hour * 3600 + sched.minute * 60)
            )
            if diff_seconds <= 30:
                self._run_scheduled_job(job)

        if not self._jobs:
            self._schedule_timer.stop()
            self._sched_log("⏰ Scheduler parado (nenhum agendamento ativo).")

    def _run_scheduled_job(self, job: ScheduleJob):
        job.status = "Executando..."
        job.has_run = True
        self._sched_log(f"\n▶ Iniciando execução agendada: '{job.report}'")

        if job.pipeline_key:
            worker = LocalPipelineWorker(self._local_run_config([job.pipeline_key]))
            job.worker = worker
            worker.log_signal.connect(self._sched_log)
        else:
            config = UpdateConfig(
                reports=[job.report],
                delete_before_update=job.delete_before,
                cutoff_date=job.cutoff_date,
                uk_labor_month=job.uk_labor_month,
            )
            # Create worker (engine built immediately in __init__)
            worker = UpdateWorker(config)
            job.worker = worker
            worker.log_signal.connect(self._sched_log)
            worker.summary_signal.connect(self._sched_log)

        jid = job.job_id
        worker.progress_signal.connect(
            lambda c, t, j=jid: self._on_sched_progress(j, c, t)
        )
        worker.finished_signal.connect(
            lambda ok, msg, j=jid: self._on_sched_finished(j, ok, msg)
        )

        # Refresh table AFTER worker is assigned so Stop button sees it
        self._refresh_schedule_table()
        worker.start()

    def _on_sched_progress(self, job_id: str, current: int, total: int):
        job = self._jobs.get(job_id)
        if job:
            job.status = f"Executando... {current}/{total}"
            self._refresh_schedule_table()

    def _on_sched_finished(self, job_id: str, success: bool, message: str):
        job = self._jobs.get(job_id)
        if not job:
            return
        if success:
            job.status = f"✓ Concluído — {message}"
        else:
            job.status = f"✗ {message}"
        job.worker = None
        self._refresh_schedule_table()
        self._sched_log(
            f"{'✓' if success else '✗'} '{job.report}': {message}"
        )

    # ──────────────────────────────────────────────────────────────────────
    # TAB 3: Rodagem Local (pipelines do python_tools)
    # ──────────────────────────────────────────────────────────────────────

    def _build_local_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(8, 12, 8, 8)

        splitter = QSplitter(Qt.Horizontal)
        layout.addWidget(splitter, stretch=1)

        # LEFT — pipelines + opções + configuração
        left = QWidget()
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(0, 0, 8, 0)

        grp_pipes = QGroupBox("Pipelines (python_tools)")
        pipes_lay = QVBoxLayout(grp_pipes)
        self.local_pipe_checks: dict[str, QCheckBox] = {}
        for key, p in PIPELINES.items():
            chk = QCheckBox(f"{p.name}   —   release: {p.release_hint}")
            chk.stateChanged.connect(self._refresh_local_plan)
            pipes_lay.addWidget(chk)
            self.local_pipe_checks[key] = chk
        left_lay.addWidget(grp_pipes)

        grp_opt = QGroupBox("Opções")
        opt_lay = QVBoxLayout(grp_opt)

        scope_row = QHBoxLayout()
        scope_row.addWidget(QLabel("Escopo:"))
        self.local_scope = QComboBox()
        self.local_scope.addItem("Dashboard (subset dos runbooks)", "dashboard")
        self.local_scope.addItem("Full (todas as categorias)", "full")
        self.local_scope.currentIndexChanged.connect(self._refresh_local_plan)
        scope_row.addWidget(self.local_scope)
        scope_row.addStretch()
        opt_lay.addLayout(scope_row)

        self.local_chk_sa = QCheckBox("IPCA / IPCA-15: carregar também idx SA (X-13 + fixes)")
        self.local_chk_sa.setChecked(True)
        self.local_chk_extras = QCheckBox("CPI-U: alt measures + bottom-up + difusão + breadth")
        self.local_chk_extras.setChecked(True)
        self.local_chk_oer = QCheckBox("CPI-U: OER regional")
        self.local_chk_fed = QCheckBox("PCE: alt measures scraped (Cleveland/Dallas já publicaram)")
        self.local_chk_dry = QCheckBox("Dry-run: loaders só listam, nada é gravado no SQL")
        for c in (self.local_chk_sa, self.local_chk_extras, self.local_chk_oer,
                  self.local_chk_fed, self.local_chk_dry):
            c.stateChanged.connect(self._refresh_local_plan)
            opt_lay.addWidget(c)
        left_lay.addWidget(grp_opt)

        grp_cfg = QGroupBox("Configuração")
        cfg_lay = QVBoxLayout(grp_cfg)

        dir_row = QHBoxLayout()
        dir_row.addWidget(QLabel("Pasta python_tools:"))
        self.local_dir_edit = QLineEdit(self._local_settings.get("python_tools_dir", ""))
        self.local_dir_edit.setPlaceholderText(r"ex.: C:\dev\python_tools")
        dir_row.addWidget(self.local_dir_edit, stretch=1)
        btn_browse = QPushButton("…")
        btn_browse.setObjectName("secondary")
        btn_browse.setFixedWidth(36)
        btn_browse.clicked.connect(self._browse_python_tools)
        dir_row.addWidget(btn_browse)
        cfg_lay.addLayout(dir_row)

        r_row = QHBoxLayout()
        r_row.addWidget(QLabel("Rscript:"))
        self.local_rscript_edit = QLineEdit(self._local_settings.get("rscript_cmd", "Rscript"))
        self.local_rscript_edit.setPlaceholderText("Rscript  (ou caminho completo do Rscript.exe)")
        r_row.addWidget(self.local_rscript_edit, stretch=1)
        cfg_lay.addLayout(r_row)

        py_row = QHBoxLayout()
        py_row.addWidget(QLabel("Python:"))
        self.local_python_edit = QLineEdit(self._local_settings.get("python_exe", ""))
        self.local_python_edit.setPlaceholderText("vazio = o Python que está rodando o app")
        py_row.addWidget(self.local_python_edit, stretch=1)
        cfg_lay.addLayout(py_row)

        keys_row = QHBoxLayout()
        keys_row.addWidget(QLabel("BLS_API_KEY:"))
        self.local_bls_edit = QLineEdit(self._local_settings.get("BLS_API_KEY", ""))
        self.local_bls_edit.setEchoMode(QLineEdit.Password)
        keys_row.addWidget(self.local_bls_edit, stretch=1)
        keys_row.addWidget(QLabel("BEA_API_KEY:"))
        self.local_bea_edit = QLineEdit(self._local_settings.get("BEA_API_KEY", ""))
        self.local_bea_edit.setEchoMode(QLineEdit.Password)
        keys_row.addWidget(self.local_bea_edit, stretch=1)
        cfg_lay.addLayout(keys_row)

        save_row = QHBoxLayout()
        self.lbl_local_cfg = QLabel(f"salvo em {settings_path()}")
        self.lbl_local_cfg.setObjectName("subtitle")
        save_row.addWidget(self.lbl_local_cfg, stretch=1)
        self.btn_local_check = QPushButton("🔍 Testar ambiente")
        self.btn_local_check.setObjectName("testConn")
        self.btn_local_check.clicked.connect(self._check_local_environment)
        save_row.addWidget(self.btn_local_check)
        btn_save = QPushButton("💾 Salvar configuração")
        btn_save.setObjectName("secondary")
        btn_save.clicked.connect(self._save_local_settings)
        save_row.addWidget(btn_save)
        cfg_lay.addLayout(save_row)

        left_lay.addWidget(grp_cfg)
        left_lay.addStretch()
        splitter.addWidget(left)

        # RIGHT — plano + botões + progresso + log
        right = QWidget()
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(8, 0, 0, 0)

        action_row = QHBoxLayout()
        self.btn_local_run = QPushButton("▶ Rodar Pipelines")
        self.btn_local_run.setObjectName("primary")
        self.btn_local_run.clicked.connect(self._start_local_run)
        action_row.addWidget(self.btn_local_run)

        self.btn_local_cancel = QPushButton("■ Cancelar")
        self.btn_local_cancel.setObjectName("danger")
        self.btn_local_cancel.setEnabled(False)
        self.btn_local_cancel.clicked.connect(self._cancel_local_run)
        action_row.addWidget(self.btn_local_cancel)
        action_row.addStretch()
        right_lay.addLayout(action_row)

        self.local_progress = QProgressBar()
        self.local_progress.setValue(0)
        self.local_progress.setFormat("%v / %m passos  (%p%)")
        right_lay.addWidget(self.local_progress)

        self.lbl_local_status = QLabel("Selecione um ou mais pipelines")
        self.lbl_local_status.setObjectName("status")
        self.lbl_local_status.setAlignment(Qt.AlignCenter)
        right_lay.addWidget(self.lbl_local_status)

        grp_plan = QGroupBox("Passos planejados")
        plan_lay = QVBoxLayout(grp_plan)
        self.local_plan_list = QListWidget()
        self.local_plan_list.setSelectionMode(QAbstractItemView.NoSelection)
        self.local_plan_list.setMaximumHeight(170)
        plan_lay.addWidget(self.local_plan_list)
        right_lay.addWidget(grp_plan)

        grp_log = QGroupBox("Log")
        log_lay = QVBoxLayout(grp_log)
        self.local_log_box = QTextEdit()
        self.local_log_box.setObjectName("logBox")
        self.local_log_box.setReadOnly(True)
        log_lay.addWidget(self.local_log_box)
        btn_clear = QPushButton("Limpar Log")
        btn_clear.setObjectName("secondary")
        btn_clear.clicked.connect(self.local_log_box.clear)
        log_lay.addWidget(btn_clear, alignment=Qt.AlignRight)
        right_lay.addWidget(grp_log, stretch=1)

        splitter.addWidget(right)
        splitter.setSizes([420, 600])
        return tab

    def _local_options(self) -> PipelineOptions:
        return PipelineOptions(
            scope=self.local_scope.currentData() or "dashboard",
            sa=self.local_chk_sa.isChecked(),
            cpius_extras=self.local_chk_extras.isChecked(),
            cpius_oer=self.local_chk_oer.isChecked(),
            pce_fed=self.local_chk_fed.isChecked(),
        )

    def _local_settings_from_form(self) -> dict:
        cfg = dict(self._local_settings)
        cfg.update({
            "python_tools_dir": self.local_dir_edit.text().strip(),
            "rscript_cmd": self.local_rscript_edit.text().strip() or "Rscript",
            "python_exe": self.local_python_edit.text().strip(),
            "BLS_API_KEY": self.local_bls_edit.text().strip(),
            "BEA_API_KEY": self.local_bea_edit.text().strip(),
        })
        return cfg

    def _local_run_config(self, keys: list[str]) -> LocalRunConfig:
        return LocalRunConfig(
            pipelines=keys,
            options=self._local_options(),
            dry_run=self.local_chk_dry.isChecked(),
            settings=self._local_settings_from_form(),
        )

    def _selected_pipelines(self) -> list[str]:
        return [k for k, c in self.local_pipe_checks.items() if c.isChecked()]

    def _refresh_local_plan(self, *_):
        self.local_plan_list.clear()
        keys = self._selected_pipelines()
        if not keys:
            return
        steps = plan_steps(self._local_run_config(keys))
        for i, st in enumerate(steps, 1):
            icon = {"load": "💾", "fix": "🔧"}.get(st.kind, "⬇")
            self.local_plan_list.addItem(f"{i:>2}. {icon} {st.label}")
        self.lbl_local_status.setText(f"{len(steps)} passos planejados")

    def _browse_python_tools(self):
        d = QFileDialog.getExistingDirectory(self, "Pasta do python_tools", self.local_dir_edit.text())
        if d:
            self.local_dir_edit.setText(d)

    def _check_local_environment(self):
        """Roda python -c / Rscript --version com a configuração atual e mostra
        um resultado legível no log (pensado para quem não programa)."""
        self.btn_local_check.setEnabled(False)
        self._local_log("\n🔍 Testando ambiente da Rodagem Local...")
        settings = self._local_settings_from_form()
        keys = self._selected_pipelines() or None
        worker = _EnvCheckWorker(settings, keys, self)
        worker.result.connect(self._on_local_env_checked)
        self._env_worker = worker
        worker.start()

    def _on_local_env_checked(self, results: list):
        ok_all = True
        for ok, msg in results:
            ok_all &= ok
            self._local_log(f"  {'✓' if ok else '✗'} {msg}")
        self._local_log("  → Ambiente pronto. Pode rodar." if ok_all
                        else "  → Corrija os itens com ✗ acima (campos da Configuração) e teste de novo.")
        self.btn_local_check.setEnabled(True)

    def _save_local_settings(self):
        self._local_settings = self._local_settings_from_form()
        try:
            save_settings(self._local_settings)
            self._local_log(f"✓ Configuração salva em {settings_path()}")
        except Exception as e:
            QMessageBox.warning(self, "Erro", f"Não foi possível salvar a configuração:\n{e}")

    def _start_local_run(self):
        keys = self._selected_pipelines()
        if not keys:
            QMessageBox.warning(self, "Atenção", "Selecione ao menos um pipeline.")
            return
        cfg = self._local_run_config(keys)
        if not cfg.dry_run:
            names = "\n".join(f"  • {PIPELINES[k].name}" for k in keys)
            reply = QMessageBox.question(
                self, "Confirmar carga no SQL",
                f"Os loaders vão gravar no SQL corp (OPT_Macro_Series_2 / _Data_2):\n\n{names}\n\n"
                "Escopo: " + ("FULL" if cfg.options.scope == "full" else "dashboard") + ". Continuar?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return

        self._local_settings = cfg.settings
        self.local_log_box.clear()
        self.local_progress.setValue(0)
        self.local_progress.setMaximum(0)

        self._local_worker = LocalPipelineWorker(cfg)
        self._local_worker.log_signal.connect(self._local_log)
        self._local_worker.progress_signal.connect(self._on_local_progress)
        self._local_worker.finished_signal.connect(self._on_local_finished)
        self._set_local_running(True)
        self._local_worker.start()

    def _cancel_local_run(self):
        if self._local_worker:
            self._local_log("\n⏳ Cancelando (encerra o passo em execução)...")
            self._local_worker.cancel()

    def _on_local_progress(self, current: int, total: int):
        self.local_progress.setMaximum(total)
        self.local_progress.setValue(current)

    def _on_local_finished(self, success: bool, message: str):
        self._set_local_running(False)
        if not success and self.local_progress.maximum() == 0:
            self.local_progress.setMaximum(1)
        self.lbl_local_status.setText(f"✓ {message}" if success else f"✗ {message}")
        self.lbl_local_status.setObjectName("status" if success else "statusError")
        self.lbl_local_status.style().unpolish(self.lbl_local_status)
        self.lbl_local_status.style().polish(self.lbl_local_status)

    def _set_local_running(self, running: bool):
        self.btn_local_run.setEnabled(not running)
        self.btn_local_cancel.setEnabled(running)
        for c in self.local_pipe_checks.values():
            c.setEnabled(not running)
        if running:
            self.lbl_local_status.setText("Executando...")
            self.lbl_local_status.setObjectName("status")
            self.lbl_local_status.style().unpolish(self.lbl_local_status)
            self.lbl_local_status.style().polish(self.lbl_local_status)

    def _local_log(self, message: str):
        self.local_log_box.append(message)
        self.local_log_box.moveCursor(QTextCursor.End)

    # ──────────────────────────────────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────────────────────────────────

    def _set_status(self, text: str, error: bool = False):
        self.lbl_status.setText(text)
        self.lbl_status.setObjectName("statusError" if error else "status")
        self.lbl_status.style().unpolish(self.lbl_status)
        self.lbl_status.style().polish(self.lbl_status)

    def _log(self, message: str):
        self.log_box.append(message)
        self.log_box.moveCursor(QTextCursor.End)

    def _sched_log(self, message: str):
        ts = datetime.now().strftime("%H:%M:%S")
        self.sched_log_box.append(f"[{ts}] {message}")
        self.sched_log_box.moveCursor(QTextCursor.End)
