"""Utilitários de URL: normalização (evita duplicatas) e filtros."""
from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

_TRACKING_PREFIXES = ("utm_",)
_TRACKING_PARAMS = {"fbclid", "gclid", "msclkid", "mc_cid", "mc_eid", "igshid", "ref_src"}
_SKIP_EXT = {
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".ico", ".bmp", ".pdf", ".zip", ".rar", ".7z", ".gz",
    ".tar", ".exe", ".msi", ".dmg", ".apk", ".mp3", ".mp4", ".avi", ".mkv", ".mov", ".wav", ".css", ".js",
    ".json", ".xml", ".woff", ".woff2", ".ttf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
}


def normalize_url(url: str, base: str | None = None) -> str | None:
    """Devolve a URL canônica (http/https) ou None se não for rastreável."""
    try:
        if base:
            url = urljoin(base, url.strip())
        parts = urlsplit(url.strip())
        if parts.scheme not in ("http", "https") or not parts.hostname:
            return None
        host = parts.hostname.lower()
        port = parts.port
    except ValueError:
        return None
    netloc = host if port in (None, 80 if parts.scheme == "http" else 443) else f"{host}:{port}"
    query = urlencode([(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
                       if k.lower() not in _TRACKING_PARAMS and not k.lower().startswith(_TRACKING_PREFIXES)])
    out = urlunsplit((parts.scheme, netloc, parts.path or "/", query, ""))   # sem fragmento nem credenciais
    return out if len(out) <= 2000 else None


def host_key(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def is_crawlable_extension(url: str) -> bool:
    path = urlsplit(url).path.lower()
    dot = path.rfind(".")
    return dot == -1 or path[dot:] not in _SKIP_EXT or path.rfind("/") > dot
