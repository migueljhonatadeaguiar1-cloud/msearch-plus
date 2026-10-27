"""Interpretação da barra de endereço (sem Qt, testável).

    texto digitado → URL (https:// adicionado quando apropriado) | pesquisa | arquivo local | inválido
Esquemas perigosos (javascript:, data:, vbscript:, ftp:, blob:, chrome: ...) NUNCA viram navegação.
"""
from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlsplit

_HOST = re.compile(r"^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+(?:[a-z]{2,63}|xn--[a-z0-9-]{2,59})$", re.I)
_SCHEME = re.compile(r"^([a-zA-Z][a-zA-Z0-9+.\-]*):")
_BLOCKED = {"javascript", "data", "vbscript", "view-source", "blob", "ftp", "mailto", "tel", "chrome",
            "chrome-error", "qrc", "filesystem", "ws", "wss", "searchplus-offline", "about"}
_WIN_PATH = re.compile(r"^[A-Za-z]:[\\/]")
_HOSTPORT = re.compile(r"^(\[[0-9a-fA-F:.]+\]|[^/:?#\s]+)(:\d{1,5})?([/?#].*)?$")


@dataclass(frozen=True)
class Resolved:
    kind: str          # url | search | local_file | blank | invalid
    value: str = ""
    message: str = ""


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host.strip("[]"))
        return True
    except ValueError:
        return False


def file_url_to_path(url: str) -> str:
    path = unquote(urlsplit(url).path)
    if re.match(r"^/[A-Za-z]:/", path):
        path = path[1:]
    return path


def resolve_input(text: str) -> Resolved:
    t = (text or "").strip()
    if not t or t.lower() == "about:blank":
        return Resolved("blank")

    if t.startswith(("/", "~")) or _WIN_PATH.match(t):
        p = Path(t).expanduser()
        if p.is_file():
            return Resolved("local_file", str(p.resolve()))
        if t.startswith("~") or _WIN_PATH.match(t):
            return Resolved("invalid", message="Arquivo não encontrado.")

    m = _SCHEME.match(t)
    if m and t[m.end():].startswith("//") or (m and m.group(1).lower() in _BLOCKED and not t[m.end():][:1].isdigit()):
        scheme = m.group(1).lower()
        if scheme in ("http", "https"):
            parts = urlsplit(t)
            host = parts.hostname or ""
            if (" " in t) or not host or not (_HOST.match(host) or host == "localhost" or _is_ip(host)):
                return Resolved("invalid", message="Endereço inválido.")
            try:
                parts.port
            except ValueError:
                return Resolved("invalid", message="Porta inválida.")
            return Resolved("url", t)
        if scheme == "file":
            path = file_url_to_path(t)
            return Resolved("local_file", path) if Path(path).is_file() else Resolved(
                "invalid", message="Arquivo não encontrado.")
        return Resolved("invalid", message=f"O esquema “{scheme}:” não é permitido por segurança.")

    if " " in t or "\t" in t:
        return Resolved("search", t)

    hp = _HOSTPORT.match(t)
    if hp:
        host = hp.group(1)
        if host.lower() == "localhost" or _is_ip(host):
            return Resolved("url", "http://" + t)
        if _HOST.match(host):
            return Resolved("url", "https://" + t)
    return Resolved("search", t)


def security_state(url: str) -> str:
    scheme = urlsplit(url).scheme.lower()
    return {"https": "secure", "http": "insecure", "searchplus-offline": "offline"}.get(scheme, "none")
