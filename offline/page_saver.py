"""Salva uma página COMPLETA para uso offline.

    HTML → baixa CSS, JS, imagens, fontes, mídia → reescreve as referências para caminhos locais

    conteudo_offline/<id>/
        index.html          manifest.json
        css/  js/  images/  fonts/  media/  other/

Como funciona:
  • <link rel=stylesheet/icon/preload>, <script src>, <img src/srcset>, <source>, <video/audio src/poster>,
    <track>, <embed>, <object data> e style="...url()" são baixados e reescritos (ex.: https://x.com/a.css → css/a.css).
  • CSS: url(...) e @import são resolvidos recursivamente (fontes, imagens de fundo, outros CSS), com caminhos
    relativos corretos (css/a.css → ../images/bg.png).
  • Links <a href> e <form action> viram URLs absolutas (clicar offline abre a cópia salva, se existir).
  • <base>, <meta charset>, CSP em <meta>, integrity e crossorigin são removidos/ajustados (o conteúdo agora é local).
  • Recursos que falharem ficam apontando para a URL original — offline eles são bloqueados, nunca falsificados.

Limitações (documentadas, não escondidas): o HTML salvo é o que o servidor entregou; conteúdo montado por JavaScript
a partir de APIs remotas, WebSockets, login e URLs construídas em tempo de execução não funcionam offline.
"""
from __future__ import annotations

import hashlib
import html as html_lib
import json
import mimetypes
import posixpath
import re
import shutil
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Protocol
from urllib.parse import unquote, urljoin, urlsplit
from urllib.request import url2pathname

from config.settings import Settings
from core.models import ParsedPage
from crawler.http import HttpClient
from crawler.parser import decode_html, parse_html
from crawler.urls import normalize_url
from offline.fsutil import safe_filename
from offline.page_library import SavedPage, SavedPageLibrary, guess_mime, page_id_for

HTML_ACCEPT = "text/html,application/xhtml+xml;q=0.9,*/*;q=0.1"
HTML_TYPES = {"text/html", "application/xhtml+xml"}
MAX_CSS_DEPTH = 4
ProgressCallback = Callable[[int, str], None]


class SaveError(Exception):
    pass


class SaveCancelled(SaveError):
    pass


@dataclass
class FetchedResource:
    url: str
    body: bytes
    content_type: str = ""
    charset: str | None = None


class Fetcher(Protocol):
    def get(self, url: str, *, referer: str | None, max_bytes: int, accept: str | None) -> FetchedResource | None: ...


class HttpFetcher:
    """Baixa recursos pela web usando o mesmo cliente HTTP do crawler (timeouts, bloqueio de rede privada)."""

    def __init__(self, settings: Settings):
        self.client = HttpClient(settings)

    def get(self, url, *, referer=None, max_bytes=15_000_000, accept=None):
        res = self.client.fetch(url, max_bytes=max_bytes, accept=accept or "*/*", referer=referer)
        if res.error or not (200 <= res.status < 300) or res.truncated:
            return None
        return FetchedResource(res.url, res.body, res.content_type, res.charset)


class LocalFetcher:
    """Lê arquivos locais, restrito a uma pasta-raiz (nunca sai dela)."""

    def __init__(self, root: Path):
        self.root = root.resolve()

    def get(self, url, *, referer=None, max_bytes=15_000_000, accept=None):
        parts = urlsplit(url)
        if parts.scheme != "file":
            return None
        try:
            path = Path(url2pathname(parts.path)).resolve(strict=True)
            path.relative_to(self.root)
            if not path.is_file() or path.stat().st_size > max_bytes:
                return None
            return FetchedResource(path.as_uri(), path.read_bytes(), guess_mime(path))
        except (OSError, ValueError):
            return None


@dataclass
class SaveReport:
    page_id: str
    url: str
    title: str
    kind: str
    resources: int = 0
    failed: list[str] = field(default_factory=list)
    size_bytes: int = 0
    page: ParsedPage | None = None


@dataclass
class _Ctx:
    root: Path
    base: str
    page_url: str
    assets: dict[str, str | None] = field(default_factory=dict)   # URL absoluta → caminho local (ou None)
    names: set[str] = field(default_factory=set)
    total: int = 0
    failed: list[str] = field(default_factory=list)


# ---------------------------------------------------------------- expressões
_RAW = re.compile(
    r"<!--.*?-->"
    r"|(?P<sopen><script\b[^>]*>)(?P<sbody>.*?)(?P<sclose></script\s*>)"
    r"|(?P<yopen><style\b[^>]*>)(?P<ybody>.*?)(?P<yclose></style\s*>)", re.I | re.S)
_TAG = re.compile(r"<(?P<name>[a-zA-Z][a-zA-Z0-9:-]*)(?P<attrs>(?:\s+[^\s\"'<>/=]+(?:\s*=\s*(?:\"[^\"]*\"|'[^']*'|[^\s\"'=<>`]+))?)*)\s*(?P<end>/?)>")
_ATTR = re.compile(r"""(?P<n>[^\s"'<>/=]+)(?:\s*=\s*(?:"(?P<d>[^"]*)"|'(?P<s>[^']*)'|(?P<u>[^\s"'=<>`]+)))?""")
_CSS_URL = re.compile(r"""url\(\s*(?P<q>["']?)(?P<u>[^"')]*?)(?P=q)\s*\)""", re.I)
_CSS_IMPORT = re.compile(r"""@import\s+(?P<q>["'])(?P<u>[^"']+)(?P=q)""", re.I)
_BASE_HREF = re.compile(r"""<base\b[^>]*?\bhref\s*=\s*(?:"([^"]*)"|'([^']*)')""", re.I)
_HEAD_OPEN = re.compile(r"<head\b[^>]*>", re.I)

_LINK_LOCALIZE_RELS = {"stylesheet", "icon", "shortcut", "apple-touch-icon", "apple-touch-icon-precomposed",
                       "preload", "modulepreload", "mask-icon"}
_DROP_ATTRS = {"integrity", "crossorigin", "nonce"}
_SKIP_SCHEMES = ("data:", "javascript:", "mailto:", "tel:", "about:", "blob:", "#")
_TEXT_ASSET_KINDS = {"css", "js"}


def _classify(url: str, content_type: str) -> str:
    ct = (content_type or "").lower()
    ext = posixpath.splitext(urlsplit(url).path.lower())[1]
    if ct == "text/css" or ext == ".css":
        return "css"
    if "javascript" in ct or "ecmascript" in ct or ext in (".js", ".mjs"):
        return "js"
    if ct.startswith("image/") or ext in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico", ".avif", ".bmp"):
        return "images"
    if ct.startswith("font/") or "font" in ct or ext in (".woff", ".woff2", ".ttf", ".otf", ".eot"):
        return "fonts"
    if ct.startswith(("audio/", "video/")) or ext in (".mp4", ".webm", ".ogg", ".mp3", ".wav", ".m4a", ".vtt"):
        return "media"
    return "other"


def _decode_text(body: bytes, charset: str | None) -> str:
    for enc in ("utf-8-sig", charset or "", "latin-1"):
        if not enc:
            continue
        try:
            return body.decode(enc)
        except (LookupError, UnicodeDecodeError):
            continue
    return body.decode("utf-8", errors="replace")


def _rel(target: str, source_dir: str) -> str:
    return posixpath.relpath(target, source_dir or ".")


class PageSaver:
    def __init__(self, library: SavedPageLibrary, fetcher: Fetcher | None, *, max_resources: int = 300,
                 max_total_bytes: int = 60_000_000, max_file_bytes: int = 15_000_000, max_html_bytes: int = 5_000_000,
                 stop: threading.Event | None = None, on_progress: ProgressCallback | None = None):
        self.library, self.fetcher = library, fetcher
        self.max_resources, self.max_total = max_resources, max_total_bytes
        self.max_file, self.max_html = max_file_bytes, max_html_bytes
        self.stop, self.on_progress = stop, on_progress

    # ------------------------------------------------------------------ API
    def save(self, url: str, *, main: FetchedResource | None = None, kind: str = "full") -> SaveReport:
        url = normalize_url(url) or url
        page_id = page_id_for(url)
        if main is None:
            if self.fetcher is None:
                raise SaveError("sem fonte para baixar a página")
            main = self.fetcher.get(url, referer=None, max_bytes=self.max_html, accept=HTML_ACCEPT)
        if main is None:
            raise SaveError("não foi possível baixar a página")
        if main.content_type.split(";")[0].strip().lower() not in HTML_TYPES | {"text/plain", ""}:
            raise SaveError(f"conteúdo não é HTML ({main.content_type})")
        if len(main.body) > self.max_html:
            raise SaveError("página grande demais para salvar")

        html = decode_html(main.body, main.charset)
        base = main.url
        m = _BASE_HREF.search(html)
        if m:
            base = urljoin(base, m.group(1) or m.group(2) or "")
        tmp = self.library.root / f"{page_id}.tmp"
        shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir(parents=True)
        ctx = _Ctx(root=tmp, base=base, page_url=main.url)
        try:
            localized = self._localize_html(html, ctx, download=self.fetcher is not None and kind != "html_only")
            body = localized.encode("utf-8")
            (tmp / "index.html").write_bytes(body)
            ctx.total += len(body)
            parsed = parse_html(html, main.url)
            parsed.url = url
            (tmp / "manifest.json").write_text(json.dumps({
                "url": url, "final_url": main.url, "title": parsed.title, "saved_at": time.time(), "kind": kind,
                "resources": {v: k for k, v in ctx.assets.items() if v}, "failed": ctx.failed,
            }, indent=2, ensure_ascii=False), encoding="utf-8")
            final = self.library.folder_for(page_id)
            shutil.rmtree(final, ignore_errors=True)
            tmp.rename(final)
        except BaseException:
            shutil.rmtree(tmp, ignore_errors=True)
            raise
        saved = sum(1 for v in ctx.assets.values() if v)
        self.library.register(SavedPage(page_id, url, parsed.title or url, kind, time.time(), saved,
                                        len(ctx.failed), ctx.total))
        return SaveReport(page_id, url, parsed.title or url, kind, saved, list(ctx.failed), ctx.total, parsed)

    # ------------------------------------------------------------- HTML
    def _localize_html(self, html: str, ctx: _Ctx, *, download: bool) -> str:
        out: list[str] = []
        pos = 0
        for m in _RAW.finditer(html):
            out.append(self._tags(html[pos:m.start()], ctx, download))
            if m.group("sopen"):
                out.append(self._tags(m.group("sopen"), ctx, download) + m.group("sbody") + m.group("sclose"))
            elif m.group("yopen"):
                css = self._css(m.group("ybody"), ctx.base, "", ctx, 0, download)
                out.append(m.group("yopen") + css + m.group("yclose"))
            else:
                out.append(m.group(0))       # comentário: intocado
            pos = m.end()
        out.append(self._tags(html[pos:], ctx, download))
        result = "".join(out)
        head = _HEAD_OPEN.search(result)
        meta = '<meta charset="utf-8">'
        return result[:head.end()] + meta + result[head.end():] if head else meta + result

    def _tags(self, text: str, ctx: _Ctx, download: bool) -> str:
        def repl(m: re.Match) -> str:
            name = m.group("name").lower()
            attrs: list[list] = []
            for a in _ATTR.finditer(m.group("attrs")):
                if a.group("d") is not None:
                    attrs.append([a.group("n"), a.group("d"), '"'])
                elif a.group("s") is not None:
                    attrs.append([a.group("n"), a.group("s"), "'"])
                elif a.group("u") is not None:
                    attrs.append([a.group("n"), a.group("u"), '"'])
                else:
                    attrs.append([a.group("n"), None, '"'])
            keep = self._tag(name, attrs, ctx, download)
            if not keep:
                return ""
            parts = [f"<{m.group('name')}"]
            for n, v, q in attrs:
                parts.append(f" {n}" if v is None else f" {n}={q}{v}{q}")
            parts.append(" />" if m.group("end") else ">")
            return "".join(parts)
        return _TAG.sub(repl, text)

    def _tag(self, name: str, attrs: list[list], ctx: _Ctx, download: bool) -> bool:
        """Edita `attrs` no lugar. Devolve False para remover a tag."""
        d = {a[0].lower(): a for a in attrs}
        low = {k: (a[1] or "") for k, a in d.items()}

        def local(attr: str) -> None:
            if attr in d and d[attr][1]:
                d[attr][1] = html_lib.escape(
                    self._ref(html_lib.unescape(d[attr][1]), ctx, "", download, ctx.page_url), quote=True)

        def absolute(attr: str) -> None:
            if attr in d and d[attr][1]:
                v = html_lib.unescape(d[attr][1]).strip()
                if not v.lower().startswith(_SKIP_SCHEMES):
                    d[attr][1] = html_lib.escape(urljoin(ctx.base, v), quote=True)

        if name == "base":
            return False
        if name == "meta":
            equiv = low.get("http-equiv", "").lower()
            if equiv in ("content-security-policy", "content-type") or "charset" in d:
                return False
        if name == "link":
            rels = set(low.get("rel", "").lower().split())
            if rels & _LINK_LOCALIZE_RELS:
                local("href")
            else:
                absolute("href")
        elif name in ("script", "embed", "track", "source", "video", "audio", "img", "input"):
            if name == "input" and low.get("type", "").lower() != "image":
                pass
            else:
                for attr in ("src", "poster", "data-src"):
                    local(attr)
                for attr in ("srcset", "data-srcset"):
                    if attr in d and d[attr][1]:
                        d[attr][1] = self._srcset(html_lib.unescape(d[attr][1]), ctx, download)
        elif name == "object":
            local("data")
        elif name in ("a", "area"):
            absolute("href")
        elif name == "form":
            absolute("action")
        elif name in ("iframe", "frame"):
            absolute("src")
        if "style" in d and d["style"][1] and "url(" in d["style"][1].lower():
            d["style"][1] = html_lib.escape(
                self._css(html_lib.unescape(d["style"][1]), ctx.base, "", ctx, 0, download), quote=True)
        attrs[:] = [a for a in attrs if a[0].lower() not in _DROP_ATTRS]
        return True

    def _srcset(self, value: str, ctx: _Ctx, download: bool) -> str:
        items = []
        for chunk in value.split(","):
            chunk = chunk.strip()
            if not chunk:
                continue
            bits = chunk.split(None, 1)
            url = self._ref(bits[0], ctx, "", download, ctx.page_url)
            items.append(url + (" " + bits[1] if len(bits) > 1 else ""))
        return html_lib.escape(", ".join(items), quote=True)

    # -------------------------------------------------------------- CSS
    def _css(self, text: str, base_url: str, source_dir: str, ctx: _Ctx, depth: int, download: bool) -> str:
        def sub_url(m: re.Match) -> str:
            raw = m.group("u").strip()
            if not raw or raw.lower().startswith(_SKIP_SCHEMES):
                return m.group(0)
            ref = self._ref(raw, ctx, source_dir, download, base_url, depth=depth + 1, rel_base=base_url)
            return f"url({m.group('q')}{ref}{m.group('q')})"

        def sub_import(m: re.Match) -> str:
            raw = m.group("u").strip()
            ref = self._ref(raw, ctx, source_dir, download, base_url, depth=depth + 1, rel_base=base_url)
            return f"@import {m.group('q')}{ref}{m.group('q')}"

        return _CSS_URL.sub(sub_url, _CSS_IMPORT.sub(sub_import, text))

    # ----------------------------------------------------- recursos / arquivos
    def _ref(self, raw: str, ctx: _Ctx, source_dir: str, download: bool, referer: str,
             depth: int = 0, rel_base: str | None = None) -> str:
        """Devolve a referência a gravar no arquivo: caminho local relativo (se salvou) ou URL absoluta."""
        raw = raw.strip()
        if not raw or raw.lower().startswith(_SKIP_SCHEMES):
            return raw
        absolute = urljoin(rel_base or ctx.base, raw)
        parts = urlsplit(absolute)
        if parts.scheme not in ("http", "https", "file"):
            return raw
        key = absolute.split("#", 1)[0]
        fragment = ("#" + absolute.split("#", 1)[1]) if "#" in absolute else ""
        if key in ctx.assets:
            local = ctx.assets[key]
            return (_rel(local, source_dir) + fragment) if local else self._fallback(absolute)
        if not download or depth > MAX_CSS_DEPTH:
            return self._fallback(absolute)
        local = self._download(key, ctx, referer, depth)
        return (_rel(local, source_dir) + fragment) if local else self._fallback(absolute)

    @staticmethod
    def _fallback(absolute: str) -> str:
        """Recurso não salvo: mantém a URL original (será bloqueada offline). file:// nunca é mantido."""
        return "about:blank" if absolute.startswith("file:") else absolute

    def _download(self, url: str, ctx: _Ctx, referer: str, depth: int) -> str | None:
        if self.stop is not None and self.stop.is_set():
            raise SaveCancelled("salvamento cancelado")
        if len([v for v in ctx.assets.values() if v]) >= self.max_resources or ctx.total >= self.max_total:
            ctx.assets[url] = None
            ctx.failed.append(url)
            return None
        res = self.fetcher.get(url, referer=referer, max_bytes=self.max_file, accept="*/*") if self.fetcher else None
        if res is None:
            ctx.assets[url] = None
            ctx.failed.append(url)
            return None
        kind = _classify(res.url, res.content_type)
        local = f"{kind}/{self._name(url, res, kind, ctx)}"
        ctx.assets[url] = local                      # reserva antes de recursar (evita ciclos)
        body = res.body
        if kind == "css":
            text = self._css(_decode_text(body, res.charset), res.url, posixpath.dirname(local), ctx, depth, True)
            body = text.encode("utf-8")
        elif kind == "js" and res.charset and res.charset.lower() not in ("utf-8", "utf8"):
            body = _decode_text(body, res.charset).encode("utf-8")
        target = ctx.root / local
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)
        ctx.total += len(body)
        if self.on_progress:
            self.on_progress(len([v for v in ctx.assets.values() if v]), url)
        return local

    @staticmethod
    def _name(url: str, res: FetchedResource, kind: str, ctx: _Ctx) -> str:
        base = re.sub(r"[#%\s]+", "_", safe_filename(unquote(posixpath.basename(urlsplit(res.url).path)) or "recurso",
                                                      "recurso"))
        stem, ext = posixpath.splitext(base)
        if not ext:
            guess = mimetypes.guess_extension((res.content_type or "").split(";")[0].strip()) or ""
            ext = {".jpe": ".jpg"}.get(guess, guess) or {"css": ".css", "js": ".js"}.get(kind, "")
        name = stem + ext
        if f"{kind}/{name}" in ctx.names:
            name = f"{stem}-{hashlib.sha1(url.encode()).hexdigest()[:8]}{ext}"
        ctx.names.add(f"{kind}/{name}")
        return name


# ------------------------------------------------------------ arquivos locais
def text_to_html(text: str, title: str) -> bytes:
    safe = html_lib.escape(text)
    return (f'<!doctype html><html><head><meta charset="utf-8"><title>{html_lib.escape(title)}</title></head>'
            f'<body><pre style="white-space:pre-wrap;font:15px/1.6 monospace;max-width:90ch;margin:2rem auto;'
            f'padding:0 1rem">{safe}</pre></body></html>').encode("utf-8")
