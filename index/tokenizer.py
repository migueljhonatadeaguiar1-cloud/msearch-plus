"""Normalização e tokenização.

Pipeline:  texto → minúsculas → remove acentos → palavras → stopwords → stemming leve.
O MESMO pipeline é usado na indexação e na consulta (essencial para o casamento funcionar).
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

_WORD = re.compile(r"[^\W_]+", re.UNICODE)


def strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def normalize(text: str) -> str:
    return strip_accents(text.lower())


_STOP_PT = """
de da do das dos em no na nos nas um uma uns umas por para com sem sob sobre entre ate
que quem qual quais como onde quando porque pois se mas ou e nem ao aos as os
foi era ser sao eh esta estao estou tem ter tinha ha havia isso isto esse essa esses essas
este esta estes estas aquele aquela seu sua seus suas meu minha nosso nossa ele ela eles elas
eu tu voce nos vos lhe lhes mais menos muito muita tambem ja so sua
"""
_STOP_EN = """
the a an and or of to in on at by for with from as is are was were be been being this that
these those it its he she they we you i his her their our your not no but if then than so
do does did have has had will would can could should may might
"""
STOPWORDS = {normalize(w) for w in (_STOP_PT + _STOP_EN).split()}


def stem(word: str) -> str:
    """Stemming leve (plurais comuns em PT/EN). Propositalmente simples e previsível."""
    if len(word) <= 3 or word.isdigit():
        return word
    if word.endswith(("oes", "aes")):
        return word[:-3] + "ao"
    if word.endswith("ies") and len(word) > 4:
        return word[:-3] + "y"
    if word.endswith(("res", "zes", "nes")):
        return word[:-2]
    if word.endswith(("ss", "us", "is")):
        return word
    if word.endswith("s"):
        return word[:-1]
    return word


@dataclass(frozen=True)
class Token:
    term: str | None   # None = stopword/curto demais (mantém posição para snippets)
    start: int
    end: int


class Tokenizer:
    def __init__(self, stopwords: set[str] | None = None, min_len: int = 2, max_len: int = 40):
        self.stopwords = STOPWORDS if stopwords is None else stopwords
        self.min_len = min_len
        self.max_len = max_len

    def _term(self, raw_word: str) -> str | None:
        w = normalize(raw_word)
        if len(w) > self.max_len:
            return None
        if len(w) < self.min_len and not w.isdigit():
            return None
        if w in self.stopwords:
            return None
        return stem(w)

    def analyze(self, text: str) -> list[Token]:
        return [Token(self._term(m.group()), m.start(), m.end()) for m in _WORD.finditer(text)]

    def tokenize(self, text: str) -> list[str]:
        return [t for t in (self._term(m.group()) for m in _WORD.finditer(text)) if t]

    def words(self, text: str) -> list[str]:
        """Palavras normalizadas SEM remover stopwords nem aplicar stemming (para frases)."""
        return [normalize(m.group()) for m in _WORD.finditer(text)]

    def normalize_text(self, text: str) -> str:
        return " ".join(self.words(text))
