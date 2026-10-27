"""Downloads próprios do M-Search+: pasta configurável, progresso, cancelamento e aviso para arquivos perigosos."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QObject, QUrl, Qt, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWebEngineCore import QWebEngineDownloadRequest
from PyQt6.QtWidgets import (QApplication, QDialog, QFrame, QHBoxLayout, QLabel, QMessageBox, QProgressBar,
                             QPushButton, QScrollArea, QVBoxLayout, QWidget)

from offline.fsutil import is_dangerous_filename, safe_filename, unique_path

State = QWebEngineDownloadRequest.DownloadState


def default_download_dir() -> Path:
    return Path.home() / "Downloads"


class DownloadItem(QObject):
    changed = pyqtSignal()

    def __init__(self, request: QWebEngineDownloadRequest, path: Path, parent=None):
        super().__init__(parent)
        self.request, self.path = request, path
        for sig in (request.receivedBytesChanged, request.totalBytesChanged, request.stateChanged):
            sig.connect(lambda *_: self.changed.emit())

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def received(self) -> int:
        return max(0, int(self.request.receivedBytes()))

    @property
    def total(self) -> int:
        return int(self.request.totalBytes())

    @property
    def state(self):
        return self.request.state()

    @property
    def in_progress(self) -> bool:
        return self.state in (State.DownloadInProgress, State.DownloadRequested)

    def cancel(self) -> None:
        if self.in_progress:
            self.request.cancel()


class DownloadManager(QObject):
    item_added = pyqtSignal(object)

    def __init__(self, service, profile, parent=None):
        super().__init__(parent)
        self.service = service
        self.items: list[DownloadItem] = []
        profile.downloadRequested.connect(self._on_request)

    def download_dir(self) -> Path:
        chosen = self.service.settings.download_dir.strip()
        folder = Path(chosen).expanduser() if chosen else default_download_dir()
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def _on_request(self, request: QWebEngineDownloadRequest) -> None:
        name = safe_filename(request.downloadFileName() or Path(request.url().path()).name or "download", "download")
        if is_dangerous_filename(name):
            answer = QMessageBox.warning(
                QApplication.activeWindow(), "Arquivo potencialmente perigoso",
                f"“{name}” é um tipo de arquivo executável/script que pode danificar o computador.\n"
                f"Origem: {request.url().host()}\n\nBaixar mesmo assim? (O M-Search+ nunca abre arquivos baixados.)",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                request.cancel()
                return
        folder = self.download_dir()
        target = unique_path(folder, name)
        request.setDownloadDirectory(str(folder))
        request.setDownloadFileName(target.name)
        item = DownloadItem(request, target, self)
        self.items.insert(0, item)
        request.accept()
        self.item_added.emit(item)


class _Row(QFrame):
    def __init__(self, item: DownloadItem, parent=None):
        super().__init__(parent)
        self.item = item
        self.setObjectName("Card")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 8)
        self.name = QLabel(item.name)
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(8)
        self.info = QLabel()
        self.info.setObjectName("Muted")
        self.cancel = QPushButton("Cancelar")
        self.show_btn = QPushButton("Mostrar na pasta")
        self.show_btn.hide()
        row = QHBoxLayout()
        row.addWidget(self.info, 1)
        row.addWidget(self.cancel)
        row.addWidget(self.show_btn)
        for w in (self.name, self.bar):
            lay.addWidget(w)
        lay.addLayout(row)
        self.cancel.clicked.connect(item.cancel)
        self.show_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(item.path.parent))))
        item.changed.connect(self.refresh)
        self.refresh()

    @staticmethod
    def _mb(n: int) -> str:
        return f"{n / 1_048_576:.1f} MB"

    def refresh(self) -> None:
        it = self.item
        if it.total > 0:
            self.bar.setRange(0, 100)
            self.bar.setValue(int(100 * it.received / it.total))
        else:
            self.bar.setRange(0, 0 if it.in_progress else 1)
        if it.state == State.DownloadCompleted:
            self.info.setText(f"Concluído · {self._mb(it.received)} · {it.path.parent}")
            self.bar.setRange(0, 100)
            self.bar.setValue(100)
        elif it.state == State.DownloadCancelled:
            self.info.setText("Cancelado")
        elif it.state == State.DownloadInterrupted:
            self.info.setText("Interrompido (falha de rede ou de disco)")
        else:
            pct = f"{100 * it.received // it.total}% · " if it.total > 0 else ""
            self.info.setText(f"{pct}{self._mb(it.received)}" + (f" de {self._mb(it.total)}" if it.total > 0 else ""))
        self.cancel.setVisible(it.in_progress)
        self.show_btn.setVisible(it.state == State.DownloadCompleted)


class DownloadsDialog(QDialog):
    def __init__(self, manager: DownloadManager, parent=None):
        super().__init__(parent)
        self.manager = manager
        self.setWindowTitle("Downloads")
        self.resize(520, 420)
        self.setWindowModality(Qt.WindowModality.NonModal)
        self._inner = QWidget()
        self._lay = QVBoxLayout(self._inner)
        self._lay.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.empty = QLabel("Nenhum download nesta sessão.")
        self.empty.setObjectName("Muted")
        self._lay.addWidget(self.empty)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self._inner)
        self.folder_label = QLabel()
        self.folder_label.setObjectName("Muted")
        root = QVBoxLayout(self)
        root.addWidget(scroll, 1)
        root.addWidget(self.folder_label)
        manager.item_added.connect(self._add)
        for item in reversed(manager.items):
            self._add(item)

    def _add(self, item: DownloadItem) -> None:
        self.empty.hide()
        self._lay.insertWidget(0, _Row(item))
        self.folder_label.setText(f"Pasta de downloads: {self.manager.download_dir()}")

    def showEvent(self, event) -> None:
        self.folder_label.setText(f"Pasta de downloads: {self.manager.download_dir()}")
        super().showEvent(event)
