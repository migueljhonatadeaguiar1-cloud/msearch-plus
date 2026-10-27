"""Uma aba do navegador: uma BrowserView com sua própria página, histórico e estado de carregamento."""
from __future__ import annotations

from PyQt6.QtCore import QUrl, pyqtSignal
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QVBoxLayout, QWidget

from ui.browser.browser_view import BrowserHooks, BrowserView

NEW_TAB_HTML = """<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><title>Nova aba</title>
<style>body{font:16px/1.6 system-ui,sans-serif;color:#667085;text-align:center;margin-top:22vh}
b{font-size:44px;color:#222}b span{color:#3b5bdb}</style></head>
<body><b>M-Search<span>+</span></b><p>Digite um endereço ou uma pesquisa na barra acima.</p></body></html>"""


class BrowserTab(QWidget):
    title_changed = pyqtSignal(object, str)
    icon_changed = pyqtSignal(object, QIcon)
    url_changed = pyqtSignal(object)
    load_changed = pyqtSignal(object)            # início, progresso ou fim
    link_hovered = pyqtSignal(str)
    close_requested = pyqtSignal(object)
    visited = pyqtSignal(str, str)               # (url, título) depois de carregar com sucesso

    def __init__(self, profile, hooks: BrowserHooks, parent=None):
        super().__init__(parent)
        self.view = BrowserView(profile, hooks, self)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.view)
        self.progress = 0
        self.loading = False
        self.display_override = ""              # URL "pretendida" quando exibimos a página de indisponível
        self._keep_override = False
        v = self.view
        v.titleChanged.connect(lambda t: self.title_changed.emit(self, t))
        v.iconChanged.connect(lambda i: self.icon_changed.emit(self, i))
        v.urlChanged.connect(lambda _u: self.url_changed.emit(self))
        v.loadStarted.connect(self._on_started)
        v.loadProgress.connect(self._on_progress)
        v.loadFinished.connect(self._on_finished)
        page = v.page()
        page.linkHovered.connect(self.link_hovered)
        page.windowCloseRequested.connect(lambda: self.close_requested.emit(self))

    # ---------------------------------------------------------------- estado
    def _on_started(self) -> None:
        self.loading, self.progress = True, 0
        if not self._keep_override:
            self.display_override = ""
        self.load_changed.emit(self)

    def _on_progress(self, p: int) -> None:
        self.progress = p
        self.load_changed.emit(self)

    def _on_finished(self, ok: bool) -> None:
        self.loading, self.progress = False, 100
        self._keep_override = False
        if ok and self.view.url().scheme() in ("http", "https"):
            self.visited.emit(self.view.url().toString(), self.view.title())
        self.load_changed.emit(self)

    # ----------------------------------------------------------------- ações
    def load(self, url: str) -> None:
        self.display_override = ""
        self.view.setUrl(QUrl(url))

    def show_new_tab_page(self) -> None:
        self.display_override = ""
        self.view.page().set_internal_html(NEW_TAB_HTML)

    def show_unavailable(self, url: str) -> None:
        self.display_override, self._keep_override = url, True
        self.view.page().show_unavailable(url)

    def reload(self) -> None:
        if self.display_override:
            self.load(self.display_override)         # tenta de novo (talvez já esteja online)
        else:
            self.view.reload()

    def dispose(self) -> None:
        self.view.stop()
        self.view.deleteLater()        # a página pertence à view e é destruída junto
        self.deleteLater()
