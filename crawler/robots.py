"""Política de robots.txt (RFC 9309, simplificada) com cache por host.

    404/4xx  → sem restrições          5xx/erro de rede → não rastrear (conservador)
"""
from __future__ import annotations

import time
from typing import Callable
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

# fetch(url) -> (status, texto | None)
RobotsFetcher = Callable[[str], tuple[int, str | None]]


class RobotsPolicy:
    def __init__(self, fetch: RobotsFetcher, agent: str = "SearchPlusBot", ttl_s: float = 3600, enabled: bool = True):
        self._fetch, self._agent, self._ttl, self.enabled = fetch, agent, ttl_s, enabled
        self._cache: dict[str, tuple[float, str, RobotFileParser | None]] = {}

    def _entry(self, url: str) -> tuple[str, RobotFileParser | None]:
        p = urlsplit(url)
        origin = f"{p.scheme}://{p.netloc}"
        hit = self._cache.get(origin)
        if hit and time.time() - hit[0] < self._ttl:
            return hit[1], hit[2]
        status, text = self._fetch(f"{origin}/robots.txt")
        parser: RobotFileParser | None = None
        if status == 200 and text is not None:
            mode, parser = "rules", RobotFileParser()
            parser.parse(text.splitlines())
        elif 400 <= status < 500:
            mode = "allow_all"
        else:
            mode = "disallow_all"
        self._cache[origin] = (time.time(), mode, parser)
        return mode, parser

    def can_fetch(self, url: str) -> bool:
        if not self.enabled:
            return True
        mode, parser = self._entry(url)
        if mode == "allow_all":
            return True
        if mode == "disallow_all" or parser is None:
            return False
        return parser.can_fetch(self._agent, url)

    def crawl_delay(self, url: str) -> float | None:
        if not self.enabled:
            return None
        _, parser = self._entry(url)
        if parser is None:
            return None
        delay = parser.crawl_delay(self._agent)
        return float(delay) if delay is not None else None
