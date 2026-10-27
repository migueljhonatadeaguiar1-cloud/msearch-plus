"""Análise de HTML (stdlib): título, texto, links, cabeçalhos e metadados."""
from __future__ import annotations

import re
from html.parser import HTMLParser
from urllib.parse import urljoin

from core.models import ParsedPage

_SKIP = {"script", "style", "noscript", "template", "svg", "iframe", "nav", "footer", "head_noise"}
_HEADINGS = {"h1", "h2", "h3", "h4"}
_BLOCK = {"p", "div", "br", "li", "ul", "ol", "tr", "td", "th", "table", "section", "article", "main",
          "header", "h1", "h2", "h3", "h4", "h5", "h6", "pre", "blockquote", "dd", "dt"}
_WS = re.compile(r"\s+")
MAX_TEXT_CHARS = 200_000
MAX_LINKS = 500


def decode_html(body: bytes, header_charset: str | None = None) -> str:
    candidates = []
    if header_charset:
        candidates.append(header_charset)
    m = re.search(rb"""charset\s*=\s*["']?([\w\-]+)""", body[:4096], re.I)
    if m:
        candidates.append(m.group(1).decode("ascii", "ignore"))
    candidates.append("utf-8")
    for enc in candidates:
        try:
            return body.decode(enc)
        except (LookupError, UnicodeDecodeError):
            continue
    return body.decode("latin-1", errors="replace")


class _Extractor(HTMLParser):
    def __init__(self, base: str):
        super().__init__(convert_charrefs=True)
        self.base = base
        self.title_parts: list[str] = []
        self.in_title = False
        self.title_done = False
        self.skip_depth = 0
        self.text: list[str] = []
        self.headings: list[str] = []
        self.heading_tag: str | None = None
        self.heading_parts: list[str] = []
        self.links: list[str] = []
        self.meta: dict[str, str] = {}
        self.lang = ""
        self.canonical = ""
        self.noindex = False
        self.nofollow = False

    def _join(self, href: str) -> str | None:
        try:
            return urljoin(self.base, href.strip())
        except ValueError:
            return None

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "html":
            self.lang = a.get("lang", "")
        elif tag == "title" and not self.title_done:
            self.in_title = True
        elif tag == "base" and a.get("href"):
            self.base = self._join(a["href"]) or self.base
        elif tag == "meta":
            self._meta(a)
        elif tag == "link" and "canonical" in a.get("rel", "").lower().split() and a.get("href"):
            self.canonical = self._join(a["href"]) or ""
        elif tag == "a" and a.get("href") and "nofollow" not in a.get("rel", "").lower():
            link = self._join(a["href"])
            if link:
                self.links.append(link)
        if tag in _SKIP:
            self.skip_depth += 1
        elif tag in _HEADINGS and not self.skip_depth:
            self.heading_tag, self.heading_parts = tag, []
        if tag in _BLOCK:
            self.text.append(" ")

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title, self.title_done = False, True
        if tag in _SKIP:
            self.skip_depth = max(0, self.skip_depth - 1)
        if tag == self.heading_tag:
            h = _WS.sub(" ", " ".join(self.heading_parts)).strip()
            if h:
                self.headings.append(h)
            self.heading_tag = None
        if tag in _BLOCK:
            self.text.append(" ")

    def handle_data(self, data):
        if self.in_title:
            self.title_parts.append(data)
            return
        if self.skip_depth:
            return
        self.text.append(data)
        if self.heading_tag:
            self.heading_parts.append(data)

    def _meta(self, a: dict[str, str]) -> None:
        name = (a.get("name") or a.get("property") or "").lower()
        content = a.get("content", "")
        if name in ("description", "og:description", "twitter:description"):
            self.meta.setdefault("description", content)
        elif name == "keywords":
            self.meta["keywords"] = content
        elif name in ("robots", "googlebot"):
            low = content.lower()
            self.noindex = self.noindex or "noindex" in low or "none" in low.split(",")
            self.nofollow = self.nofollow or "nofollow" in low or "none" in low.split(",")


def parse_html(html: str, url: str) -> ParsedPage:
    ex = _Extractor(url)
    try:
        ex.feed(html)
        ex.close()
    except Exception:  # HTML quebrado: aproveita o que já foi extraído
        pass
    return ParsedPage(
        url=url,
        title=_WS.sub(" ", " ".join(ex.title_parts)).strip(),
        description=_WS.sub(" ", ex.meta.get("description", "")).strip(),
        keywords=_WS.sub(" ", ex.meta.get("keywords", "")).strip(),
        lang=ex.lang.strip().lower(),
        canonical=ex.canonical,
        headings=list(dict.fromkeys(ex.headings))[:50],
        text=_WS.sub(" ", " ".join(ex.text)).strip()[:MAX_TEXT_CHARS],
        links=list(dict.fromkeys(ex.links))[:MAX_LINKS],
        noindex=ex.noindex,
        nofollow=ex.nofollow,
    )


def parse_plain_text(text: str, url: str, title: str = "") -> ParsedPage:
    return ParsedPage(url=url, title=title, text=_WS.sub(" ", text).strip()[:MAX_TEXT_CHARS])
