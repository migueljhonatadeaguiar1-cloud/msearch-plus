"""Processamento da consulta.

Sintaxe suportada:
    python tutorial        → todos os termos (com preferência por quem tem todos)
    "teorema de pitágoras" → frase exata (filtra)
    -java                  → exclui documentos com o termo
    site:exemplo.com       → restringe ao domínio
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from index.tokenizer import Tokenizer

_PIECES = re.compile(r'-?"[^"]*"|\S+')


@dataclass
class Query:
    raw: str
    terms: list[str] = field(default_factory=list)        # termos normalizados (stem), sem repetição
    phrases: list[str] = field(default_factory=list)      # frases exatas normalizadas (filtro)
    excluded: list[str] = field(default_factory=list)
    site: str | None = None
    soft_phrase: str = ""                                 # consulta inteira, para bônus (não filtra)

    @property
    def is_empty(self) -> bool:
        return not self.terms

    @property
    def key(self) -> str:
        return "|".join([",".join(self.terms), ";".join(self.phrases), ",".join(self.excluded), self.site or ""])


def parse_query(raw: str, tok: Tokenizer) -> Query:
    q = Query(raw=raw)
    plain_words: list[str] = []
    seen: set[str] = set()

    def add_terms(text: str) -> None:
        for t in tok.tokenize(text):
            if t not in seen:
                seen.add(t)
                q.terms.append(t)

    for piece in _PIECES.findall(raw):
        low = piece.lower()
        if low.startswith('-"') or (low.startswith("-") and len(low) > 1):
            q.excluded.extend(tok.tokenize(piece.lstrip("-").strip('"')))
        elif piece.startswith('"'):
            phrase = tok.normalize_text(piece.strip('"'))
            if phrase:
                q.phrases.append(phrase)
                add_terms(piece.strip('"'))
        elif low.startswith("site:"):
            site = low[5:].strip("/")
            q.site = site[4:] if site.startswith("www.") else (site or None)
        else:
            add_terms(piece)
            plain_words.extend(tok.words(piece))
    if len(plain_words) >= 2 and not q.phrases:
        q.soft_phrase = " ".join(plain_words)
    return q
