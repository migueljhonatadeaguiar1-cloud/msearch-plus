"""Navegador interno: abas + barra de ferramentas + progresso + avisos. Implementa BrowserHooks.

A aba 0 ("Pesquisa") é a tela de busca do M-Search+ (widget fornecido pela janela principal); as demais são sites
(online ou páginas salvas offline) renderizados por QWebEngineView.
"""
from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit

from PyQt6.QtCore import Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices, QKeySequence, QShortcut
from PyQt6.QtWidgets import (QApplication, QHBoxLayout, QLabel, QProgressBar, QStackedWidget, QTabBar,
                             QToolButton, QVBoxLayout, QWidget)

from core.service import SearchPlusService
from offline.page_library import SCHEME
from ui.browser.browser_tab import BrowserTab
from ui.browser.browser_toolbar import BrowserToolbar
from ui.browser.browser_view import BrowserView
from ui.browser.download_manager import DownloadsDialog
from ui.browser.profile import BrowserEngine
from ui.browser.url_utils import resolve_input, security_state
from ui.workers import SaveWorker


class BrowserWindow(QWidget):
    search_requested = pyqtSignal(str)
    home_requested = pyqtSignal()
    clear_data_requested = pyqtSignal()

    def __init__(self, service: SearchPlusService, engine: BrowserEngine, parent=None):
        super().__init__(parent)
        self.service, self.engine = service, engine
        self._widgets: dict[int, QWidget] = {}
        self._next_id = 0
        self._search_widget: QWidget | None = None
        self._blocked: dict[str, int] = {}
        self._saver: SaveWorker | None = None
        self._downloads: DownloadsDialog | None = None
        self._flash_text = ""

        self.tab_bar = QTabBar()
        self.tab_bar.setDocumentMode(True)
        self.tab_bar.setTabsClosable(True)
        self.tab_bar.setMovable(True)
        self.tab_bar.setExpanding(False)
        self.tab_bar.setUsesScrollButtons(True)
        self.tab_bar.setElideMode(Qt.TextElideMode.ElideRight)
        self.tab_bar.tabCloseRequested.connect(self.close_tab)
        self.tab_bar.currentChanged.connect(self._on_current_changed)
        plus = QToolButton()
        plus.setText("+")
        plus.setToolTip("Nova aba (Ctrl+T)")
        plus.setAutoRaise(True)
        plus.clicked.connect(lambda _c=False: self.new_blank_tab())
        tabrow = QHBoxLayout()
        tabrow.setContentsMargins(0, 0, 0, 0)
        tabrow.addWidget(self.tab_bar, 1)
        tabrow.addWidget(plus)

        self.toolbar = BrowserToolbar()
        self.progress = QProgressBar()
        self.progress.setObjectName("PageProgress")
        self.progress.setFixedHeight(3)
        self.progress.setTextVisible(False)
        self.progress.setRange(0, 100)
        self.progress.hide()
        self.infobar = QLabel()
        self.infobar.setObjectName("InfoBar")
        self.infobar.setWordWrap(True)
        self.infobar.hide()
        self.status = QLabel()
        self.status.setObjectName("Muted")
        self.stack = QStackedWidget()

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addLayout(tabrow)
        root.addWidget(self.toolbar)
        root.addWidget(self.progress)
        root.addWidget(self.infobar)
        root.addWidget(self.stack, 1)
        root.addWidget(self.status)

        t = self.toolbar
        t.submitted.connect(self._on_submit)
        t.back_clicked.connect(lambda: self._with_tab(lambda tab: tab.view.back()))
        t.forward_clicked.connect(lambda: self._with_tab(lambda tab: tab.view.forward()))
        t.reload_clicked.connect(lambda: self._with_tab(lambda tab: tab.reload()))
        t.stop_clicked.connect(lambda: self._with_tab(lambda tab: tab.view.stop()))
        t.home_clicked.connect(self.home_requested)
        t.new_tab_clicked.connect(self.new_blank_tab)
        t.copy_url_clicked.connect(lambda: self.copy_text(self._current_url()))
        t.external_clicked.connect(lambda: self.open_external(self._current_url()))
        t.save_offline_clicked.connect(lambda: self.save_offline())
        t.open_offline_clicked.connect(self._open_offline_copy_of_current)
        t.downloads_clicked.connect(self.show_downloads)
        t.clear_data_clicked.connect(self.clear_data_requested)
        t.zoom_clicked.connect(self._zoom)
        t.history_menu.aboutToShow.connect(self._fill_history_menu)
        engine.blocked.connect(self._on_blocked)
        engine.downloads.item_added.connect(lambda _item: self.show_downloads())
        self._install_shortcuts()

    # =============================================================== abas
    def set_search_widget(self, widget: QWidget, title: str = "Pesquisa") -> None:
        self._search_widget = widget
        self._add_widget_tab(widget, title, closable=False)

    def _add_widget_tab(self, widget: QWidget, title: str, *, closable: bool = True, select: bool = True) -> int:
        tid = self._next_id
        self._next_id += 1
        self._widgets[tid] = widget
        self.stack.addWidget(widget)
        idx = self.tab_bar.addTab(title)
        self.tab_bar.setTabData(idx, tid)
        if not closable:
            for side in (QTabBar.ButtonPosition.RightSide, QTabBar.ButtonPosition.LeftSide):
                self.tab_bar.setTabButton(idx, side, None)
        if select:
            self.tab_bar.setCurrentIndex(idx)
        return idx

    def _widget_at(self, index: int) -> QWidget | None:
        return self._widgets.get(self.tab_bar.tabData(index)) if index >= 0 else None

    def _index_of(self, widget: QWidget) -> int:
        for i in range(self.tab_bar.count()):
            if self._widget_at(i) is widget:
                return i
        return -1

    def current_browser_tab(self) -> BrowserTab | None:
        w = self._widget_at(self.tab_bar.currentIndex())
        return w if isinstance(w, BrowserTab) else None

    def _with_tab(self, fn) -> None:
        tab = self.current_browser_tab()
        if tab is not None:
            fn(tab)

    def _new_browser_tab(self, *, select: bool = True) -> BrowserTab:
        tab = BrowserTab(self.engine.profile, self, self)
        tab.title_changed.connect(self._on_title)
        tab.icon_changed.connect(self._on_icon)
        tab.url_changed.connect(self._on_tab_changed)
        tab.load_changed.connect(self._on_tab_changed)
        tab.link_hovered.connect(lambda text, t=tab: self._on_hover(t, text))
        tab.close_requested.connect(lambda t: self.close_tab(self._index_of(t)))
        tab.visited.connect(self._on_visited)
        self._add_widget_tab(tab, "Nova aba", select=select)
        return tab

    def new_blank_tab(self) -> BrowserTab:
        tab = self._new_browser_tab()
        tab.show_new_tab_page()
        self.toolbar.focus_address()
        return tab

    def close_tab(self, index: int) -> None:
        widget = self._widget_at(index)
        if widget is None or widget is self._search_widget:
            return
        tid = self.tab_bar.tabData(index)
        self.tab_bar.removeTab(index)
        self.stack.removeWidget(widget)
        self._widgets.pop(tid, None)
        if isinstance(widget, BrowserTab):
            widget.dispose()
        self._refresh_chrome()

    def show_search_tab(self) -> None:
        if self._search_widget is not None:
            self.tab_bar.setCurrentIndex(self._index_of(self._search_widget))

    def _on_current_changed(self, index: int) -> None:
        w = self._widget_at(index)
        if w is not None:
            self.stack.setCurrentWidget(w)
        self.status.setText("")
        self._refresh_chrome()

    # ============================================================= abrir URLs
    def open_url(self, url: str, *, new_tab: bool = True, background: bool = False) -> None:
        target, _mode = self.service.browser_target(url)
        tab = self._new_browser_tab(select=not background) if (new_tab or self.current_browser_tab() is None) \
            else self.current_browser_tab()
        if target is None:
            tab.show_unavailable(url)
        else:
            tab.load(target)

    def open_saved_copy(self, url: str) -> None:
        target = self.service.offline.saved_copy_url(url)
        if target is None:
            self._flash("Não há cópia salva desta página.")
            return
        self._new_browser_tab().load(target)

    def _on_submit(self, text: str) -> None:
        r = resolve_input(text)
        if r.kind == "blank":
            return
        if r.kind == "invalid":
            self._flash(r.message or "Endereço inválido.")
            return
        if r.kind == "search":
            self.search_requested.emit(r.value)
            return
        url = Path(r.value).as_uri() if r.kind == "local_file" else r.value
        self.open_url(url, new_tab=self.current_browser_tab() is None)

    def _open_offline_copy_of_current(self) -> None:
        url = self._original_url(self.current_browser_tab())
        if url:
            self.open_saved_copy(url)

    # ============================================================== hooks
    def offline_now(self) -> bool:
        return self.service.connectivity.offline_now()

    def saved_copy_url(self, url: str) -> str | None:
        return self.service.offline.saved_copy_url(url)

    def open_local_file(self, url: str) -> str | None:
        return self.service.offline.ensure_local_copy(url)

    def on_blocked_navigation(self, url: str, reason: str) -> None:
        self._flash(f"{reason}  ({url[:80]})", 6000)

    def create_tab_for_popup(self, background: bool) -> BrowserView:
        return self._new_browser_tab(select=not background).view

    def open_external(self, url: str) -> None:
        if url.lower().startswith(("http://", "https://")):
            QDesktopServices.openUrl(QUrl(url))          # escolha explícita do usuário

    def copy_text(self, text: str) -> None:
        if text:
            QApplication.clipboard().setText(text)
            self._flash("Copiado.", 1500)

    def request_save_offline(self, url: str) -> None:
        self.save_offline(url)

    # ============================================================ salvar offline
    def save_offline(self, url: str | None = None) -> None:
        url = url or self._original_url(self.current_browser_tab())
        if not url.lower().startswith(("http://", "https://")):
            self._flash("Só é possível salvar páginas http(s).")
            return
        if not self.service.connectivity.online:
            self._flash("Sem conexão: não é possível baixar a página agora.")
            return
        if self._saver is not None and self._saver.isRunning():
            self._flash("Já existe um salvamento em andamento.")
            return
        self._saver = SaveWorker(self.service, url, self)
        self._saver.progress.connect(lambda n, _u: self._flash(f"Salvando cópia offline… {n} recurso(s)", 0))
        self._saver.done.connect(self._save_done)
        self._flash("Salvando cópia offline…", 0)
        self._saver.start()

    def _save_done(self, report, error: str) -> None:
        if report is None:
            self._flash(f"Não foi possível salvar: {error}", 8000)
            return
        msg = f"Cópia offline salva: {report.resources} recurso(s) locais"
        if report.failed:
            msg += f"; {len(report.failed)} não puderam ser baixados e dependerão da internet"
        self._flash(msg + ".", 8000)
        self._refresh_chrome()

    # =================================================================== UI
    def _original_url(self, tab: BrowserTab | None) -> str:
        if tab is None:
            return ""
        if tab.display_override:
            return tab.display_override
        url = tab.view.url()
        if url.scheme() == SCHEME:
            page = self.service.offline.library.find_by_id(url.host())
            return page.url if page else ""
        return url.toString() if url.scheme() in ("http", "https") else ""

    def _current_url(self) -> str:
        return self._original_url(self.current_browser_tab())

    def _display_url(self, tab: BrowserTab) -> str:
        if tab.display_override:
            return tab.display_override
        url = tab.view.url()
        if url.scheme() in ("about", "data", ""):
            return ""
        if url.scheme() == SCHEME:
            page = self.service.offline.library.find_by_id(url.host())
            return page.url if page else url.toString()
        return url.toString()

    def _on_title(self, tab: BrowserTab, title: str) -> None:
        idx = self._index_of(tab)
        if idx >= 0:
            text = title.strip() or "Nova aba"
            self.tab_bar.setTabText(idx, text if len(text) <= 26 else text[:25] + "…")
            self.tab_bar.setTabToolTip(idx, text)

    def _on_icon(self, tab: BrowserTab, icon) -> None:
        idx = self._index_of(tab)
        if idx >= 0:
            self.tab_bar.setTabIcon(idx, icon)

    def _on_tab_changed(self, tab: BrowserTab) -> None:
        if tab is self.current_browser_tab():
            self._refresh_chrome()

    def _on_hover(self, tab: BrowserTab, text: str) -> None:
        if tab is self.current_browser_tab():
            self.status.setText(text)

    def _on_visited(self, url: str, title: str) -> None:
        if self.service.settings.browser_store_history:
            self.service.db.add_visit(url, title)

    def _on_blocked(self, page_id: str, _url: str) -> None:
        self._blocked[page_id] = self._blocked.get(page_id, 0) + 1
        self._refresh_chrome()

    def refresh_connectivity(self) -> None:
        self._refresh_chrome()

    def _refresh_chrome(self) -> None:
        tab = self.current_browser_tab()
        if tab is None:
            self.toolbar.set_state(can_back=False, can_forward=False, loading=False, is_web=False, address="",
                                   security="none", can_save=False, has_offline_copy=False)
            self.progress.hide()
            self._update_infobar(None)
            return
        original = self._original_url(tab)
        history = tab.view.history()
        security = "none" if tab.display_override else security_state(tab.view.url().toString())
        is_http = original.lower().startswith(("http://", "https://"))
        self.toolbar.set_state(
            can_back=history.canGoBack(), can_forward=history.canGoForward(), loading=tab.loading, is_web=True,
            address=self._display_url(tab), security=security,
            can_save=is_http and self.service.connectivity.online,
            has_offline_copy=is_http and self.service.offline.has_offline_copy(original))
        if tab.loading:
            self.progress.setValue(tab.progress)
            self.progress.show()
        else:
            self.progress.hide()
        self._update_infobar(tab)

    def _update_infobar(self, tab: BrowserTab | None) -> None:
        text = self._flash_text
        if not text and tab is not None and tab.view.url().scheme() == SCHEME:
            page = self.service.offline.library.find_by_id(tab.view.url().host())
            if page is not None:
                blocked = self._blocked.get(page.page_id, 0)
                if page.kind == "local":
                    text = "📁 Documento local aberto em ambiente isolado (sem acesso a outros arquivos nem à internet)."
                elif page.kind == "html_only":
                    text = ("📁 Cópia offline parcial: só o HTML foi guardado (sem imagens/estilos). "
                            "Online, use “Salvar página para uso offline” para a cópia completa.")
                else:
                    text = (f"📁 Cópia offline completa ({page.resources} recursos). "
                            "Funções que dependem de servidores externos não estão disponíveis offline.")
                if blocked:
                    text += f"  {blocked} requisição(ões) à internet foram bloqueadas."
        self.infobar.setText(text)
        self.infobar.setVisible(bool(text))

    def _flash(self, text: str, ms: int = 4000) -> None:
        self._flash_text = text
        self._refresh_chrome()
        if ms:
            QTimer.singleShot(ms, lambda t=text: self._clear_flash(t))

    def _clear_flash(self, text: str) -> None:
        if self._flash_text == text:
            self._flash_text = ""
            self._refresh_chrome()

    # ============================================================== extras
    def _fill_history_menu(self) -> None:
        menu = self.toolbar.history_menu
        menu.clear()
        if not self.service.settings.browser_store_history:
            menu.addAction("Histórico desativado (Configurações → Privacidade)").setEnabled(False)
            return
        visits = self.service.db.list_visits(15)
        if not visits:
            menu.addAction("Vazio").setEnabled(False)
        for url, title, _ts in visits:
            label = (title or urlsplit(url).netloc or url)[:60]
            menu.addAction(label, lambda u=url: self.open_url(u))

    def show_downloads(self) -> None:
        if self._downloads is None:
            self._downloads = DownloadsDialog(self.engine.downloads, self)
        self._downloads.show()
        self._downloads.raise_()

    def _zoom(self, direction: int) -> None:
        tab = self.current_browser_tab()
        if tab is None:
            return
        factor = 1.0 if direction == 0 else max(0.25, min(5.0, tab.view.zoomFactor() + 0.1 * direction))
        tab.view.setZoomFactor(factor)

    def _install_shortcuts(self) -> None:
        def sc(keys: str, fn) -> None:
            s = QShortcut(QKeySequence(keys), self)
            s.activated.connect(fn)

        sc("Ctrl+T", self.new_blank_tab)
        sc("Ctrl+W", lambda: self.close_tab(self.tab_bar.currentIndex()))
        sc("Ctrl+L", self.toolbar.focus_address)
        sc("F6", self.toolbar.focus_address)
        sc("F5", lambda: self._with_tab(lambda t: t.reload()))
        sc("Ctrl+R", lambda: self._with_tab(lambda t: t.reload()))
        sc("Alt+Left", lambda: self._with_tab(lambda t: t.view.back()))
        sc("Alt+Right", lambda: self._with_tab(lambda t: t.view.forward()))
        sc("Ctrl+Tab", lambda: self.tab_bar.setCurrentIndex((self.tab_bar.currentIndex() + 1) % self.tab_bar.count()))
        sc("Ctrl+Shift+Tab", lambda: self.tab_bar.setCurrentIndex((self.tab_bar.currentIndex() - 1) % self.tab_bar.count()))
        sc("Ctrl++", lambda: self._zoom(1))
        sc("Ctrl+=", lambda: self._zoom(1))
        sc("Ctrl+-", lambda: self._zoom(-1))
        sc("Ctrl+0", lambda: self._zoom(0))

    def shutdown(self) -> None:
        if self._saver is not None and self._saver.isRunning():
            self._saver.request_stop()
            self._saver.wait(5000)
        for i in range(self.tab_bar.count() - 1, -1, -1):
            self.close_tab(i)
        self.engine.shutdown()
