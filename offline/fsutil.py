"""Utilitários de sistema de arquivos compartilhados (sem Qt): nomes seguros e extensões perigosas."""
from __future__ import annotations

import re
from pathlib import Path

_BAD_CHARS = re.compile(r'[\x00-\x1f<>:"|?*\\/]')
_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}
DANGEROUS_EXTENSIONS = {
    ".exe", ".msi", ".bat", ".cmd", ".com", ".scr", ".pif", ".lnk", ".ps1", ".psm1", ".vbs", ".vbe", ".js",
    ".jse", ".wsf", ".wsh", ".hta", ".jar", ".apk", ".dmg", ".pkg", ".sh", ".run", ".bin", ".reg", ".dll",
    ".cpl", ".appimage", ".deb", ".rpm",
}


def safe_filename(name: str, default: str = "arquivo", max_len: int = 150) -> str:
    """Remove caminhos, caracteres de controle/ilegais e nomes reservados do Windows."""
    name = name.replace("\\", "/").split("/")[-1]
    name = _BAD_CHARS.sub("_", name).strip(" .")
    if not name:
        return default
    stem, dot, ext = name.rpartition(".")
    if not dot:
        stem, ext = name, ""
    if stem.lower() in _RESERVED:
        name = "_" + name
    if len(name) > max_len:
        keep = max_len - len(ext) - 1 if ext else max_len
        name = name[:keep] + ("." + ext if ext else "")
    return name


def unique_path(directory: Path, name: str) -> Path:
    candidate = directory / name
    if not candidate.exists():
        return candidate
    stem, suffix = Path(name).stem, Path(name).suffix
    for i in range(1, 10_000):
        candidate = directory / f"{stem} ({i}){suffix}"
        if not candidate.exists():
            return candidate
    raise OSError("não foi possível gerar um nome único")


def is_dangerous_filename(name: str) -> bool:
    lower = name.lower().rstrip(". ")
    return Path(lower).suffix in DANGEROUS_EXTENSIONS
