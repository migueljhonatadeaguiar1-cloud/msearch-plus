"""Janela principal do M-Search+: aba "Pesquisa" (tela inicial + resultados) dentro do navegador interno.

Estrutura:  cabeçalho (status, Indexar, Privacidade, Configurações)
            └─ BrowserWindow: [Pesquisa] [site] [site] [+]  ← aba 0 = busca; demais = QWebEngineView
Se o PyQt6-WebEngine não estiver instalado, o app funciona sem abas e abre links no navegador do sistema.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (QApplication, QHBoxLayout, QLabel, QMainWindow, QMessageBox, QPushButton,
                             QStackedWidget, QVBoxLayout, QWidget)

from core.service import SearchPlusService
from ui.browser import WEBENGINE_AVAILABLE, WEBENGINE_ERROR
from ui.index_dialog import IndexDialog
from ui.results_view import ResultsView
from ui.search_bar import SearchBar
from ui.settings import TAB_PRIVACY, SettingsDialog
from ui.theme import palette, stylesheet
from ui.workers import ConnectivityWorker

if WEBENGINE_AVAILABLE:
    from ui.browser.browser_window import BrowserWindow
    from ui.browser.profile import BrowserEngine


def logo_html(size: int, accent: str) -> str:
    return (f'<span style="font-size:{size}px; font-weight:700; letter-spacing:-1px">M-Search'
            f'<span style="color:{accent}">+</span></span>')


class MainWindow(QMainWindow):
    def __init__(self, service: SearchPlusService):
        super().__init__()
        self.service = service
        self._query = ""
        self._shown = 0
        self.engine = None
        self.browser = None
        self.setWindowTitle("M-Search+")
        self.resize(1100, 760)

        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_home())
        self.stack.addWidget(self._build_results_page())

        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(14, 8, 14, 8)
        root.addLayout(self._build_header())
        if WEBENGINE_AVAILABLE:
            self.engine = BrowserEngine(service, self)
            self.browser = BrowserWindow(service, self.engine, self)
            self.browser.set_search_widget(self.stack, "Pesquisa")
            self.browser.search_requested.connect(self.run_search)
            self.browser.home_requested.connect(self.go_home)
            self.browser.clear_data_requested.connect(self.clear_browsing_data)
            root.addWidget(self.browser, 1)
        else:
            warn = QLabel("Navegador interno indisponível (instale com: pip install PyQt6-WebEngine). "
                          "Os links serão abertos no navegador do sistema.")
            warn.setObjectName("Notice")
            warn.setWordWrap(True)
            warn.setToolTip(WEBENGINE_ERROR)
            root.addWidget(warn)
            root.addWidget(self.stack, 1)
        self.setCentralWidget(central)

        self.apply_theme()
        self._refresh_home()
        self.net = ConnectivityWorker(service, self)
        self.net.changed.connect(self._set_online)
        self.net.start()
        self._set_online(False, checking=True)

    # ---------------------------------------------------------------- layout
    def _build_header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addStretch(1)
        self.status = QLabel("● Verificando…")
        row.addWidget(self.status)
        for text, fn in (("Indexar", self.open_index), ("Privacidade", self.open_privacy),
                         ("Configurações", self.open_settings)):
            b = QPushButton(text)
            b.clicked.connect(lambda _checked=False, f=fn: f())
            if text == "Indexar":
                self.index_btn = b
            row.addWidget(b)
        return row

    def _build_home(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.addStretch(3)
        self.big_logo = QLabel()
        self.big_logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tagline = QLabel("Busca própria, privada e que funciona offline")
        tagline.setObjectName("Tagline")
        tagline.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.home_bar = SearchBar()
        self.home_bar.setMaximumWidth(720)
        self.home_bar.submitted.connect(self.run_search)
        self.home_info = QLabel()
        self.home_info.setObjectName("Muted")
        self.home_info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.sample_btn = QPushButton("Carregar páginas de exemplo")
        self.sample_btn.clicked.connect(self._load_samples)
        for w in (self.big_logo, tagline):
            lay.addWidget(w)
        lay.addSpacing(12)
        lay.addWidget(self.home_bar, alignment=Qt.AlignmentFlag.AlignHCenter)
        lay.addSpacing(8)
        lay.addWidget(self.home_info)
        lay.addWidget(self.sample_btn, alignment=Qt.AlignmentFlag.AlignHCenter)
        lay.addStretch(4)
        return page

    def _build_results_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        top = QHBoxLayout()
        self.small_logo_label = QLabel()
        top.addWidget(self.small_logo_label)
        self.results_bar = SearchBar(compact=True)
        self.results_bar.submitted.connect(self.run_search)
        top.addWidget(self.results_bar, 1)
        home_btn = QPushButton("Início")
        home_btn.clicked.connect(lambda _checked=False: self.go_home())
        top.addWidget(home_btn)
        lay.addLayout(top)
        self.results = ResultsView(self.service.offline.has_offline_copy)
        self.results.open_requested.connect(self.open_url)
        self.results.cached_requested.connect(self.open_cached)
        self.results.favorite_toggled.connect(self.toggle_favorite)
        self.results.external_requested.connect(self.open_external)
        self.results.copy_requested.connect(self.copy_url)
        self.results.save_offline_requested.connect(self.save_offline)
        self.results.more_requested.connect(self.load_more)
        lay.addWidget(self.results, 1)
        return page

    # ------------------------------------------------------------------ tema
    def apply_theme(self) -> None:
        theme = self.service.settings.theme
        pal = palette(theme)
        self._pal = pal
        self.setStyleSheet(stylesheet(theme))
        self.big_logo.setText(logo_html(64, pal["accent"]))
        self.small_logo_label.setText(logo_html(26, pal["accent"]))
        self.results.set_link_color(pal["link"])

    # ----------------------------------------------------------- conectividade
    def _set_online(self, online: bool, checking: bool = False) -> None:
        pal = self._pal
        if checking:
            self.status.setText("● Verificando…")
            return
        suffix = " (manual)" if self.service.connectivity.forced else ""
        if online:
            self.status.setText(f'<span style="color:{pal["ok"]}">●</span> Online{suffix}')
            self.status.setToolTip("Sites abrem no navegador interno. A pesquisa usa o índice local.")
        else:
            self.status.setText(f'<span style="color:{pal["bad"]}">●</span> Offline{suffix}')
            self.status.setToolTip("Só páginas salvas, arquivos locais e favoritos abrem. Nada é carregado da internet.")
        self.index_btn.setEnabled(online)
        self.index_btn.setToolTip("" if online else "Indexar exige conexão. Você ainda pode pesquisar offline.")
        if self.browser is not None:
            self.browser.refresh_connectivity()

    # ----------------------------------------------------------------- busca
    def run_search(self, text: str) -> None:
        self._query = text
        self.home_bar.set_text(text)
        self.results_bar.set_text(text)
        resp = self.service.search(text, 0)
        self._shown = len(resp.results)
        self.results.show_response(resp, append=False)
        self.stack.setCurrentIndex(1)
        if self.browser is not None:
            self.browser.show_search_tab()

    def load_more(self) -> None:
        resp = self.service.search(self._query, self._shown)
        self._shown += len(resp.results)
        self.results.show_response(resp, append=True)

    def go_home(self) -> None:
        self._refresh_home()
        self.stack.setCurrentIndex(0)
        if self.browser is not None:
            self.browser.show_search_tab()
        self.home_bar.focus()

    def _refresh_home(self) -> None:
        n = self.service.stats()["documents"]
        self.home_info.setText(f"{n} página(s) no índice local" if n else
                               "O índice está vazio. Indexe sites ou carregue as páginas de exemplo.")
        self.sample_btn.setVisible(n == 0)

    # ------------------------------------------------------------------ ações
    def open_url(self, url: str) -> None:
        """Comportamento padrão: abrir DENTRO do M-Search+ (nova aba)."""
        if self.browser is not None:
            self.browser.open_url(url, new_tab=True)
        else:
            self.open_external(url)

    def open_cached(self, url: str) -> None:
        if self.browser is not None:
            self.browser.open_saved_copy(url)
        else:
            path = self.service.offline.cached_copy_path(url)
            if path is None:
                QMessageBox.information(self, "Cópia salva", "Não há cópia salva desta página.")
                return
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def open_external(self, url: str) -> None:
        if not self.service.connectivity.online and not url.startswith("file:"):
            QMessageBox.information(self, "Offline", "Você está offline.")
            return
        QDesktopServices.openUrl(QUrl(url))

    def copy_url(self, url: str) -> None:
        QApplication.clipboard().setText(url)
        self.statusBar().showMessage("URL copiada.", 2500)

    def save_offline(self, url: str) -> None:
        if self.browser is not None:
            self.browser.save_offline(url)

    def toggle_favorite(self, doc_id: int, url: str, favorite: bool) -> None:
        self.service.offline.set_favorite(url, favorite=favorite)

    def clear_browsing_data(self) -> None:
        if self.engine is None:
            return
        if QMessageBox.question(self, "Limpar dados de navegação",
                                "Apagar cookies, cache e histórico de navegação do navegador interno?\n"
                                "(Páginas salvas offline e o índice NÃO são apagados.)") == QMessageBox.StandardButton.Yes:
            self.engine.clear_browsing_data()
            self.statusBar().showMessage("Dados de navegação apagados.", 3000)

    def _load_samples(self) -> None:
        self.service.load_sample_pages()
        self._refresh_home()

    # ---------------------------------------------------------------- diálogos
    def open_index(self) -> None:
        dlg = IndexDialog(self.service, self)
        dlg.index_changed.connect(self._refresh_home)
        dlg.exec()

    def open_settings(self, start_tab: int = 0) -> None:
        dlg = SettingsDialog(self.service, self, start_tab)
        dlg.settings_changed.connect(self._settings_changed)
        dlg.data_changed.connect(self._refresh_home)
        dlg.clear_browsing_requested.connect(self.clear_browsing_data)
        dlg.exec()

    def open_privacy(self) -> None:
        self.open_settings(TAB_PRIVACY)

    def _settings_changed(self) -> None:
        self.apply_theme()
        if self.engine is not None:
            self.engine.apply_settings()
        self.net.probe_now()

    def closeEvent(self, event) -> None:
        self.net.stop()
        self.net.wait(3000)
        if self.browser is not None:
            self.browser.shutdown()
        super().closeEvent(event)
