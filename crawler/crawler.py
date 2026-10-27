"""Crawler educado do M-Search+.

Fluxo por URL:  robots.txt → (cache recente?) → espera por domínio → HTTP → parser → cache → indexador → links
"""
from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Callable
from urllib.parse import urlsplit

from config.settings import BOT_TOKEN, Settings
from crawler.http import FetchResult, HttpClient
from crawler.parser import decode_html, parse_html
from crawler.robots import RobotsPolicy
from crawler.urls import host_key, is_crawlable_extension, normalize_url
from database.database import Database
from index.indexer import Indexer

EventCallback = Callable[[str, str], None]    # (tipo, mensagem)
MAX_CRAWL_DELAY_S = 30.0
HTML_TYPES = {"text/html", "application/xhtml+xml", "text/plain"}


@dataclass
class CrawlStats:
    processed: int = 0
    indexed: int = 0
    updated: int = 0
    unchanged: int = 0
    duplicates: int = 0
    blocked_by_robots: int = 0
    noindex: int = 0
    from_cache: int = 0
    errors: int = 0
    discovered: int = 0
    stopped: bool = False
    log: list[str] = field(default_factory=list)

    def summary(self) -> str:
        return (f"{self.processed} páginas processadas · {self.indexed} novas · {self.updated} atualizadas · "
                f"{self.duplicates} duplicadas · {self.blocked_by_robots} bloqueadas pelo robots.txt · "
                f"{self.errors} erros")


class Crawler:
    def __init__(self, settings: Settings, indexer: Indexer, db: Database, *,
                 on_event: EventCallback | None = None, stop_event: threading.Event | None = None):
        self.s = settings
        self.indexer = indexer
        self.db = db
        self.client = HttpClient(settings)
        self.stop = stop_event or threading.Event()
        self._emit_cb = on_event
        self._last_hit: dict[str, float] = {}
        self._paused_hosts: set[str] = set()
        self.robots = RobotsPolicy(self._fetch_robots, BOT_TOKEN)

    # ----------------------------------------------------------------- helpers
    def _emit(self, kind: str, msg: str) -> None:
        if self._emit_cb:
            self._emit_cb(kind, msg)

    def _wait_turn(self, url: str, delay: float) -> None:
        host = host_key(url)
        wait = self._last_hit.get(host, 0.0) + delay - time.monotonic()
        if wait > 0:
            self.stop.wait(wait)          # espera interrompível
        self._last_hit[host] = time.monotonic()

    def _fetch_robots(self, robots_url: str) -> tuple[int, str | None]:
        self._wait_turn(robots_url, self.s.request_delay_s)
        res = self.client.fetch(robots_url, max_bytes=500_000)
        self._last_hit[host_key(robots_url)] = time.monotonic()
        if res.status == 200:
            return 200, decode_html(res.body, res.charset)
        return (res.status or 599), None

    def _delay_for(self, url: str) -> float:
        d = self.robots.crawl_delay(url)
        return min(max(self.s.request_delay_s, d or 0.0), MAX_CRAWL_DELAY_S)

    # -------------------------------------------------------------------- main
    def crawl(self, seeds: list[str], *, max_pages: int | None = None, max_depth: int | None = None) -> CrawlStats:
        max_pages = max_pages if max_pages is not None else self.s.max_pages_per_run
        max_depth = max_depth if max_depth is not None else self.s.max_depth
        stats = CrawlStats()
        queue: deque[tuple[str, int]] = deque()
        seen: set[str] = set()
        seed_hosts: set[str] = set()
        for raw in seeds:
            url = normalize_url(raw if "://" in raw else f"https://{raw}")
            if url and url not in seen:
                seen.add(url)
                seed_hosts.add(host_key(url))
                queue.append((url, 0))

        while queue and stats.processed < max_pages:
            if self.stop.is_set():
                stats.stopped = True
                self._emit("info", "Indexação interrompida.")
                break
            url, depth = queue.popleft()
            if host_key(url) in self._paused_hosts:
                continue
            links = self._process(url, depth, stats, seen)
            if links and depth < max_depth:
                for link in links:
                    n = normalize_url(link)
                    if not n or n in seen or not is_crawlable_extension(n):
                        continue
                    if not self.s.follow_external_links and host_key(n) not in seed_hosts:
                        continue
                    seen.add(n)
                    stats.discovered += 1
                    queue.append((n, depth + 1))
        self._emit("done", stats.summary())
        return stats

    def _process(self, url: str, depth: int, stats: CrawlStats, seen: set[str]) -> list[str]:
        if not self.robots.can_fetch(url):
            stats.blocked_by_robots += 1
            self._emit("skip", f"robots.txt bloqueia: {url}")
            return []

        html: str | None = None
        final_url = url
        meta = self.db.get_meta_by_url(url)
        fresh = meta and (time.time() - meta.fetched_at) < self.s.recrawl_after_hours * 3600
        cached = self.db.cache_get(url) if (fresh and self.s.cache_enabled) else None
        if cached is not None:
            html = decode_html(cached)
            stats.from_cache += 1
            self._emit("cache", f"(cache) {url}")
        else:
            self._wait_turn(url, self._delay_for(url))
            res = self.client.fetch(url)
            if not self._accept(res, url, stats):
                return []
            final_url = self._final_url(res, url, seen, stats)
            if final_url is None:
                return []
            html = decode_html(res.body, res.charset)
            if self.s.cache_enabled:
                self.db.cache_put(final_url, res.body, res.content_type)

        stats.processed += 1
        page = parse_html(html, final_url)
        outcome = self.indexer.add_page(page)
        counter = {"indexed": "indexed", "updated": "updated", "unchanged": "unchanged",
                   "duplicate": "duplicates", "noindex": "noindex"}.get(outcome.status)
        if counter:
            setattr(stats, counter, getattr(stats, counter) + 1)
        label = {"indexed": "indexada", "updated": "atualizada", "unchanged": "sem mudanças",
                 "duplicate": f"duplicada de {outcome.duplicate_of}", "noindex": "noindex (ignorada)",
                 "empty": "sem texto"}[outcome.status]
        self._emit("ok", f"[{depth}] {final_url} → {label}")
        return [] if page.nofollow else page.links

    def _accept(self, res: FetchResult, url: str, stats: CrawlStats) -> bool:
        if res.status in (429, 503):
            self._paused_hosts.add(host_key(url))
            stats.errors += 1
            self._emit("error", f"{url}: servidor pediu para reduzir o ritmo (HTTP {res.status}); domínio pausado")
            return False
        if res.error or not (200 <= res.status < 300):
            stats.errors += 1
            self._emit("error", f"{url}: {res.error or 'HTTP ' + str(res.status)}")
            return False
        if res.content_type not in HTML_TYPES:
            self._emit("skip", f"{url}: tipo ignorado ({res.content_type})")
            return False
        return True

    def _final_url(self, res: FetchResult, url: str, seen: set[str], stats: CrawlStats) -> str | None:
        final = normalize_url(res.url) or url
        if final != url:
            if final in seen:
                stats.duplicates += 1
                self._emit("skip", f"{url} redireciona para {final} (já visitada)")
                return None
            seen.add(final)
            if urlsplit(final).netloc != urlsplit(url).netloc and not self.robots.can_fetch(final):
                stats.blocked_by_robots += 1
                self._emit("skip", f"robots.txt bloqueia destino do redirecionamento: {final}")
                return None
        return final
