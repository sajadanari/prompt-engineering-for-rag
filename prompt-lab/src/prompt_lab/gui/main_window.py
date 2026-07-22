"""Main window: workspace editors, run controls, and result panes."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QThread, Slot
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QStatusBar,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from prompt_lab.assembler import assemble_messages
from prompt_lab.config import SUPPORTED_LANGUAGES, WORKSPACE_DIR, ConfigError, load_config
from prompt_lab.logging_util import LOGS_DIR
from prompt_lab.workspace import init_workspace

from .log_view import configure_log_browser, show_log_text
from .worker import ApiWorker


EDITOR_KEYS = (
    ("system_prompt", "system_prompt.md"),
    ("few_shot", "few_shot.md"),
    ("reminder", "reminder.md"),
    ("context", "context.yaml"),
    ("questions", "questions.yaml"),
)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("prompt-lab")
        self.resize(1280, 800)

        self._thread: QThread | None = None
        self._worker: ApiWorker | None = None
        self._busy = False
        self.editors: dict[str, QPlainTextEdit] = {}

        self._build_toolbar()
        self._build_central()
        self.lang_combo.currentTextChanged.connect(self._on_lang_changed)
        self.setStatusBar(QStatusBar())
        self._set_status("idle")

        self._reload_editors()
        self._refresh_logs()

    # ------------------------------------------------------------------ UI
    def _build_toolbar(self) -> None:
        tb = QToolBar("Main")
        tb.setMovable(False)
        self.addToolBar(tb)

        tb.addWidget(QLabel(" Lang "))
        self.lang_combo = QComboBox()
        self.lang_combo.addItems(list(SUPPORTED_LANGUAGES))
        tb.addWidget(self.lang_combo)

        tb.addWidget(QLabel("  Model "))
        self.model_edit = QLineEdit()
        self.model_edit.setPlaceholderText("(from config.yaml)")
        self.model_edit.setMinimumWidth(160)
        tb.addWidget(self.model_edit)

        self.no_context = QCheckBox("No context")
        tb.addWidget(self.no_context)

        tb.addSeparator()
        self.btn_init = QPushButton("Init")
        self.btn_reload = QPushButton("Reload")
        tb.addWidget(self.btn_init)
        tb.addWidget(self.btn_reload)

        self.btn_init.clicked.connect(self._on_init)
        self.btn_reload.clicked.connect(self._reload_editors)

        # Seed defaults from config if present (block signals — editors not ready yet)
        try:
            cfg = load_config()
            idx = self.lang_combo.findText(cfg.language)
            if idx >= 0:
                self.lang_combo.blockSignals(True)
                self.lang_combo.setCurrentIndex(idx)
                self.lang_combo.blockSignals(False)
            self.model_edit.setText(cfg.model)
        except ConfigError:
            pass

    def _build_central(self) -> None:
        root = QWidget()
        layout = QVBoxLayout(root)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left: editors
        self.editor_tabs = QTabWidget()
        mono = QFont("Consolas")
        mono.setStyleHint(QFont.StyleHint.Monospace)
        mono.setPointSize(10)
        for key, label in EDITOR_KEYS:
            edit = QPlainTextEdit()
            edit.setFont(mono)
            edit.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
            self.editors[key] = edit
            self.editor_tabs.addTab(edit, label)
        splitter.addWidget(self.editor_tabs)

        # Right: results
        self.result_tabs = QTabWidget()

        self.response_view = QPlainTextEdit()
        self.response_view.setReadOnly(True)
        self.response_view.setFont(mono)
        self.result_tabs.addTab(self.response_view, "Response")

        self.prompt_view = QPlainTextEdit()
        self.prompt_view.setReadOnly(True)
        self.prompt_view.setFont(mono)
        self.result_tabs.addTab(self.prompt_view, "Assembled prompt")

        batch_page = QWidget()
        batch_layout = QVBoxLayout(batch_page)
        self.batch_table = QTableWidget(0, 5)
        self.batch_table.setHorizontalHeaderLabels(
            ["#", "Question", "Note", "Answer", "Tokens"]
        )
        self.batch_table.horizontalHeader().setStretchLastSection(True)
        batch_layout.addWidget(self.batch_table)
        self.result_tabs.addTab(batch_page, "Batch results")

        logs_page = QWidget()
        logs_layout = QHBoxLayout(logs_page)
        self.log_list = QListWidget()
        self.log_preview = QTextBrowser()
        configure_log_browser(self.log_preview)
        logs_layout.addWidget(self.log_list, 1)
        logs_layout.addWidget(self.log_preview, 3)
        self.log_list.currentTextChanged.connect(self._on_log_selected)
        self.result_tabs.addTab(logs_page, "Logs")

        splitter.addWidget(self.result_tabs)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter, stretch=1)

        # Bottom bar: question + actions
        bottom = QHBoxLayout()
        bottom.addWidget(QLabel("Question:"))
        self.question_edit = QLineEdit()
        self.question_edit.setPlaceholderText("Ask a question…")
        bottom.addWidget(self.question_edit, stretch=1)

        self.btn_show = QPushButton("Show prompt")
        self.btn_run = QPushButton("Run")
        self.btn_batch = QPushButton("Batch")
        bottom.addWidget(self.btn_show)
        bottom.addWidget(self.btn_run)
        bottom.addWidget(self.btn_batch)
        layout.addLayout(bottom)

        self.btn_show.clicked.connect(self._on_show_prompt)
        self.btn_run.clicked.connect(self._on_run)
        self.btn_batch.clicked.connect(self._on_batch)

        self.setCentralWidget(root)

    # -------------------------------------------------------------- helpers
    def _set_status(self, text: str) -> None:
        self.statusBar().showMessage(text)

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        for btn in (
            self.btn_run,
            self.btn_batch,
            self.btn_show,
            self.btn_init,
            self.btn_reload,
        ):
            btn.setEnabled(not busy)

    def _current_lang(self) -> str:
        return self.lang_combo.currentText()

    def _lang_dir(self) -> Path:
        return WORKSPACE_DIR / self._current_lang()

    def _include_context(self) -> bool:
        return not self.no_context.isChecked()

    def _build_config(self):
        model = self.model_edit.text().strip() or None
        return load_config(language=self._current_lang(), model=model)

    def _save_editors(self) -> None:
        lang_dir = self._lang_dir()
        lang_dir.mkdir(parents=True, exist_ok=True)
        for key, filename in EDITOR_KEYS:
            path = lang_dir / filename
            path.write_text(self.editors[key].toPlainText(), encoding="utf-8")

    def _reload_editors(self) -> None:
        lang_dir = self._lang_dir()
        for key, filename in EDITOR_KEYS:
            path = lang_dir / filename
            if path.exists():
                self.editors[key].setPlainText(path.read_text(encoding="utf-8"))
            else:
                self.editors[key].setPlainText("")
        self._set_status(f"Loaded workspace/{self._current_lang()}/")

    def _on_lang_changed(self, _lang: str) -> None:
        if not self._busy:
            self._reload_editors()

    def _format_messages(self, messages: list[dict]) -> str:
        parts: list[str] = []
        for msg in messages:
            role = msg.get("role", "?")
            content = msg.get("content", "")
            parts.append(f"===== {role.upper()} =====\n{content}\n")
        return "\n".join(parts)

    def _refresh_logs(self) -> None:
        self.log_list.clear()
        if not LOGS_DIR.exists():
            return
        files = sorted(LOGS_DIR.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
        for path in files:
            self.log_list.addItem(path.name)

    # -------------------------------------------------------------- actions
    @Slot()
    def _on_init(self) -> None:
        exists = WORKSPACE_DIR.exists() and any(WORKSPACE_DIR.iterdir())
        force = False
        if exists:
            reply = QMessageBox.question(
                self,
                "Init workspace",
                "Workspace already has files.\n\n"
                "Yes = overwrite with templates (force)\n"
                "No = copy only missing files\n"
                "Cancel = abort",
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.No
                | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.Cancel:
                return
            force = reply == QMessageBox.StandardButton.Yes

        try:
            copied = init_workspace(list(SUPPORTED_LANGUAGES), force=force)
        except ConfigError as exc:
            QMessageBox.critical(self, "Init failed", str(exc))
            return

        self._reload_editors()
        msg = f"Init complete ({len(copied)} file(s))."
        self._set_status(msg)
        QMessageBox.information(self, "Init", msg)

    @Slot()
    def _on_show_prompt(self) -> None:
        question = self.question_edit.text().strip()
        if not question:
            QMessageBox.warning(self, "Show prompt", "Enter a question first.")
            return
        try:
            self._save_editors()
            config = self._build_config()
            messages = assemble_messages(
                config, question, include_context=self._include_context()
            )
        except (ConfigError, OSError, ValueError) as exc:
            QMessageBox.critical(self, "Show prompt failed", str(exc))
            return

        self.prompt_view.setPlainText(self._format_messages(messages))
        self.result_tabs.setCurrentWidget(self.prompt_view)
        self._set_status("Assembled prompt (no API call)")

    @Slot()
    def _on_run(self) -> None:
        if self._busy:
            return
        question = self.question_edit.text().strip()
        if not question:
            QMessageBox.warning(self, "Run", "Enter a question first.")
            return
        try:
            self._save_editors()
            config = self._build_config()
        except (ConfigError, OSError) as exc:
            QMessageBox.critical(self, "Run failed", str(exc))
            return

        self._start_worker(
            lambda w: w.run_single(config, question, self._include_context())
        )
        self._set_status("running…")

    @Slot()
    def _on_batch(self) -> None:
        if self._busy:
            return
        try:
            self._save_editors()
            config = self._build_config()
        except (ConfigError, OSError) as exc:
            QMessageBox.critical(self, "Batch failed", str(exc))
            return

        self._start_worker(lambda w: w.run_batch(config, self._include_context()))
        self._set_status("batch running…")

    def _start_worker(self, starter) -> None:
        self._set_busy(True)
        self._thread = QThread()
        self._worker = ApiWorker()
        self._worker.moveToThread(self._thread)

        self._worker.progress.connect(self._set_status)
        self._worker.failed.connect(self._on_worker_failed)
        self._worker.finished_single.connect(self._on_single_done)
        self._worker.finished_batch.connect(self._on_batch_done)

        self._thread.started.connect(lambda: starter(self._worker))
        self._worker.finished_single.connect(self._thread.quit)
        self._worker.finished_batch.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.finished.connect(self._cleanup_worker)
        self._thread.start()

    def _cleanup_worker(self) -> None:
        if self._worker is not None:
            self._worker.deleteLater()
            self._worker = None
        if self._thread is not None:
            self._thread.deleteLater()
            self._thread = None
        self._set_busy(False)

    @Slot(str)
    def _on_worker_failed(self, message: str) -> None:
        QMessageBox.critical(self, "Error", message)
        self._set_status("error")

    @Slot(dict)
    def _on_single_done(self, payload: dict) -> None:
        meta_lines = [
            f"Model: {payload.get('model')}",
            f"Tokens: prompt={payload.get('prompt_tokens')}  "
            f"completion={payload.get('completion_tokens')}",
            f"Finish: {payload.get('finish_reason')}",
            f"Elapsed: {payload.get('elapsed', 0):.2f}s",
        ]
        if payload.get("used_fallback_key"):
            meta_lines.append("Used fallback API key")
        body = payload.get("answer", "")
        self.response_view.setPlainText("\n".join(meta_lines) + "\n\n" + body)
        self.prompt_view.setPlainText(self._format_messages(payload.get("messages") or []))
        self.result_tabs.setCurrentWidget(self.response_view)

        log_path = payload.get("log_path", "")
        self._set_status(f"done — log: {log_path}")
        self._refresh_logs()

    @Slot(dict)
    def _on_batch_done(self, payload: dict) -> None:
        rows = payload.get("rows") or []
        self.batch_table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            answer = row.get("answer") or ""
            if row.get("error"):
                answer = f"[ERROR] {row['error']}"
            values = [
                str(row.get("index", r + 1)),
                row.get("question", ""),
                row.get("note", ""),
                answer,
                row.get("tokens", "-"),
            ]
            for c, value in enumerate(values):
                self.batch_table.setItem(r, c, QTableWidgetItem(value))
        self.batch_table.resizeColumnsToContents()
        self.result_tabs.setCurrentIndex(2)

        log_path = payload.get("log_path", "")
        self._set_status(f"batch done — log: {log_path}")
        self._refresh_logs()

    @Slot(str)
    def _on_log_selected(self, name: str) -> None:
        if not name:
            self.log_preview.clear()
            return
        path = LOGS_DIR / name
        if path.exists():
            show_log_text(self.log_preview, path.read_text(encoding="utf-8"))
        else:
            show_log_text(self.log_preview, "# File missing\n\n*(file missing)*")
