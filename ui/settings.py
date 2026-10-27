"""Janela de configurações (Geral · Indexação · Privacidade · Dados)."""
from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog,
                             QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QSpinBox, QTabWidget,
                             QTextBrowser, QVBoxLayout, QWidget)

from core.service import SearchPlusService

TAB_GENERAL, TAB_CRAWLER, TAB_PRIVACY, TAB_BROWSER, TAB_DATA = range(5)


class SettingsDialog(QDialog):
    settings_changed = pyqtSignal()
    data_changed = pyqtSignal()
    clear_browsing_requested = pyqtSignal()

    def __init__(self, service: SearchPlusService, parent=None, start_tab: int = TAB_GENERAL):
        super().__init__(parent)
        self.service = service
        self.setWindowTitle("Configurações do M-Search+")
        self.resize(640, 560)
        s = service.settings

        tabs = QTabWidget()
        tabs.addTab(self._general_tab(s), "Geral")
        tabs.addTab(self._crawler_tab(s), "Indexação")
        tabs.addTab(self._privacy_tab(s), "Privacidade")
        tabs.addTab(self._browser_tab(s), "Navegador")
        tabs.addTab(self._data_tab(), "Dados locais")
        tabs.setCurrentIndex(start_tab)
        self.tabs = tabs

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        root = QVBoxLayout(self)
        root.addWidget(tabs)
        root.addWidget(buttons)

    # ------------------------------------------------------------------ abas
    def _general_tab(self, s) -> QWidget:
        w, form = QWidget(), QFormLayout()
        self.theme = QComboBox()
        self.theme.addItem("Claro", "light")
        self.theme.addItem("Escuro", "dark")
        self.theme.setCurrentIndex(0 if s.theme == "light" else 1)
        self.per_page = QSpinBox()
        self.per_page.setRange(5, 50)
        self.per_page.setValue(s.results_per_page)
        self.mode = QComboBox()
        self.mode.addItem("Automático (detecta a conexão)", "auto")
        self.mode.addItem("Sempre offline (só índice local)", "offline")
        self.mode.addItem("Sempre online (não verifica a rede)", "online")
        self.mode.setCurrentIndex({"auto": 0, "offline": 1, "online": 2}.get(s.connectivity_mode, 0))
        form.addRow("Tema", self.theme)
        form.addRow("Resultados por página", self.per_page)
        form.addRow("Modo de conexão", self.mode)
        note = QLabel("No modo automático o app abre uma conexão TCP curta (sem enviar dados) para "
                      f"{s.connectivity_check_host}:{s.connectivity_check_port}. Veja a aba Privacidade.")
        note.setWordWrap(True)
        note.setObjectName("Muted")
        form.addRow(note)
        w.setLayout(form)
        return w

    def _crawler_tab(self, s) -> QWidget:
        w, form = QWidget(), QFormLayout()
        self.delay = QDoubleSpinBox()
        self.delay.setRange(0.5, 30.0)
        self.delay.setSingleStep(0.5)
        self.delay.setSuffix(" s")
        self.delay.setValue(s.request_delay_s)
        self.timeout = QDoubleSpinBox()
        self.timeout.setRange(2, 60)
        self.timeout.setSuffix(" s")
        self.timeout.setValue(s.timeout_s)
        self.max_pages = QSpinBox()
        self.max_pages.setRange(1, 1000)
        self.max_pages.setValue(s.max_pages_per_run)
        self.depth = QSpinBox()
        self.depth.setRange(0, 5)
        self.depth.setValue(s.max_depth)
        self.external = QCheckBox("Seguir links para outros sites (descobrir novos domínios)")
        self.external.setChecked(s.follow_external_links)
        self.cache = QCheckBox("Guardar cópia das páginas (necessário para “Cópia salva” offline)")
        self.cache.setChecked(s.cache_enabled)
        self.local_net = QCheckBox("Permitir rede local/localhost (desenvolvimento)")
        self.local_net.setChecked(s.allow_local_network)
        form.addRow("Intervalo entre requisições (por domínio)", self.delay)
        form.addRow("Timeout", self.timeout)
        form.addRow("Máx. de páginas por execução", self.max_pages)
        form.addRow("Profundidade máxima", self.depth)
        form.addRow(self.external)
        form.addRow(self.cache)
        form.addRow(self.local_net)
        note = QLabel("O robots.txt é sempre respeitado e não pode ser desativado.")
        note.setObjectName("Muted")
        form.addRow(note)
        w.setLayout(form)
        return w

    def _privacy_tab(self, s) -> QWidget:
        w, lay = QWidget(), QVBoxLayout()
        view = QTextBrowser()
        view.setHtml(self.service.privacy.notice_html)
        lay.addWidget(view, 1)
        self.history = QCheckBox("Guardar histórico de pesquisas (somente neste computador)")
        self.history.setChecked(s.save_search_history)
        self.wipe_exit = QCheckBox("Apagar índice, cache e histórico ao fechar o aplicativo")
        self.wipe_exit.setChecked(s.clear_data_on_exit)
        self.b_cookies = QCheckBox("Navegador: permitir cookies de primeiro nível (terceiros ficam sempre bloqueados)")
        self.b_cookies.setChecked(s.browser_allow_cookies)
        self.b_history = QCheckBox("Navegador: armazenar histórico de navegação (somente neste computador)")
        self.b_history.setChecked(s.browser_store_history)
        self.b_cache = QCheckBox("Navegador: manter cache das páginas em disco (desligado = só em memória)")
        self.b_cache.setChecked(s.browser_keep_cache)
        lay.addWidget(self.history)
        lay.addWidget(self.wipe_exit)
        for w in (self.b_cookies, self.b_history, self.b_cache):
            lay.addWidget(w)
        note = QLabel("Cookies desligados também desativam o armazenamento local dos sites. "
                      "Mudanças de cookies/cache valem por completo ao reiniciar o app.")
        note.setObjectName("Muted")
        note.setWordWrap(True)
        lay.addWidget(note)
        clear_nav = QPushButton("Limpar dados de navegação")
        clear_nav.clicked.connect(self.clear_browsing_requested.emit)
        lay.addWidget(clear_nav)
        row = QHBoxLayout()
        for text, fn in (("Apagar histórico", self._clear_history), ("Limpar cache", self._clear_cache),
                         ("Apagar TODOS os dados locais", self._clear_all)):
            b = QPushButton(text)
            if "TODOS" in text:
                b.setObjectName("Danger")
            b.clicked.connect(fn)
            row.addWidget(b)
        lay.addLayout(row)
        w.setLayout(lay)
        return w

    def _browser_tab(self, s) -> QWidget:
        w, form = QWidget(), QFormLayout()
        self.b_js = QCheckBox("Permitir JavaScript nos sites")
        self.b_js.setChecked(s.browser_javascript)
        self.dl_dir = QLineEdit(s.download_dir)
        self.dl_dir.setPlaceholderText("Padrão: pasta Downloads do usuário")
        pick = QPushButton("Escolher…")
        pick.clicked.connect(self._pick_download_dir)
        row = QHBoxLayout()
        row.addWidget(self.dl_dir, 1)
        row.addWidget(pick)
        form.addRow(self.b_js)
        form.addRow("Pasta de downloads", row)
        note = QLabel("O navegador interno nega por padrão câmera, microfone, localização e notificações, bloqueia pop-ups "
                      "sem clique, conteúdo misto e certificados inválidos, e nunca abre arquivos baixados.")
        note.setWordWrap(True)
        note.setObjectName("Muted")
        form.addRow(note)
        w.setLayout(form)
        return w

    def _pick_download_dir(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Pasta de downloads", self.dl_dir.text())
        if folder:
            self.dl_dir.setText(folder)

    def _data_tab(self) -> QWidget:
        w, lay = QWidget(), QVBoxLayout()
        self.stats_label = QLabel()
        self.stats_label.setWordWrap(True)
        lay.addWidget(self.stats_label)
        b = QPushButton("Importar pasta de páginas/notas (.html, .md, .txt)…")
        b.clicked.connect(self._import_folder)
        lay.addWidget(b)
        b2 = QPushButton("Carregar páginas de exemplo")
        b2.clicked.connect(self._load_samples)
        lay.addWidget(b2)
        b4 = QPushButton("Apagar páginas salvas para uso offline")
        b4.setObjectName("Danger")
        b4.clicked.connect(self._clear_saved)
        lay.addWidget(b4)
        b3 = QPushButton("Apagar apenas o índice")
        b3.setObjectName("Danger")
        b3.clicked.connect(self._clear_index)
        lay.addWidget(b3)
        folder = QLabel(f"Pasta de dados: {self.service.paths.root}")
        folder.setObjectName("Muted")
        folder.setWordWrap(True)
        lay.addWidget(folder)
        lay.addStretch(1)
        w.setLayout(lay)
        self._refresh_stats()
        return w

    # ------------------------------------------------------------------ ações
    def _refresh_stats(self) -> None:
        st = self.service.stats()
        src = st["by_source"]
        self.stats_label.setText(
            f"<b>{st['documents']}</b> documentos no índice (web: {src.get('web', 0)} · "
            f"arquivos locais: {src.get('local', 0)} · favoritos: {src.get('bookmark', 0)})<br>"
            f"{st['saved_pages']} páginas salvas offline ({st['saved_bytes'] / 1_048_576:.1f} MB) · "
            f"{st['terms']} termos · {st['cached_pages']} no cache do crawler · "
            f"banco: {st['db_bytes'] / 1024:.0f} KB")

    def _confirm(self, text: str) -> bool:
        return QMessageBox.question(self, "Confirmar", text) == QMessageBox.StandardButton.Yes

    def _clear_history(self) -> None:
        self.service.privacy.clear_history()
        self._refresh_stats()

    def _clear_cache(self) -> None:
        if self._confirm("Apagar as cópias salvas das páginas? (a opção “Cópia salva” deixará de existir)"):
            self.service.privacy.clear_cache()
            self._refresh_stats()
            self.data_changed.emit()

    def _clear_saved(self) -> None:
        if self._confirm("Apagar todas as páginas salvas para uso offline?"):
            self.service.privacy.clear_saved_pages()
            self._refresh_stats()
            self.data_changed.emit()

    def _clear_index(self) -> None:
        if self._confirm("Apagar todo o índice local? Você precisará indexar de novo."):
            self.service.privacy.clear_index()
            self._refresh_stats()
            self.data_changed.emit()

    def _clear_all(self) -> None:
        if self._confirm("Apagar índice, cache e histórico? Esta ação não pode ser desfeita."):
            self.service.privacy.clear_all()
            self._refresh_stats()
            self.data_changed.emit()

    def _import_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Escolha a pasta")
        if folder:
            counts = self.service.offline.import_path(folder)
            QMessageBox.information(self, "Importação", f"Importados: {counts['imported']} · "
                                                        f"ignorados: {counts['skipped']} · erros: {counts['errors']}")
            self._refresh_stats()
            self.data_changed.emit()

    def _load_samples(self) -> None:
        counts = self.service.load_sample_pages()
        QMessageBox.information(self, "Exemplos", f"{counts['imported']} páginas de exemplo carregadas.")
        self._refresh_stats()
        self.data_changed.emit()

    def _save(self) -> None:
        s = self.service.settings
        s.theme = self.theme.currentData()
        s.results_per_page = self.per_page.value()
        s.connectivity_mode = self.mode.currentData()
        s.request_delay_s = self.delay.value()
        s.timeout_s = self.timeout.value()
        s.max_pages_per_run = self.max_pages.value()
        s.max_depth = self.depth.value()
        s.follow_external_links = self.external.isChecked()
        s.cache_enabled = self.cache.isChecked()
        s.allow_local_network = self.local_net.isChecked()
        s.browser_javascript = self.b_js.isChecked()
        s.download_dir = self.dl_dir.text().strip()
        s.browser_allow_cookies = self.b_cookies.isChecked()
        s.browser_store_history = self.b_history.isChecked()
        s.browser_keep_cache = self.b_cache.isChecked()
        s.save_search_history = self.history.isChecked()
        s.clear_data_on_exit = self.wipe_exit.isChecked()
        self.service.save_settings()
        self.settings_changed.emit()
        self.accept()
