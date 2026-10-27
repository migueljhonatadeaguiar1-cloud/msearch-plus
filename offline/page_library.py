"""Biblioteca de páginas salvas para uso offline.

Cada página fica em   conteudo_offline/<page_id>/   (index.html + css/ js/ images/ fonts/ media/ other/)
e é exibida pelo navegador interno através do esquema próprio  searchplus-offline://<page_id>/...
O resolvedor abaixo só entrega arquivos DENTRO da pasta daquela página (sem path traversal, sem symlinks
para fora), de modo que o conteúdo salvo nunca enxerga o resto do disco do usuário.
"""
from __future__ import annotations

import hashlib
import mimetypes
import re
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote

from config.settings import AppPaths
from database.database import Database

SCHEME = "searchplus-offline"
_ID_RE = re.compile(r"^p[0-9a-f]{12}$")

_MIME_OVERRIDES = {
    ".html": "text/html", ".htm": "text/html", ".xhtml": "application/xhtml+xml", ".css": "text/css",
    ".js": "text/javascript", ".mjs": "text/javascript", ".json": "application/json", ".svg": "image/svg+xml",
    ".woff": "font/woff", ".woff2": "font/woff2", ".ttf": "font/ttf", ".otf": "font/otf",
    ".eot": "application/vnd.ms-fontobject", ".webp": "image/webp", ".avif": "image/avif", ".ico": "image/x-icon",
    ".wasm": "application/wasm", ".mp4": "video/mp4", ".webm": "video/webm", ".mp3": "audio/mpeg",
    ".ogg": "audio/ogg", ".txt": "text/plain", ".map": "application/json",
}


def guess_mime(path: str | Path) -> str:
    ext = Path(str(path)).suffix.lower()
    return _MIME_OVERRIDES.get(ext) or mimetypes.guess_type(str(path))[0] or "application/octet-stream"


def page_id_for(url: str) -> str:
    return "p" + hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]


@dataclass
class SavedPage:
    page_id: str
    url: str
    title: str
    kind: str             # full | html_only | local
    saved_at: float
    resources: int = 0
    failed: int = 0
    size_bytes: int = 0


def _row(r: tuple) -> SavedPage:
    return SavedPage(page_id=r[0], url=r[1], title=r[2], kind=r[3], saved_at=r[4], resources=r[5],
                     failed=r[6], size_bytes=r[7])


class SavedPageLibrary:
    def __init__(self, db: Database, paths: AppPaths):
        self.db, self.paths = db, paths

    @property
    def root(self) -> Path:
        self.paths.saved_pages_dir.mkdir(parents=True, exist_ok=True)
        return self.paths.saved_pages_dir

    # ------------------------------------------------------------------ URLs
    @staticmethod
    def offline_url(page_id: str, rel: str = "index.html") -> str:
        return f"{SCHEME}://{page_id}/{rel}"

    def folder_for(self, page_id: str) -> Path:
        return self.root / page_id

    # --------------------------------------------------------------- consulta
    def find_by_url(self, url: str) -> SavedPage | None:
        r = self.db.saved_page_get(url=url)
        if r and (self.folder_for(r[0]) / "index.html").is_file():
            return _row(r)
        return None

    def find_by_id(self, page_id: str) -> SavedPage | None:
        r = self.db.saved_page_get(page_id=page_id) if _ID_RE.match(page_id or "") else None
        return _row(r) if r else None

    def list_pages(self) -> list[SavedPage]:
        return [_row(r) for r in self.db.saved_pages_list()]

    # ------------------------------------------------------------ resolução
    def resolve_file(self, page_id: str, rel_path: str) -> Path | None:
        """Caminho seguro de um arquivo da página, ou None. Nunca sai da pasta da página."""
        if not _ID_RE.match(page_id or ""):
            return None
        folder = self.folder_for(page_id)
        rel = unquote(rel_path or "").lstrip("/")
        if "\x00" in rel:
            return None
        if rel == "" or rel.endswith("/"):
            rel += "index.html"
        try:
            base = folder.resolve(strict=True)
            target = (base / rel).resolve(strict=True)
            target.relative_to(base)
        except (OSError, ValueError):
            return None
        return target if target.is_file() else None

    # --------------------------------------------------------------- escrita
    def register(self, page: SavedPage) -> None:
        self.db.saved_page_put({
            "page_id": page.page_id, "url": page.url, "title": page.title, "kind": page.kind,
            "saved_at": page.saved_at or time.time(), "resources": page.resources, "failed": page.failed,
            "size_bytes": page.size_bytes})

    def delete(self, page_id: str) -> None:
        if _ID_RE.match(page_id or ""):
            shutil.rmtree(self.folder_for(page_id), ignore_errors=True)
            self.db.saved_page_delete(page_id)

    def clear(self) -> None:
        shutil.rmtree(self.paths.saved_pages_dir, ignore_errors=True)
        self.paths.saved_pages_dir.mkdir(parents=True, exist_ok=True)
        self.db.saved_pages_clear()
