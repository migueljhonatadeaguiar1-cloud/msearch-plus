"""QWebEngineView / QWebEnginePage com política de navegação segura.

Regras de navegação (página principal):
  http/https          → permitido (offline: troca pela cópia salva, se existir; senão mostra "indisponível")
  searchplus-offline  → permitido, mas uma página http(s) NÃO pode redirecionar/linkar para páginas salvas
  file:               → nunca carregado direto; vira uma cópia isolada (searchplus-offline) do arquivo local
  javascript:, data:, ftp:, blob:, qrc:, mailto: ...  → bloqueado
"""
from __future__ import annotations

import html
from typing import Protocol

from PyQt6.QtCore import QTimer, QUrl
from PyQt6.QtGui import QContextMenuEvent
from PyQt6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import QMenu

from offline.page_library import SCHEME

NavType = QWebEnginePage.NavigationType


class BrowserHooks(Protocol):
    """O que o navegador precisa saber do resto do app (implementado por BrowserWindow)."""
    def offline_now(self) -> bool: ...
    def saved_copy_url(self, url: str) -> str | None: ...
    def open_local_file(self, url: str) -> str | None: ...
    def on_blocked_navigation(self, url: str, reason: str) -> None: ...
    def create_tab_for_popup(self, background: bool) -> "BrowserView": ...
    def open_external(self, url: str) -> None: ...
    def copy_text(self, text: str) -> None: ...
    def request_save_offline(self, url: str) -> None: ...


UNAVAILABLE_HTML = """<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><title>Indisponível offline</title>
<style>body{{font:16px/1.6 system-ui,sans-serif;max-width:640px;margin:12vh auto;padding:0 1.2rem;color:#333}}
h1{{font-size:1.4rem}}code{{background:#eee;padding:2px 6px;border-radius:4px;word-break:break-all}}</style></head>
<body><h1>Esta página não está disponível no modo offline</h1>
<p>O M-Search+ não consegue acessar a internet agora e não existe uma cópia salva de:</p><p><code>{url}</code></p>
<p>Quando estiver online, abra a página e use <b>Salvar offline</b> (menu ⋮) para guardá-la com CSS, JavaScript,
imagens e fontes. Páginas salvas aparecem nos resultados com o selo <b>Cópia salva</b>.</p></body></html>"""


class BrowserPage(QWebEnginePage):
    def __init__(self, profile: QWebEngineProfile, hooks: BrowserHooks, parent=None):
        super().__init__(profile, parent)
        self.hooks = hooks
        self._internal_html = False
        self.loadFinished.connect(lambda _ok: setattr(self, "_internal_html", False))
        self.certificateError.connect(self._on_certificate_error)
        self.fullScreenRequested.connect(lambda req: req.reject())
        # Permissões (câmera, microfone, localização, notificações...): SEMPRE negadas.
        if hasattr(self, "permissionRequested"):                       # Qt >= 6.8
            self.permissionRequested.connect(lambda perm: perm.deny())
        else:                                                          # Qt 6.0 – 6.7
            self.featurePermissionRequested.connect(
                lambda origin, feature: self.setFeaturePermission(
                    origin, feature, QWebEnginePage.PermissionPolicy.PermissionDeniedByUser))

    def set_internal_html(self, content: str) -> None:
        self._internal_html = True
        self.setHtml(content, QUrl("about:blank"))

    def show_unavailable(self, url: str) -> None:
        self.set_internal_html(UNAVAILABLE_HTML.format(url=html.escape(url)))

    def _on_certificate_error(self, error) -> None:
        error.rejectCertificate()              # nunca aceitar certificado inválido

    def acceptNavigationRequest(self, url: QUrl, nav_type, is_main_frame: bool) -> bool:
        scheme = url.scheme().lower()
        if self._internal_html:
            return True
        if not is_main_frame:
            return scheme in ("http", "https", "about", "blob", "data", SCHEME, "chrome-error")
        if scheme in ("http", "https"):
            if self.hooks.offline_now():
                target = self.hooks.saved_copy_url(url.toString())
                if target:
                    QTimer.singleShot(0, lambda: self.setUrl(QUrl(target)))
                else:
                    QTimer.singleShot(0, lambda: self.show_unavailable(url.toString()))
                return False
            return True
        if scheme == SCHEME:
            if self.url().scheme().lower() in ("http", "https") and nav_type == NavType.NavigationTypeLinkClicked:
                self.hooks.on_blocked_navigation(url.toString(), "Sites da internet não podem abrir páginas salvas.")
                return False
            return True
        if scheme == "file":
            target = self.hooks.open_local_file(url.toString())
            if target and self.url().scheme().lower() == SCHEME:       # link em documento local salvo
                QTimer.singleShot(0, lambda: self.setUrl(QUrl(target)))
            else:
                self.hooks.on_blocked_navigation(url.toString(), "Acesso direto a arquivos locais bloqueado.")
            return False
        if scheme in ("about", "chrome-error"):
            return True
        self.hooks.on_blocked_navigation(url.toString(), f"Esquema “{scheme}:” bloqueado por segurança.")
        return False


class BrowserView(QWebEngineView):
    def __init__(self, profile: QWebEngineProfile, hooks: BrowserHooks, parent=None):
        super().__init__(parent)
        self.hooks = hooks
        self.setPage(BrowserPage(profile, hooks, self))

    # window.open / target=_blank / Ctrl+clique / "Abrir em nova aba" → sempre uma aba do M-Search+
    def createWindow(self, window_type):
        background = window_type == QWebEnginePage.WebWindowType.WebBrowserBackgroundTab
        return self.hooks.create_tab_for_popup(background)

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:
        try:
            menu: QMenu = self.createStandardContextMenu() if hasattr(self, "createStandardContextMenu") \
                else self.page().createStandardContextMenu()
            request = self.lastContextMenuRequest() if hasattr(self, "lastContextMenuRequest") else None
            link = request.linkUrl().toString() if request is not None and request.linkUrl().isValid() else ""
        except Exception:
            super().contextMenuEvent(event)
            return
        menu.addSeparator()
        page_url = self.url().toString()
        if link:
            menu.addAction("Copiar endereço do link", lambda: self.hooks.copy_text(link))
            if link.lower().startswith(("http://", "https://")):
                menu.addAction("Abrir link no navegador externo", lambda: self.hooks.open_external(link))
        if page_url.lower().startswith(("http://", "https://")):
            menu.addAction("Copiar URL da página", lambda: self.hooks.copy_text(page_url))
            menu.addAction("Salvar página para uso offline", lambda: self.hooks.request_save_offline(page_url))
            menu.addAction("Abrir página no navegador externo", lambda: self.hooks.open_external(page_url))
        menu.exec(event.globalPos())
        event.accept()
