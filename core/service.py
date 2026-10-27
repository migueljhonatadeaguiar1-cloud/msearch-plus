"""SearchPlusService — a única porta de entrada para qualquer frontend.

Hoje é chamada diretamente pela UI PyQt6. Na V2, uma API REST (ex.: FastAPI) apenas expõe estes métodos;
o motor, o crawler e o índice não precisam mudar.
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable

from config.settings import AppPaths, Settings, default_data_dir, load_settings, save_settings
from core.models import SearchResponse
from crawler.crawler import CrawlStats, Crawler
from database.database import Database
from index.indexer import Indexer
from index.tokenizer import Tokenizer
from offline.offline_engine import ConnectivityMonitor, OfflineEngine
from privacy.privacy_manager import PrivacyManager
from search.engine import SearchEngine

SAMPLE_DIR = Path(__file__).resolve().parent.parent / "sample_pages"


class OfflineError(RuntimeError):
    pass


class SearchPlusService:
    def __init__(self, data_dir: Path | str | None = None):
        self.paths = AppPaths(Path(data_dir) if data_dir else default_data_dir())
        self.paths.ensure()
        self.settings: Settings = load_settings(self.paths.settings_file)
        self.db = Database(self.paths.db_file)
        self.tokenizer = Tokenizer()
        self.indexer = Indexer(self.db, self.tokenizer)
        self.engine = SearchEngine(self.db, self.tokenizer)
        self.connectivity = ConnectivityMonitor(self.settings)
        self.offline = OfflineEngine(self.db, self.indexer, self.paths, self.settings)
        self.privacy = PrivacyManager(self.db, self.paths, self.settings)

    # ------------------------------------------------------------------ busca
    def search(self, text: str, offset: int = 0, limit: int | None = None) -> SearchResponse:
        limit = limit or self.settings.results_per_page
        resp = self.engine.search(text, offset=offset, limit=limit)
        online = self.connectivity.online
        resp.mode = "online" if online else "offline"
        if resp.total == 0 and not resp.message:
            resp.message = self.offline.empty_message(online)
        if offset == 0:
            self.privacy.record_search(text)
        return resp

    # -------------------------------------------------------------- indexação
    def crawl(self, seeds: list[str], *, max_pages: int | None = None, max_depth: int | None = None,
              stop_event: threading.Event | None = None,
              on_event: Callable[[str, str], None] | None = None) -> CrawlStats:
        if not self.connectivity.online:
            raise OfflineError("Sem conexão: o crawler só funciona online. A pesquisa local continua disponível.")
        crawler = Crawler(self.settings, self.indexer, self.db, on_event=on_event, stop_event=stop_event)
        return crawler.crawl(seeds, max_pages=max_pages, max_depth=max_depth)

    # ------------------------------------------------- navegador interno / offline
    def browser_target(self, url: str) -> tuple[str | None, str]:
        return self.offline.browser_target(url, self.connectivity.online)

    def save_page_offline(self, url: str, *, stop_event: threading.Event | None = None,
                          on_progress: Callable[[int, str], None] | None = None):
        if not self.connectivity.online:
            raise OfflineError("Sem conexão: não é possível baixar a página agora.")
        report = self.offline.save_full(url, stop=stop_event, on_progress=on_progress)
        if report.page and not self.db.get_meta_by_url(report.url):
            self.indexer.add_page(report.page)          # a página salva também passa a ser pesquisável
        return report

    def load_sample_pages(self) -> dict[str, int]:
        return self.offline.import_path(SAMPLE_DIR)

    # -------------------------------------------------------- navegador interno
    def offline_copy_for(self, url: str):
        """Caminho de uma cópia salva da URL (tenta a URL original e a normalizada) ou None."""
        from crawler.urls import normalize_url
        for candidate in (url, normalize_url(url)):
            if candidate:
                path = self.offline.cached_copy_path(candidate)
                if path:
                    return path
        return None

    def record_visit(self, url: str, title: str = "") -> None:
        if self.settings.save_browsing_history:
            self.db.add_browse_history(url, title)

    def browse_history(self, limit: int = 200):
        return self.db.list_browse_history(limit)

    # ---------------------------------------------------------------- utilidades
    def stats(self) -> dict:
        return self.db.stats()

    def save_settings(self) -> None:
        save_settings(self.settings, self.paths.settings_file)

    def close(self) -> None:
        try:
            self.privacy.on_exit()
        finally:
            self.db.close()
