"""Perfil do navegador interno: configurações de segurança/privacidade, interceptor, cookies e esquema offline.

Segurança (resumo)
  • Sem acesso a file://: LocalContentCanAccessFileUrls/RemoteUrls = False; esquemas perigosos bloqueados.
  • Permissões (câmera, microfone, localização, notificações, área de transferência): sempre negadas.
  • Pop-ups sem gesto do usuário: bloqueados. Conteúdo misto inseguro: bloqueado. Plugins: desligados.
  • Erros de certificado: a página NÃO carrega (não há botão "continuar assim mesmo").
  • WebRTC só com interfaces públicas (não vaza IP local); tela cheia e captura de tela desativadas.
  • Páginas offline (searchplus-offline://) nunca fazem requisições http(s); offline, ninguém faz.
Privacidade
  • Cookies de terceiros sempre bloqueados; de primeiro nível só se o usuário permitir (e então persistem).
  • Cache em disco, histórico e armazenamento local só se o usuário permitir; nada é enviado a serviços externos.
"""
from __future__ import annotations

import shutil

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWebEngineCore import (QWebEngineProfile, QWebEngineSettings, QWebEngineUrlRequestInterceptor)

from core.service import SearchPlusService
from offline.page_library import SCHEME
from ui.browser.download_manager import DownloadManager
from ui.browser.offline_scheme import OfflineSchemeHandler, register_scheme

PROFILE_NAME = "SearchPlusBrowser"


def register_schemes() -> None:
    register_scheme()


def _set(ws: QWebEngineSettings, attr: str, value: bool) -> None:
    """Define um atributo se ele existir nesta versão do Qt."""
    enum = getattr(QWebEngineSettings.WebAttribute, attr, None)
    if enum is not None:
        ws.setAttribute(enum, value)


class _Interceptor(QWebEngineUrlRequestInterceptor):
    blocked = pyqtSignal(str, str)      # (id da página offline, URL bloqueada)

    def __init__(self, service: SearchPlusService, parent=None):
        super().__init__(parent)
        self.service = service

    def interceptRequest(self, info) -> None:          # roda na thread de IO do Chromium
        url = info.requestUrl()
        scheme = url.scheme().lower()
        if scheme in ("http", "https"):
            first = info.firstPartyUrl()
            if first.scheme().lower() == SCHEME:        # página salva tentando falar com a internet
                info.block(True)
                self.blocked.emit(first.host(), url.toString())
            elif self.service.connectivity.offline_now():   # modo offline: nada sai do computador
                info.block(True)
        elif scheme in ("file", "ftp"):
            info.block(True)


class BrowserEngine(QObject):
    blocked = pyqtSignal(str, str)

    def __init__(self, service: SearchPlusService, parent=None):
        super().__init__(parent)
        self.service = service
        self._allow_cookies = False
        self._purge_unwanted_storage()
        base = service.paths.webengine_dir
        self.profile = QWebEngineProfile(PROFILE_NAME, self)
        self.profile.setPersistentStoragePath(str(base / "data"))
        self.profile.setCachePath(str(base / "cache"))
        self.interceptor = _Interceptor(service, self)
        self.interceptor.blocked.connect(self.blocked)
        self.profile.setUrlRequestInterceptor(self.interceptor)
        self.scheme_handler = OfflineSchemeHandler(service.offline.library, self)
        self.profile.installUrlSchemeHandler(SCHEME.encode("ascii"), self.scheme_handler)
        self.profile.cookieStore().setCookieFilter(self._cookie_filter)
        self.downloads = DownloadManager(service, self.profile, self)
        self.apply_settings()

    # ------------------------------------------------------------ configuração
    def _purge_unwanted_storage(self) -> None:
        """Dados do WebEngine só sobrevivem entre execuções se o usuário permitiu (cookies / cache)."""
        s, base = self.service.settings, self.service.paths.webengine_dir
        if not s.browser_allow_cookies or s.clear_data_on_exit:
            shutil.rmtree(base / "data", ignore_errors=True)
        if not s.browser_keep_cache or s.clear_data_on_exit:
            shutil.rmtree(base / "cache", ignore_errors=True)

    def _cookie_filter(self, request) -> bool:         # thread de IO; só lê atributos simples
        if not self._allow_cookies:
            return False
        return not bool(getattr(request, "thirdParty", False))

    def apply_settings(self) -> None:
        s, p = self.service.settings, self.profile
        self._allow_cookies = s.browser_allow_cookies
        P = QWebEngineProfile
        p.setPersistentCookiesPolicy(P.PersistentCookiesPolicy.AllowPersistentCookies if s.browser_allow_cookies
                                     else P.PersistentCookiesPolicy.NoPersistentCookies)
        p.setHttpCacheType(P.HttpCacheType.DiskHttpCache if s.browser_keep_cache else P.HttpCacheType.MemoryHttpCache)
        policy = getattr(P, "PersistentPermissionsPolicy", None)
        if policy is not None and hasattr(p, "setPersistentPermissionsPolicy"):
            p.setPersistentPermissionsPolicy(policy.AskEveryTime)
        ws = p.settings()
        _set(ws, "JavascriptEnabled", s.browser_javascript)
        _set(ws, "JavascriptCanOpenWindows", False)            # sem pop-ups sem gesto do usuário
        _set(ws, "JavascriptCanAccessClipboard", False)
        _set(ws, "AllowWindowActivationFromJavaScript", False)
        _set(ws, "LocalStorageEnabled", s.browser_allow_cookies)
        _set(ws, "LocalContentCanAccessFileUrls", False)
        _set(ws, "LocalContentCanAccessRemoteUrls", False)
        _set(ws, "AllowRunningInsecureContent", False)
        _set(ws, "AllowGeolocationOnInsecureOrigins", False)
        _set(ws, "PluginsEnabled", False)
        _set(ws, "FullScreenSupportEnabled", False)
        _set(ws, "ScreenCaptureEnabled", False)
        _set(ws, "WebRTCPublicInterfacesOnly", True)
        _set(ws, "DnsPrefetchEnabled", False)
        _set(ws, "HyperlinkAuditingEnabled", False)
        _set(ws, "NavigateOnDropEnabled", False)
        _set(ws, "PdfViewerEnabled", True)
        _set(ws, "ErrorPageEnabled", True)
        _set(ws, "AutoLoadIconsForPage", True)
        if not s.browser_store_history:
            p.clearAllVisitedLinks()

    def clear_browsing_data(self) -> None:
        self.profile.clearHttpCache()
        self.profile.cookieStore().deleteAllCookies()
        self.profile.clearAllVisitedLinks()
        self.service.privacy.clear_browsing_history()

    def shutdown(self) -> None:
        if not self.service.settings.browser_store_history:
            self.profile.clearAllVisitedLinks()
        if self.service.settings.clear_data_on_exit:
            self.clear_browsing_data()
