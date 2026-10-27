"""Modelos de dados compartilhados entre UI, motor, crawler e (futuramente) API."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ParsedPage:
    url: str
    title: str = ""
    description: str = ""
    keywords: str = ""
    lang: str = ""
    canonical: str = ""
    headings: list[str] = field(default_factory=list)
    text: str = ""
    links: list[str] = field(default_factory=list)
    noindex: bool = False
    nofollow: bool = False


@dataclass
class Posting:
    tf_body: int = 0
    tf_title: int = 0
    tf_headings: int = 0
    tf_url: int = 0


@dataclass
class DocStats:
    doc_id: int
    length: int
    source: str
    favorite: bool
    inlinks: int
    domain: str


@dataclass
class DocMeta:
    doc_id: int
    url: str
    content_hash: str
    fetched_at: float


@dataclass
class Document:
    doc_id: int
    url: str
    domain: str
    title: str
    description: str
    headings: str
    body: str
    lang: str
    source: str          # web | local | bookmark
    favorite: bool
    fetched_at: float
    length: int


@dataclass
class ScoreBreakdown:
    text_score: float = 0.0
    coverage: float = 1.0
    matched_terms: int = 0
    total_terms: int = 0
    title_all: bool = False
    phrase_in_title: bool = False
    phrase_in_body: bool = False
    favorite: bool = False
    inlinks: int = 0
    short_page: bool = False
    # multiplicadores/bônus aplicados (preenchidos pelo Ranker)
    base: float = 0.0
    bonus_total: float = 0.0
    length_factor: float = 1.0
    total: float = 0.0
    per_term: dict[str, float] = field(default_factory=dict)

    def explain(self) -> str:
        lines = [
            f"Pontuação final: {self.total:.2f}",
            f"• Texto (BM25 ponderado): {self.text_score:.2f}",
            f"• Cobertura: {self.matched_terms}/{self.total_terms} termos",
            f"• Base (texto × cobertura²): {self.base:.2f}",
            f"• Bônus somados: +{self.bonus_total * 100:.0f}%",
        ]
        if self.title_all:
            lines.append("   – todos os termos no título")
        if self.phrase_in_title or self.phrase_in_body:
            lines.append("   – frase completa encontrada")
        if self.favorite:
            lines.append("   – favorito")
        if self.inlinks:
            lines.append(f"   – {self.inlinks} link(s) recebido(s) no índice")
        if self.short_page:
            lines.append("• Página muito curta: ×0.8")
        return "\n".join(lines)


@dataclass
class SearchResult:
    doc_id: int
    title: str
    url: str
    domain: str
    snippet_html: str
    score: float
    relevance: int            # 0-100, relativa ao melhor resultado da consulta
    breakdown: ScoreBreakdown
    source: str = "web"
    favorite: bool = False
    fetched_at: float = 0.0


@dataclass
class SearchResponse:
    query: str
    results: list[SearchResult]
    total: int
    elapsed_ms: float
    offset: int = 0
    message: str = ""
    mode: str = "online"

    @property
    def has_more(self) -> bool:
        return self.offset + len(self.results) < self.total
