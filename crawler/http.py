"""Cliente HTTP mínimo e educado (urllib): timeout, limite de tamanho, redirecionamentos validados."""
from __future__ import annotations

import ipaddress
import socket
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

from config.settings import Settings


class FetchError(Exception):
    pass


@dataclass
class FetchResult:
    url: str                     # URL final (após redirecionamentos)
    status: int = 0              # 0 = falha de rede
    content_type: str = ""
    charset: str | None = None
    body: bytes = b""
    error: str | None = None
    redirected: bool = False
    truncated: bool = False
    retry_after: float | None = None


class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self, max_redirections: int, validator):
        self.max_redirections = max_redirections
        self._validator = validator

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        self._validator(urljoin(req.full_url, newurl))
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class HttpClient:
    def __init__(self, settings: Settings):
        self.s = settings

    def _validate(self, url: str) -> None:
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise FetchError("esquema não suportado")
        if self.s.allow_local_network:
            return
        try:
            infos = socket.getaddrinfo(parts.hostname, parts.port or (443 if parts.scheme == "https" else 80))
        except socket.gaierror as e:
            raise FetchError(f"DNS: {e}") from e
        for info in infos:
            ip = ipaddress.ip_address(info[4][0].split("%")[0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
                raise FetchError("endereço de rede local/privada bloqueado")

    def fetch(self, url: str, *, max_bytes: int | None = None, accept: str | None = None,
              referer: str | None = None) -> FetchResult:
        max_bytes = max_bytes or self.s.max_page_bytes
        try:
            self._validate(url)
            headers = {
                "User-Agent": self.s.user_agent,
                "Accept": accept or "text/html,application/xhtml+xml;q=0.9,text/plain;q=0.5",
                "Accept-Encoding": "identity",
            }
            if referer:
                headers["Referer"] = referer
            req = urllib.request.Request(url, headers=headers)
            opener = urllib.request.build_opener(_SafeRedirect(self.s.max_redirects, self._validate))
            with opener.open(req, timeout=self.s.timeout_s) as resp:
                final = resp.geturl()
                deadline = time.monotonic() + self.s.timeout_s * 3
                chunks, size, truncated = [], 0, False
                while True:
                    chunk = resp.read(16384)
                    if not chunk:
                        break
                    chunks.append(chunk)
                    size += len(chunk)
                    if size >= max_bytes or time.monotonic() > deadline:
                        truncated = True
                        break
                return FetchResult(url=final, status=resp.status, content_type=resp.headers.get_content_type(),
                                   charset=resp.headers.get_content_charset(), body=b"".join(chunks)[:max_bytes],
                                   redirected=final != url, truncated=truncated)
        except urllib.error.HTTPError as e:
            retry = e.headers.get("Retry-After") if e.headers else None
            e.close()
            return FetchResult(url=url, status=e.code, error=f"HTTP {e.code}",
                               retry_after=float(retry) if retry and retry.isdigit() else None)
        except FetchError as e:
            return FetchResult(url=url, error=str(e))
        except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError, OSError, ValueError) as e:
            reason = getattr(e, "reason", e)
            return FetchResult(url=url, error=f"falha de conexão: {reason}")
