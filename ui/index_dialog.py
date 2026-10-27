"""Janela de indexação: seeds, limites e log do crawler."""
from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (QDialog, QFormLayout, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QSpinBox,
                             QVBoxLayout)

from core.service import SearchPlusService
from ui.workers import CrawlWorker


class IndexDialog(QDialog):
    index_changed = pyqtSignal()

    def __init__(self, service: SearchPlusService, parent=None):
        super().__init__(parent)
        self.service = service
        self.worker: CrawlWorker | None = None
        self.setWindowTitle("Indexar sites")
        self.resize(640, 560)
        s = service.settings

        info = QLabel("Informe uma URL por linha. O crawler respeita robots.txt, usa intervalo entre requisições "
                      "e só visita páginas públicas.")
        info.setWordWrap(True)
        info.setObjectName("Muted")
        self.seeds = QPlainTextEdit("\n".join(s.seeds))
        self.seeds.setPlaceholderText("https://example.com\nhttps://site.com")
        self.seeds.setFixedHeight(110)
        self.max_pages = QSpinBox()
        self.max_pages.setRange(1, 1000)
        self.max_pages.setValue(s.max_pages_per_run)
        self.depth = QSpinBox()
        self.depth.setRange(0, 5)
        self.depth.setValue(s.max_depth)
        form = QFormLayout()
        form.addRow("Máx. de páginas", self.max_pages)
        form.addRow("Profundidade", self.depth)

        self.start = QPushButton("Iniciar indexação")
        self.start.setObjectName("Primary")
        self.stop = QPushButton("Parar")
        self.stop.setEnabled(False)
        row = QHBoxLayout()
        row.addWidget(self.start)
        row.addWidget(self.stop)
        row.addStretch(1)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)

        lay = QVBoxLayout(self)
        for w in (info, self.seeds):
            lay.addWidget(w)
        lay.addLayout(form)
        lay.addLayout(row)
        lay.addWidget(self.log, 1)
        self.start.clicked.connect(self._start)
        self.stop.clicked.connect(self._stop)

    def _start(self) -> None:
        seeds = [ln.strip() for ln in self.seeds.toPlainText().splitlines() if ln.strip()]
        if not seeds:
            self.log.appendPlainText("Adicione ao menos uma URL.")
            return
        s = self.service.settings
        s.seeds, s.max_pages_per_run, s.max_depth = seeds, self.max_pages.value(), self.depth.value()
        self.service.save_settings()
        self.worker = CrawlWorker(self.service, seeds, self.max_pages.value(), self.depth.value(), self)
        self.worker.event.connect(lambda kind, msg: self.log.appendPlainText(f"[{kind}] {msg}"))
        self.worker.finished_stats.connect(self._finished)
        self.start.setEnabled(False)
        self.stop.setEnabled(True)
        self.log.appendPlainText("Iniciando…")
        self.worker.start()

    def _stop(self) -> None:
        if self.worker:
            self.worker.request_stop()
            self.stop.setEnabled(False)

    def _finished(self, stats) -> None:
        self.start.setEnabled(True)
        self.stop.setEnabled(False)
        if stats is not None:
            self.index_changed.emit()

    def reject(self) -> None:
        if self.worker and self.worker.isRunning():
            self.worker.request_stop()
            self.worker.wait(5000)
        super().reject()
