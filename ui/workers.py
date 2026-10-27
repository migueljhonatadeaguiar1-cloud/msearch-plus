"""Threads de fundo (a interface nunca trava durante indexação ou checagem de rede)."""
from __future__ import annotations

import threading

from PyQt6.QtCore import QThread, pyqtSignal


class CrawlWorker(QThread):
    event = pyqtSignal(str, str)
    finished_stats = pyqtSignal(object)

    def __init__(self, service, seeds: list[str], max_pages: int, max_depth: int, parent=None):
        super().__init__(parent)
        self.service, self.seeds, self.max_pages, self.max_depth = service, seeds, max_pages, max_depth
        self._stop_event = threading.Event()

    def request_stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:
        stats = None
        try:
            stats = self.service.crawl(self.seeds, max_pages=self.max_pages, max_depth=self.max_depth,
                                       stop_event=self._stop_event,
                                       on_event=lambda kind, msg: self.event.emit(kind, msg))
        except Exception as exc:  # mostra o erro no log em vez de derrubar o app
            self.event.emit("error", str(exc))
        self.finished_stats.emit(stats)


class ConnectivityWorker(QThread):
    changed = pyqtSignal(bool)

    def __init__(self, service, parent=None):
        super().__init__(parent)
        self.service = service
        self._wake = threading.Event()
        self._running = True

    def probe_now(self) -> None:
        self._wake.set()

    def stop(self) -> None:
        self._running = False
        self._wake.set()

    def run(self) -> None:
        while self._running:
            self.changed.emit(self.service.connectivity.probe())
            self._wake.wait(max(5, self.service.settings.connectivity_interval_s))
            self._wake.clear()


class SaveWorker(QThread):
    """Salva uma página completa (HTML + CSS + JS + imagens + fontes) para uso offline."""
    progress = pyqtSignal(int, str)
    done = pyqtSignal(object, str)         # (SaveReport | None, mensagem de erro)

    def __init__(self, service, url: str, parent=None):
        super().__init__(parent)
        self.service, self.url = service, url
        self._stop_event = threading.Event()

    def request_stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:
        try:
            report = self.service.save_page_offline(
                self.url, stop_event=self._stop_event, on_progress=lambda n, u: self.progress.emit(n, u))
            self.done.emit(report, "")
        except Exception as exc:
            self.done.emit(None, str(exc))
