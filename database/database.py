"""Implementação local (SQLite) do IndexStore + cache de páginas + histórico.

Tabelas:
    documents   – uma linha por página (título, texto, domínio, hash...)
    postings    – índice invertido: (termo, doc) → frequências por campo
    links       – grafo de links entre páginas indexadas (sinal de popularidade)
    page_cache  – HTML original comprimido (usado no modo offline)
    history     – histórico LOCAL de buscas (só é gravado se o usuário ativar)
"""
from __future__ import annotations

import sqlite3
import threading
import time
import zlib
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from core.models import DocMeta, DocStats, Document, Posting

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT NOT NULL UNIQUE,
    domain TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    headings TEXT NOT NULL DEFAULT '',
    body TEXT NOT NULL DEFAULT '',
    lang TEXT NOT NULL DEFAULT '',
    content_hash TEXT NOT NULL DEFAULT '',
    length INTEGER NOT NULL DEFAULT 0,
    source TEXT NOT NULL DEFAULT 'web',
    favorite INTEGER NOT NULL DEFAULT 0,
    fetched_at REAL NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_documents_hash ON documents(content_hash);
CREATE INDEX IF NOT EXISTS idx_documents_domain ON documents(domain);
CREATE TABLE IF NOT EXISTS postings(
    term TEXT NOT NULL,
    doc_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    tf_body INTEGER NOT NULL DEFAULT 0,
    tf_title INTEGER NOT NULL DEFAULT 0,
    tf_headings INTEGER NOT NULL DEFAULT 0,
    tf_url INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(term, doc_id)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS idx_postings_doc ON postings(doc_id);
CREATE TABLE IF NOT EXISTS links(
    src_url TEXT NOT NULL,
    dst_url TEXT NOT NULL,
    PRIMARY KEY(src_url, dst_url)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS idx_links_dst ON links(dst_url);
CREATE TABLE IF NOT EXISTS page_cache(
    url TEXT PRIMARY KEY,
    html BLOB NOT NULL,
    content_type TEXT NOT NULL DEFAULT '',
    fetched_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS browse_history(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    ts REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS history(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    query TEXT NOT NULL,
    ts REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS saved_pages(
    page_id TEXT PRIMARY KEY,
    url TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL DEFAULT 'full',
    saved_at REAL NOT NULL,
    resources INTEGER NOT NULL DEFAULT 0,
    failed INTEGER NOT NULL DEFAULT 0,
    size_bytes INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS browse_history(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    ts REAL NOT NULL
);
"""

_DOC_COLS = "id, url, domain, title, description, headings, body, lang, source, favorite, fetched_at, length"


def _chunks(seq: list, n: int) -> Iterator[list]:
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def _row_to_document(r: tuple) -> Document:
    return Document(doc_id=r[0], url=r[1], domain=r[2], title=r[3], description=r[4], headings=r[5],
                    body=r[6], lang=r[7], source=r[8], favorite=bool(r[9]), fetched_at=r[10], length=r[11])


class Database:
    def __init__(self, path: Path | str):
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self._conn.execute("PRAGMA foreign_keys=ON")
        try:
            self._conn.execute("PRAGMA journal_mode=WAL")
        except sqlite3.DatabaseError:
            pass
        self._conn.executescript(SCHEMA)
        self.version = 0
        self._corpus: tuple[int, int, float] | None = None
        self.path = str(path)

    # ------------------------------------------------------------------ infra
    @contextmanager
    def _tx(self):
        with self._lock:
            self._conn.execute("BEGIN")
            try:
                yield self._conn
                self._conn.execute("COMMIT")
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise

    def _query(self, sql: str, params: tuple | list = ()) -> list[tuple]:
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ---------------------------------------------------------------- escrita
    def upsert_document(self, doc: dict, postings: dict[str, tuple[int, int, int, int]], links: list[str]) -> int:
        url = doc["url"]
        with self._tx() as c:
            row = c.execute("SELECT id FROM documents WHERE url=?", (url,)).fetchone()
            values = (doc["domain"], doc["title"], doc["description"], doc["headings"], doc["body"],
                      doc["lang"], doc["content_hash"], doc["length"], doc["source"], doc["fetched_at"])
            if row:
                doc_id = row[0]
                c.execute("DELETE FROM postings WHERE doc_id=?", (doc_id,))
                c.execute("UPDATE documents SET domain=?, title=?, description=?, headings=?, body=?, lang=?,"
                          " content_hash=?, length=?, source=?, fetched_at=? WHERE id=?", values + (doc_id,))
            else:
                cur = c.execute("INSERT INTO documents(domain, title, description, headings, body, lang,"
                                " content_hash, length, source, fetched_at, url) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                                values + (url,))
                doc_id = cur.lastrowid
            c.executemany("INSERT INTO postings(term, doc_id, tf_body, tf_title, tf_headings, tf_url)"
                          " VALUES (?,?,?,?,?,?)", [(t, doc_id, *tf) for t, tf in postings.items()])
            c.execute("DELETE FROM links WHERE src_url=?", (url,))
            c.executemany("INSERT OR IGNORE INTO links(src_url, dst_url) VALUES (?,?)",
                          [(url, link) for link in links[:300]])
        self._bump()
        return doc_id

    def touch(self, url: str, fetched_at: float) -> None:
        with self._tx() as c:
            c.execute("UPDATE documents SET fetched_at=? WHERE url=?", (fetched_at, url))

    def delete_by_url(self, url: str) -> bool:
        with self._tx() as c:
            n = c.execute("DELETE FROM documents WHERE url=?", (url,)).rowcount
            c.execute("DELETE FROM links WHERE src_url=?", (url,))
        if n:
            self._bump()
        return bool(n)

    def set_favorite(self, url: str, favorite: bool) -> bool:
        with self._tx() as c:
            n = c.execute("UPDATE documents SET favorite=? WHERE url=?", (int(favorite), url)).rowcount
        if n:
            self._bump()
        return bool(n)

    def _bump(self) -> None:
        self.version += 1
        self._corpus = None

    # ------------------------------------------------------------------ busca
    def corpus_stats(self) -> tuple[int, float]:
        if self._corpus is None or self._corpus[0] != self.version:
            r = self._query("SELECT COUNT(*), COALESCE(AVG(length), 0) FROM documents")[0]
            self._corpus = (self.version, r[0], float(r[1]))
        return self._corpus[1], self._corpus[2]

    def get_postings(self, terms: list[str]) -> dict[str, dict[int, Posting]]:
        out: dict[str, dict[int, Posting]] = {t: {} for t in terms}
        for part in _chunks(list(terms), 400):
            marks = ",".join("?" * len(part))
            for term, doc_id, b, t, h, u in self._query(
                    f"SELECT term, doc_id, tf_body, tf_title, tf_headings, tf_url FROM postings WHERE term IN ({marks})",
                    part):
                out[term][doc_id] = Posting(b, t, h, u)
        return out

    def get_doc_stats(self, ids: list[int]) -> dict[int, DocStats]:
        out: dict[int, DocStats] = {}
        for part in _chunks(list(ids), 500):
            marks = ",".join("?" * len(part))
            rows = self._query(
                "SELECT d.id, d.length, d.source, d.favorite, d.domain,"
                " (SELECT COUNT(DISTINCT l.src_url) FROM links l WHERE l.dst_url = d.url AND l.src_url != d.url)"
                f" FROM documents d WHERE d.id IN ({marks})", part)
            for r in rows:
                out[r[0]] = DocStats(r[0], r[1], r[2], bool(r[3]), r[5], r[4])
        return out

    def get_documents(self, ids: list[int]) -> dict[int, Document]:
        out: dict[int, Document] = {}
        for part in _chunks(list(ids), 500):
            marks = ",".join("?" * len(part))
            for r in self._query(f"SELECT {_DOC_COLS} FROM documents WHERE id IN ({marks})", part):
                out[r[0]] = _row_to_document(r)
        return out

    def iter_documents(self, ids: list[int], chunk: int = 50) -> Iterator[Document]:
        for part in _chunks(list(ids), chunk):
            yield from self.get_documents(part).values()

    def get_meta_by_url(self, url: str) -> DocMeta | None:
        rows = self._query("SELECT id, url, content_hash, fetched_at FROM documents WHERE url=?", (url,))
        return DocMeta(*rows[0]) if rows else None

    def find_by_hash(self, content_hash: str) -> DocMeta | None:
        rows = self._query("SELECT id, url, content_hash, fetched_at FROM documents WHERE content_hash=? LIMIT 1",
                           (content_hash,))
        return DocMeta(*rows[0]) if rows else None

    def list_documents(self, source: str | None = None, limit: int = 200) -> list[Document]:
        if source:
            rows = self._query(f"SELECT {_DOC_COLS} FROM documents WHERE source=? ORDER BY fetched_at DESC LIMIT ?",
                               (source, limit))
        else:
            rows = self._query(f"SELECT {_DOC_COLS} FROM documents ORDER BY fetched_at DESC LIMIT ?", (limit,))
        return [_row_to_document(r) for r in rows]

    # ------------------------------------------------------------------ cache
    def cache_put(self, url: str, html: bytes, content_type: str = "", fetched_at: float | None = None) -> None:
        with self._tx() as c:
            c.execute("INSERT OR REPLACE INTO page_cache(url, html, content_type, fetched_at) VALUES (?,?,?,?)",
                      (url, zlib.compress(html, 6), content_type, fetched_at or time.time()))

    def cache_get(self, url: str) -> bytes | None:
        rows = self._query("SELECT html FROM page_cache WHERE url=?", (url,))
        return zlib.decompress(rows[0][0]) if rows else None

    def cache_has(self, url: str) -> bool:
        return bool(self._query("SELECT 1 FROM page_cache WHERE url=?", (url,)))

    # -------------------------------------------------------------- histórico
    def add_history(self, query: str) -> None:
        with self._tx() as c:
            c.execute("INSERT INTO history(query, ts) VALUES (?,?)", (query, time.time()))

    def list_history(self, limit: int = 50) -> list[tuple[str, float]]:
        return [(q, ts) for q, ts in self._query("SELECT query, ts FROM history ORDER BY id DESC LIMIT ?", (limit,))]

    def clear_history(self) -> None:
        with self._tx() as c:
            c.execute("DELETE FROM history")

    # --------------------------------------------------- histórico de navegação
    def add_browse_history(self, url: str, title: str = "") -> None:
        with self._tx() as c:
            last = c.execute("SELECT url FROM browse_history ORDER BY id DESC LIMIT 1").fetchone()
            if not last or last[0] != url:
                c.execute("INSERT INTO browse_history(url, title, ts) VALUES (?,?,?)", (url, title, time.time()))

    def list_browse_history(self, limit: int = 200) -> list[tuple[str, str, float]]:
        return self._query("SELECT url, title, ts FROM browse_history ORDER BY id DESC LIMIT ?", (limit,))

    def clear_browse_history(self) -> None:
        with self._tx() as c:
            c.execute("DELETE FROM browse_history")

    # ------------------------------------------------- páginas salvas / navegação
    def saved_page_put(self, row: dict) -> None:
        with self._tx() as c:
            c.execute("DELETE FROM saved_pages WHERE url=? OR page_id=?", (row["url"], row["page_id"]))
            c.execute("INSERT INTO saved_pages(page_id, url, title, kind, saved_at, resources, failed, size_bytes)"
                      " VALUES (:page_id, :url, :title, :kind, :saved_at, :resources, :failed, :size_bytes)", row)

    _SP_COLS = "page_id, url, title, kind, saved_at, resources, failed, size_bytes"

    def saved_page_get(self, *, url: str | None = None, page_id: str | None = None) -> tuple | None:
        if url is not None:
            rows = self._query(f"SELECT {self._SP_COLS} FROM saved_pages WHERE url=?", (url,))
        else:
            rows = self._query(f"SELECT {self._SP_COLS} FROM saved_pages WHERE page_id=?", (page_id,))
        return rows[0] if rows else None

    def saved_pages_list(self) -> list[tuple]:
        return self._query(f"SELECT {self._SP_COLS} FROM saved_pages ORDER BY saved_at DESC")

    def saved_page_delete(self, page_id: str) -> None:
        with self._tx() as c:
            c.execute("DELETE FROM saved_pages WHERE page_id=?", (page_id,))

    def saved_pages_clear(self) -> None:
        with self._tx() as c:
            c.execute("DELETE FROM saved_pages")

    def add_visit(self, url: str, title: str = "") -> None:
        with self._tx() as c:
            c.execute("INSERT INTO browse_history(url, title, ts) VALUES (?,?,?)", (url, title, time.time()))

    def list_visits(self, limit: int = 30) -> list[tuple[str, str, float]]:
        return self._query("SELECT url, title, ts FROM browse_history ORDER BY id DESC LIMIT ?", (limit,))

    def clear_visits(self) -> None:
        with self._tx() as c:
            c.execute("DELETE FROM browse_history")

    # -------------------------------------------------------------- manutenção
    def clear_cache(self) -> None:
        with self._tx() as c:
            c.execute("DELETE FROM page_cache")
        self._vacuum()

    def clear_index(self) -> None:
        with self._tx() as c:
            c.execute("DELETE FROM postings")
            c.execute("DELETE FROM links")
            c.execute("DELETE FROM documents")
        self._bump()
        self._vacuum()

    def clear_all(self) -> None:
        self.clear_visits()
        self.saved_pages_clear()
        self.clear_history()
        self.clear_browse_history()
        self.clear_index()
        self.clear_cache()

    def _vacuum(self) -> None:
        with self._lock:
            try:
                self._conn.execute("VACUUM")
            except sqlite3.OperationalError:
                pass

    def stats(self) -> dict:
        q = self._query
        by_source = dict(q("SELECT source, COUNT(*) FROM documents GROUP BY source"))
        try:
            size = Path(self.path).stat().st_size
        except OSError:
            size = 0
        return {
            "documents": sum(by_source.values()),
            "by_source": by_source,
            "terms": q("SELECT COUNT(*) FROM (SELECT DISTINCT term FROM postings)")[0][0],
            "cached_pages": q("SELECT COUNT(*) FROM page_cache")[0][0],
            "history": q("SELECT COUNT(*) FROM history")[0][0],
            "saved_pages": q("SELECT COUNT(*) FROM saved_pages")[0][0],
            "saved_bytes": q("SELECT COALESCE(SUM(size_bytes), 0) FROM saved_pages")[0][0],
            "visits": q("SELECT COUNT(*) FROM browse_history")[0][0],
            "browse_history": q("SELECT COUNT(*) FROM browse_history")[0][0],
            "db_bytes": size,
        }
