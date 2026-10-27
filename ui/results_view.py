"""Lista de resultados: cards com título, URL, trecho, relevância e ações."""
from __future__ import annotations

import time
from html import escape
from typing import Callable
from urllib.parse import urlsplit

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QMenu, QProgressBar, QPushButton, QScrollArea,
                             QVBoxLayout, QWidget)

from core.models import SearchResponse, SearchResult

SOURCE_LABELS = {"local": "Arquivo local", "bookmark": "Favorito"}


def _display_url(url: str) -> str:
    p = urlsplit(url)
    if p.scheme == "file":
        return url
    path = p.path.rstrip("/")
    return f"{p.netloc}{' › ' + path.strip('/').replace('/', ' › ') if path else ''}"


class ResultCard(QFrame):
    open_clicked = pyqtSignal(str)            # abre em NOVA ABA do navegador interno
    cached_clicked = pyqtSignal(str)          # abre a cópia salva (offline) no navegador interno
    favorite_clicked = pyqtSignal(int, str, bool)
    external_clicked = pyqtSignal(str)        # abre no navegador do sistema (escolha explícita)
    copy_clicked = pyqtSignal(str)
    save_offline_clicked = pyqtSignal(str)

    def __init__(self, r: SearchResult, has_cached: bool, link_color: str, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self._r, self._fav, self._has_cached = r, r.favorite, has_cached
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(4)

        top = QHBoxLayout()
        domain = QLabel(escape(_display_url(r.url)))
        domain.setObjectName("CardDomain")
        domain.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        top.addWidget(domain, 1)
        if r.source in SOURCE_LABELS:
            badge = QLabel(SOURCE_LABELS[r.source])
            badge.setObjectName("Badge")
            top.addWidget(badge)
        if has_cached:
            badge = QLabel("Cópia salva")
            badge.setObjectName("Badge")
            top.addWidget(badge)
        lay.addLayout(top)

        title = QLabel(f'<a href="open" style="color:{link_color}; text-decoration:none; font-size:17px">'
                       f"{escape(r.title)}</a>")
        title.setTextFormat(Qt.TextFormat.RichText)
        title.setWordWrap(True)
        title.setCursor(Qt.CursorShape.PointingHandCursor)
        title.linkActivated.connect(lambda _=None: self.open_clicked.emit(r.url))
        lay.addWidget(title)

        snippet = QLabel(r.snippet_html or "<i>Sem trecho disponível.</i>")
        snippet.setTextFormat(Qt.TextFormat.RichText)
        snippet.setWordWrap(True)
        lay.addWidget(snippet)

        bottom = QHBoxLayout()
        bar = QProgressBar()
        bar.setRange(0, 100)
        bar.setValue(r.relevance)
        bar.setTextVisible(False)
        bar.setFixedSize(90, 6)
        tip = r.breakdown.explain()
        bar.setToolTip(tip)
        rel = QLabel(f"Relevância {r.relevance}%")
        rel.setObjectName("Muted")
        rel.setToolTip(tip)
        bottom.addWidget(bar)
        bottom.addWidget(rel)
        bottom.addStretch(1)
        if r.fetched_at:
            when = QLabel(time.strftime("indexado em %d/%m/%Y", time.localtime(r.fetched_at)))
            when.setObjectName("Muted")
            bottom.addWidget(when)
        if has_cached:
            b = QPushButton("Abrir cópia salva")
            b.setObjectName("Link")
            b.clicked.connect(lambda: self.cached_clicked.emit(r.url))
            bottom.addWidget(b)
        b = QPushButton("Abrir")
        b.setObjectName("Link")
        b.setToolTip("Abrir em uma nova aba do M-Search+")
        b.clicked.connect(lambda: self.open_clicked.emit(r.url))
        bottom.addWidget(b)
        b = QPushButton("Copiar URL")
        b.setObjectName("Link")
        b.clicked.connect(lambda: self.copy_clicked.emit(r.url))
        bottom.addWidget(b)
        self.fav = QPushButton("★" if self._fav else "☆")
        self.fav.setObjectName("Link")
        self.fav.setToolTip("Favoritar (fica disponível offline)")
        self.fav.clicked.connect(self._toggle_fav)
        bottom.addWidget(self.fav)
        lay.addLayout(bottom)

    def contextMenuEvent(self, event) -> None:
        menu, r = QMenu(self), self._r
        menu.addAction("Abrir em nova aba", lambda: self.open_clicked.emit(r.url))
        if self._has_cached:
            menu.addAction("Abrir cópia salva (offline)", lambda: self.cached_clicked.emit(r.url))
        menu.addAction("Copiar URL", lambda: self.copy_clicked.emit(r.url))
        if r.url.lower().startswith(("http://", "https://")):
            menu.addAction("Salvar página para uso offline", lambda: self.save_offline_clicked.emit(r.url))
            menu.addAction("Abrir no navegador externo", lambda: self.external_clicked.emit(r.url))
        menu.exec(event.globalPos())

    def _toggle_fav(self) -> None:
        self._fav = not self._fav
        self.fav.setText("★" if self._fav else "☆")
        self.favorite_clicked.emit(self._r.doc_id, self._r.url, self._fav)


class ResultsView(QScrollArea):
    open_requested = pyqtSignal(str)
    cached_requested = pyqtSignal(str)
    favorite_toggled = pyqtSignal(int, str, bool)
    external_requested = pyqtSignal(str)
    copy_requested = pyqtSignal(str)
    save_offline_requested = pyqtSignal(str)
    more_requested = pyqtSignal()

    def __init__(self, has_cached: Callable[[str], bool], parent=None):
        super().__init__(parent)
        self._has_cached = has_cached
        self._link_color = "#1a4fd6"
        self.setWidgetResizable(True)
        inner = QWidget()
        self._lay = QVBoxLayout(inner)
        self._lay.setContentsMargins(4, 8, 12, 16)
        self._lay.setSpacing(12)
        self.summary = QLabel("")
        self.summary.setObjectName("Muted")
        self.message = QLabel("")
        self.message.setWordWrap(True)
        self.message.setObjectName("Notice")
        self.cards = QVBoxLayout()
        self.cards.setSpacing(12)
        self.more = QPushButton("Carregar mais resultados")
        self.more.clicked.connect(self.more_requested)
        self.more.hide()
        for w in (self.summary, self.message):
            self._lay.addWidget(w)
        self._lay.addLayout(self.cards)
        self._lay.addWidget(self.more, alignment=Qt.AlignmentFlag.AlignHCenter)
        self._lay.addStretch(1)
        self.setWidget(inner)

    def set_link_color(self, color: str) -> None:
        self._link_color = color

    def clear(self) -> None:
        while self.cards.count():
            item = self.cards.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.summary.setText("")
        self.message.setText("")
        self.more.hide()

    def show_response(self, resp: SearchResponse, append: bool = False) -> None:
        if not append:
            self.clear()
            self.verticalScrollBar().setValue(0)
        mode = "Offline: índice local" if resp.mode == "offline" else "Online: índice local"
        shown = resp.offset + len(resp.results)
        self.summary.setText(f"{resp.total} resultado(s) · mostrando {shown} · {resp.elapsed_ms:.1f} ms · {mode}")
        self.message.setText(resp.message)
        self.message.setVisible(bool(resp.message))
        for r in resp.results:
            card = ResultCard(r, self._has_cached(r.url), self._link_color)
            card.open_clicked.connect(self.open_requested)
            card.cached_clicked.connect(self.cached_requested)
            card.favorite_clicked.connect(self.favorite_toggled)
            card.external_clicked.connect(self.external_requested)
            card.copy_clicked.connect(self.copy_requested)
            card.save_offline_clicked.connect(self.save_offline_requested)
            self.cards.addWidget(card)
        self.more.setVisible(resp.has_more)
