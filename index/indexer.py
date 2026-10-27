"""Indexador: transforma uma ParsedPage em documento + postings e grava no IndexStore."""
from __future__ import annotations

import hashlib
import re
import time
from collections import Counter
from dataclasses import dataclass
from urllib.parse import unquote, urlsplit

from core.models import ParsedPage
from database.interfaces import IndexStore
from index.tokenizer import Tokenizer

MAX_BODY_CHARS = 100_000
_WS = re.compile(r"\s+")


@dataclass
class IndexOutcome:
    status: str                     # indexed | updated | unchanged | duplicate | noindex | empty
    doc_id: int | None = None
    duplicate_of: str | None = None


class Indexer:
    def __init__(self, store: IndexStore, tokenizer: Tokenizer | None = None):
        self.store = store
        self.tok = tokenizer or Tokenizer()

    def add_page(self, page: ParsedPage, *, source: str = "web", fetched_at: float | None = None) -> IndexOutcome:
        fetched_at = fetched_at or time.time()
        if page.noindex:
            return IndexOutcome("noindex")

        parts = urlsplit(page.url)
        domain = (parts.hostname or "local").lower()
        domain = domain[4:] if domain.startswith("www.") else domain
        url_text = f"{domain} {unquote(parts.path)}"

        title = _WS.sub(" ", page.title).strip()
        headings = _WS.sub(" ", " ".join(page.headings + ([page.keywords] if page.keywords else []))).strip()
        body = _WS.sub(" ", f"{page.description} {page.text}").strip()[:MAX_BODY_CHARS]

        tok = self.tok
        t_title, t_head, t_url, t_body = (tok.tokenize(title), tok.tokenize(headings),
                                          tok.tokenize(url_text), tok.tokenize(body))
        if not (t_title or t_body):
            return IndexOutcome("empty")

        content_hash = hashlib.sha1(" ".join(t_title + t_body[:2000]).encode("utf-8")).hexdigest()
        existing = self.store.get_meta_by_url(page.url)
        if existing and existing.content_hash == content_hash:
            self.store.touch(page.url, fetched_at)
            return IndexOutcome("unchanged", existing.doc_id)
        dup = self.store.find_by_hash(content_hash)
        if dup and dup.url != page.url:
            return IndexOutcome("duplicate", None, dup.url)

        c_body, c_title, c_head, c_url = Counter(t_body), Counter(t_title), Counter(t_head), Counter(t_url)
        postings = {t: (c_body[t], c_title[t], c_head[t], c_url[t])
                    for t in set(c_body) | set(c_title) | set(c_head) | set(c_url)}
        doc = {
            "url": page.url, "domain": domain,
            "title": title or (page.headings[0] if page.headings else page.url),
            "description": page.description.strip(), "headings": headings, "body": body,
            "lang": page.lang, "content_hash": content_hash, "length": len(t_body),
            "source": source, "fetched_at": fetched_at,
        }
        doc_id = self.store.upsert_document(doc, postings, page.links)
        return IndexOutcome("updated" if existing else "indexed", doc_id)

    def remove(self, url: str) -> bool:
        return self.store.delete_by_url(url)
