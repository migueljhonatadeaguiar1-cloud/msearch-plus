"""Esquema de URL próprio  searchplus-offline://<id-da-página>/<arquivo>.

Serve APENAS arquivos de dentro da pasta de uma página salva (ver offline/page_library.py). Por ser um esquema
próprio (e não file://), a página salva:
  • não consegue ler outros arquivos do computador;
  • tem origem isolada (cada página = um "host" diferente);
  • passa pelo mesmo interceptor que bloqueia qualquer acesso à internet.
"""
from __future__ import annotations

from PyQt6.QtCore import QBuffer, QByteArray, QIODevice
from PyQt6.QtWebEngineCore import QWebEngineUrlRequestJob, QWebEngineUrlScheme, QWebEngineUrlSchemeHandler

from offline.page_library import SCHEME, SavedPageLibrary, guess_mime

MAX_SERVED_BYTES = 64_000_000


def register_scheme() -> None:
    """Chamar UMA vez, ANTES de criar o QApplication."""
    scheme = QWebEngineUrlScheme(QByteArray(SCHEME.encode("ascii")))
    scheme.setSyntax(QWebEngineUrlScheme.Syntax.Host)
    special = getattr(QWebEngineUrlScheme, "SpecialPort", None)    # PyQt6: enum aninhado (SpecialPort.PortUnspecified)
    if special is not None:
        scheme.setDefaultPort(int(special.PortUnspecified.value))   # -1: sem porta padrão
    # Sem LocalAccessAllowed: páginas do esquema NÃO acessam arquivos locais.
    flags = QWebEngineUrlScheme.Flag.SecureScheme | QWebEngineUrlScheme.Flag.CorsEnabled
    scheme.setFlags(flags)
    QWebEngineUrlScheme.registerScheme(scheme)


class OfflineSchemeHandler(QWebEngineUrlSchemeHandler):
    def __init__(self, library: SavedPageLibrary, parent=None):
        super().__init__(parent)
        self.library = library

    def requestStarted(self, job: QWebEngineUrlRequestJob) -> None:
        if bytes(job.requestMethod()) != b"GET":
            job.fail(QWebEngineUrlRequestJob.Error.RequestDenied)
            return
        url = job.requestUrl()
        path = self.library.resolve_file(url.host(), url.path())
        if path is None:
            job.fail(QWebEngineUrlRequestJob.Error.UrlNotFound)
            return
        try:
            if path.stat().st_size > MAX_SERVED_BYTES:
                job.fail(QWebEngineUrlRequestJob.Error.RequestFailed)
                return
            data = path.read_bytes()
        except OSError:
            job.fail(QWebEngineUrlRequestJob.Error.RequestFailed)
            return
        buf = QBuffer(job)                       # vive enquanto o job viver
        buf.setData(QByteArray(data))
        buf.open(QIODevice.OpenModeFlag.ReadOnly)
        job.reply(QByteArray(guess_mime(path).encode("ascii")), buf)
