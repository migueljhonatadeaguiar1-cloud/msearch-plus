"""Modo offline: conectividade, favoritos, arquivos locais e cópias salvas.

Regra de ouro: o M-Search+ NUNCA finge pesquisar a internet sem conexão. Offline, só existe o índice local.
"""
from __future__ import annotations

import hashlib
import re
import socket
import time
from pathlib import Path
from urllib.parse import urlsplit

from config.settings import AppPaths, Settings
from crawler.parser import decode_html, parse_html, parse_plain_text
from crawler.urls import normalize_url
from database.database import Database
from index.indexer import Indexer
from offline.page_library import SavedPageLibrary
from offline.page_saver import (FetchedResource, HttpFetcher, LocalFetcher, PageSaver, SaveError, SaveReport,
                                text_to_html)
from urllib.request import url2pathname

OFFLINE_MESSAGE = "Este conteúdo não está disponível no índice offline."
LOCAL_EXTENSIONS = {".html", ".htm", ".xhtml", ".txt", ".md"}
MAX_LOCAL_FILE_BYTES = 5_000_000


class ConnectivityMonitor:
    """Detecta conexão abrindo uma conexão TCP curta (nenhum byte é enviado) ou obedece ao modo forçado."""

    def __init__(self, settings: Settings):
        self._s = settings
        self._online: bool | None = None

    def probe(self) -> bool:
        mode = self._s.connectivity_mode
        if mode == "offline":
            online = False
        elif mode == "online":
            online = True
        else:
            try:
                with socket.create_connection((self._s.connectivity_check_host,
                                               self._s.connectivity_check_port), timeout=2.5):
                    online = True
            except OSError:
                online = False
        self._online = online
        return online

    @property
    def online(self) -> bool:
        return self.probe() if self._online is None else self._online

    @property
    def forced(self) -> bool:
        return self._s.connectivity_mode != "auto"

    def offline_now(self) -> bool:
        """Leitura SEM rede e sem bloqueio (segura para threads de IO do WebEngine)."""
        return self._online is False


_CSP = ('<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; img-src data:; '
        'style-src \'unsafe-inline\'">')
_SCRIPT = re.compile(r"<script\b.*?</script\s*>", re.I | re.S)


class OfflineEngine:
    def __init__(self, db: Database, indexer: Indexer, paths: AppPaths, settings: Settings | None = None):
        self.db, self.indexer, self.paths = db, indexer, paths
        self.settings = settings or Settings()
        self.library = SavedPageLibrary(db, paths)

    # ------------------------------------------- páginas completas (navegador)
    def has_offline_copy(self, url: str) -> bool:
        if url.startswith("file:"):
            return True
        n = normalize_url(url) or url
        return self.library.find_by_url(n) is not None or self.db.cache_has(url)

    def saved_copy_url(self, url: str) -> str | None:
        """URL searchplus-offline:// da cópia salva (ou None). Promove o cache do crawler se necessário."""
        if url.startswith("file:"):
            return self.ensure_local_copy(url)
        n = normalize_url(url) or url
        page = self.library.find_by_url(n)
        if page:
            return self.library.offline_url(page.page_id)
        raw = self.db.cache_get(url) or self.db.cache_get(n)
        if raw is not None:
            try:
                report = PageSaver(self.library, None).save(
                    n, main=FetchedResource(n, raw, "text/html"), kind="html_only")
                return self.library.offline_url(report.page_id)
            except SaveError:
                return None
        return None

    def save_full(self, url: str, *, stop=None, on_progress=None) -> SaveReport:
        """Baixa a página e todos os recursos (exige conexão; quem chama verifica)."""
        saver = PageSaver(self.library, HttpFetcher(self.settings), stop=stop, on_progress=on_progress)
        return saver.save(url)

    def ensure_local_copy(self, file_url: str) -> str | None:
        """Abre um arquivo local no navegador SEM file://: gera uma cópia isolada servida pelo esquema offline."""
        try:
            path = Path(url2pathname(urlsplit(file_url).path)).resolve(strict=True)
        except OSError:
            return None
        if not path.is_file():
            return None
        uri = path.as_uri()
        existing = self.library.find_by_url(uri)
        if existing and existing.saved_at >= path.stat().st_mtime:
            return self.library.offline_url(existing.page_id)
        try:
            raw = path.read_bytes()
            if path.suffix.lower() in (".html", ".htm", ".xhtml"):
                main = FetchedResource(uri, raw, "text/html")
                saver = PageSaver(self.library, LocalFetcher(path.parent))
                report = saver.save(uri, main=main, kind="local")
            else:
                title = path.name
                main = FetchedResource(uri, text_to_html(decode_html(raw), title), "text/html")
                report = PageSaver(self.library, None).save(uri, main=main, kind="local")
            return self.library.offline_url(report.page_id)
        except (OSError, SaveError):
            return None

    def browser_target(self, url: str, online: bool) -> tuple[str | None, str]:
        """Decide o que o navegador interno carrega: (url_qt, modo) com modo online | offline | unavailable."""
        if url.startswith("file:"):
            copy = self.ensure_local_copy(url)
            return (copy, "offline") if copy else (None, "unavailable")
        if online:
            return url, "online"
        copy = self.saved_copy_url(url)
        return (copy, "offline") if copy else (None, "unavailable")

    # --------------------------------------------------------------- favoritos
    def set_favorite(self, url: str, title: str = "", note: str = "", favorite: bool = True) -> bool:
        """Favorita uma página já indexada; se não estiver no índice, cria uma entrada 'bookmark'."""
        if not favorite:
            meta = self.db.get_meta_by_url(url)
            rows = [d for d in self.db.list_documents("bookmark", 10_000) if d.url == url]
            if rows:
                return self.db.delete_by_url(url)
            return bool(meta) and self.db.set_favorite(url, False)
        if self.db.set_favorite(url, True):
            return True
        page = parse_plain_text(note or title or url, url, title or url)
        outcome = self.indexer.add_page(page, source="bookmark")
        if outcome.status in ("indexed", "updated", "unchanged"):
            self.db.set_favorite(url, True)
            return True
        return False

    # --------------------------------------------------------- arquivos locais
    def import_path(self, path: str | Path, recursive: bool = True) -> dict[str, int]:
        root = Path(path)
        files = [root] if root.is_file() else sorted(root.rglob("*") if recursive else root.glob("*"))
        counts = {"imported": 0, "skipped": 0, "errors": 0}
        for f in files:
            if not f.is_file() or f.suffix.lower() not in LOCAL_EXTENSIONS:
                continue
            try:
                if f.stat().st_size > MAX_LOCAL_FILE_BYTES:
                    counts["skipped"] += 1
                    continue
                raw = f.read_bytes()
                text = decode_html(raw)
                uri = f.resolve().as_uri()
                if f.suffix.lower() in (".html", ".htm", ".xhtml"):
                    page = parse_html(text, uri)
                    page.links = []
                    if not page.title:
                        page.title = f.stem
                else:
                    title = next((ln.lstrip("# ").strip() for ln in text.splitlines() if ln.strip()), f.stem)
                    page = parse_plain_text(text, uri, title[:120] or f.stem)
                page.noindex = False       # arquivo local do próprio usuário: sempre indexa
                outcome = self.indexer.add_page(page, source="local")
                counts["imported" if outcome.status in ("indexed", "updated", "unchanged") else "skipped"] += 1
            except OSError:
                counts["errors"] += 1
        return counts

    # ------------------------------------------------------------ cópias salvas
    def has_cached_copy(self, url: str) -> bool:
        return self.db.cache_has(url)

    def cached_copy_path(self, url: str) -> Path | None:
        raw = self.db.cache_get(url)
        if raw is None:
            return None
        html = _SCRIPT.sub("", decode_html(raw))
        banner = (f'<div style="font:13px sans-serif;background:#fff8d6;border-bottom:1px solid #e0c200;'
                  f'padding:8px 12px">Cópia salva pelo M-Search+ ({time.strftime("%d/%m/%Y %H:%M")}) — '
                  f'origem: {urlsplit(url).netloc}. Scripts e recursos externos foram desativados.</div>')
        m = re.search(r"<head[^>]*>", html, re.I)
        html = html[:m.end()] + _CSP + html[m.end():] if m else _CSP + html
        b = re.search(r"<body[^>]*>", html, re.I)
        html = html[:b.end()] + banner + html[b.end():] if b else html + banner
        self.paths.offline_view_dir.mkdir(parents=True, exist_ok=True)
        out = self.paths.offline_view_dir / (hashlib.sha1(url.encode()).hexdigest()[:16] + ".html")
        out.write_text(html, encoding="utf-8")
        return out

    @staticmethod
    def empty_message(online: bool) -> str:
        if not online:
            return OFFLINE_MESSAGE
        return ("Nenhum resultado no índice local. Use “Indexar” para adicionar sites "
                "ou carregue as páginas de exemplo.")
