"""Barra de pesquisa (campo + botão). Enter também envia."""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QLineEdit, QPushButton, QWidget


class SearchBar(QWidget):
    submitted = pyqtSignal(str)

    def __init__(self, compact: bool = False, parent=None):
        super().__init__(parent)
        self.input = QLineEdit()
        self.input.setObjectName("SearchInput")
        self.input.setPlaceholderText("Pesquisar com o M-Search+   (\"frase exata\", -excluir, site:dominio)")
        self.input.setClearButtonEnabled(True)
        self.input.setMinimumHeight(38 if compact else 48)
        self.button = QPushButton("Pesquisar")
        self.button.setObjectName("Primary")
        self.button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.button.setMinimumHeight(38 if compact else 44)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addWidget(self.input, 1)
        layout.addWidget(self.button)
        self.input.returnPressed.connect(self._emit)
        self.button.clicked.connect(self._emit)

    def _emit(self) -> None:
        text = self.input.text().strip()
        if text:
            self.submitted.emit(text)

    def text(self) -> str:
        return self.input.text()

    def set_text(self, text: str) -> None:
        self.input.setText(text)

    def focus(self) -> None:
        self.input.setFocus()
        self.input.selectAll()
