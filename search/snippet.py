"""Geração do trecho (snippet) com os termos da consulta destacados em <b>."""
from __future__ import annotations

from html import escape

from index.tokenizer import Tokenizer


def make_snippet(tok: Tokenizer, text: str, terms: set[str], width: int = 240) -> str:
    text = text[:30_000]
    if not text:
        return ""
    hits = [t for t in tok.analyze(text) if t.term in terms]
    start = 0
    if hits:
        best_count, best_start, j = 0, hits[0].start, 0
        for i, h in enumerate(hits):
            while h.end - hits[j].start > width:
                j += 1
            if i - j + 1 > best_count:
                best_count, best_start = i - j + 1, hits[j].start
        start = max(0, best_start - 40)
        if start > 0:
            sp = text.find(" ", start)
            if 0 <= sp < best_start:
                start = sp + 1
    end = min(len(text), start + width)
    if end < len(text):
        sp = text.rfind(" ", start, end)
        if sp > start + width // 2:
            end = sp
    segment = text[start:end]
    out, pos = [], 0
    for h in hits:
        if h.start < start or h.end > end:
            continue
        a, b = h.start - start, h.end - start
        out.append(escape(segment[pos:a]))
        out.append(f"<b>{escape(segment[a:b])}</b>")
        pos = b
    out.append(escape(segment[pos:]))
    html = "".join(out).strip()
    return ("… " if start > 0 else "") + html + (" …" if end < len(text) else "")
