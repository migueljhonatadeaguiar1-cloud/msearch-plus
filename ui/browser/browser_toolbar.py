"""Barra de ferramentas do navegador: voltar, avançar, recarregar, parar, início, endereço e menu."""
from __future__ import annotations

from PyQt6.QtCore import QTimer, Qt, pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QMenu, QPushButton, QToolButton, QWidget

SECURITY = {
    "secure": ("🔒", "Conexão segura (HTTPS)"),
    "insecure": ("⚠", "Conexão NÃO segura (HTTP): os dados podem ser lidos por terceiros"),
    "offline": ("📁", "Cópia salva localmente (isolada, sem acesso à internet nem aos seus arquivos)"),
    "none": ("🔍", "Digite um endereço ou uma pesquisa"),
}


class AddressEdit(QLineEdit):
    def focusInEvent(self, event) -> None:
        super().focusInEvent(event)
        QTimer.singleShot(0, self.selectAll)


class BrowserToolbar(QWidget):
    back_clicked = pyqtSignal()
    forward_clicked = pyqtSignal()
    reload_clicked = pyqtSignal()
    stop_clicked = pyqtSignal()
    home_clicked = pyqtSignal()
    submitted = pyqtSignal(str)
    new_tab_clicked = pyqtSignal()
    copy_url_clicked = pyqtSignal()
    external_clicked = pyqtSignal()
    save_offline_clicked = pyqtSignal()
    open_offline_clicked = pyqtSignal()
    downloads_clicked = pyqtSignal()
    clear_data_clicked = pyqtSignal()
    zoom_clicked = pyqtSignal(int)          # +1, -1, 0 (redefinir)

    def __init__(self, parent=None):
        super().__init__(parent)

        def btn(text: str, tip: str, signal) -> QToolButton:
            b = QToolButton()
            b.setText(text)
            b.setToolTip(tip)
            b.setAutoRaise(True)
            b.setMinimumSize(32, 32)
            b.clicked.connect(lambda _checked=False: signal.emit())
            return b

        self.back = btn("←", "Voltar (Alt+←)", self.back_clicked)
        self.forward = btn("→", "Avançar (Alt+→)", self.forward_clicked)
        self.reload = btn("↻", "Recarregar (F5)", self.reload_clicked)
        self.stop = btn("✕", "Parar carregamento", self.stop_clicked)
        self.home = btn("⌂", "Página inicial: pesquisa do M-Search+", self.home_clicked)
        self.security = QLabel("🔍")
        self.address = AddressEdit()
        self.address.setObjectName("AddressBar")
        self.address.setPlaceholderText("Pesquisar ou digitar endereço")
        self.address.setClearButtonEnabled(True)
        self.address.setMinimumHeight(34)
        self.address.returnPressed.connect(lambda: self.submitted.emit(self.address.text()))
        self.go = QPushButton("Ir")
        self.go.clicked.connect(lambda _checked=False: self.submitted.emit(self.address.text()))
        self.save_btn = btn("⭳", "Salvar esta página para uso offline (com CSS, JS e imagens)", self.save_offline_clicked)
        self.dl_btn = btn("⬇", "Downloads", self.downloads_clicked)
        self.menu_btn = QToolButton()
        self.menu_btn.setText("⋮")
        self.menu_btn.setToolTip("Mais opções")
        self.menu_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.menu = QMenu(self)
        self.menu_btn.setMenu(self.menu)
        self._build_menu()

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 4, 0, 4)
        lay.setSpacing(4)
        for w in (self.back, self.forward, self.reload, self.stop, self.home, self.security):
            lay.addWidget(w)
        lay.addWidget(self.address, 1)
        for w in (self.go, self.save_btn, self.dl_btn, self.menu_btn):
            lay.addWidget(w)

    def _build_menu(self) -> None:
        m = self.menu
        m.addAction("Nova aba\tCtrl+T", self.new_tab_clicked.emit)
        m.addSeparator()
        m.addAction("Copiar URL da página", self.copy_url_clicked.emit)
        m.addAction("Abrir no navegador externo", self.external_clicked.emit)
        self.act_save = m.addAction("Salvar página para uso offline", self.save_offline_clicked.emit)
        self.act_open_offline = m.addAction("Abrir cópia offline desta página", self.open_offline_clicked.emit)
        m.addSeparator()
        self.history_menu = m.addMenu("Histórico")
        m.addAction("Downloads", self.downloads_clicked.emit)
        z = m.addMenu("Zoom")
        z.addAction("Aumentar\tCtrl++", lambda: self.zoom_clicked.emit(1))
        z.addAction("Diminuir\tCtrl+-", lambda: self.zoom_clicked.emit(-1))
        z.addAction("Tamanho padrão\tCtrl+0", lambda: self.zoom_clicked.emit(0))
        m.addSeparator()
        m.addAction("Limpar dados de navegação…", self.clear_data_clicked.emit)

    # -------------------------------------------------------------- estado
    def set_state(self, *, can_back: bool, can_forward: bool, loading: bool, is_web: bool, address: str,
                  security: str, can_save: bool, has_offline_copy: bool) -> None:
        self.back.setEnabled(can_back)
        self.forward.setEnabled(can_forward)
        self.reload.setEnabled(is_web)
        self.stop.setEnabled(loading)
        glyph, tip = SECURITY.get(security, SECURITY["none"])
        self.security.setText(glyph)
        self.security.setToolTip(tip)
        if not self.address.hasFocus():
            self.address.setText(address)
        self.save_btn.setEnabled(can_save)
        self.act_save.setEnabled(can_save)
        self.act_open_offline.setEnabled(has_offline_copy)

    def focus_address(self) -> None:
        self.address.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self.address.selectAll()
