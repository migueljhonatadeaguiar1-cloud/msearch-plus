"""Motor de busca: consulta → índice → ranking → resultados.

Não conhece UI, crawler nem rede. Só precisa de um IndexStore.
"""
from __future__ import annotations

import time

from core.models import DocStats, SearchResponse, SearchResult, ScoreBreakdown
from database.interfaces import IndexStore
from index.tokenizer import Tokenizer
from search.query import Query, parse_query
from search.ranking import Ranker
from search.snippet import make_snippet

SOFT_PHRASE_TOP_K = 100


class SearchEngine:
    def __init__(self, store: IndexStore, tokenizer: Tokenizer | None = None, ranker: Ranker | None = None,
                 max_candidates: int = 1000):
        self.store = store
        self.tok = tokenizer or Tokenizer()
        self.ranker = ranker or Ranker()
        self.max_candidates = max_candidates
        self._cache_key: tuple | None = None
        self._cache_value: list[tuple[int, ScoreBreakdown]] = []

    # ------------------------------------------------------------------ API
    def search(self, text: str, *, offset: int = 0, limit: int = 10) -> SearchResponse:
        t0 = time.perf_counter()
        query = parse_query(text, self.tok)
        if query.is_empty:
            return SearchResponse(text, [], 0, 0.0, offset, "Digite pelo menos uma palavra significativa.")
        ranked = self._ranked(query)
        page = ranked[offset:offset + limit]
        docs = self.store.get_documents([doc_id for doc_id, _ in page])
        top = ranked[0][1].total if ranked else 1.0
        terms = set(query.terms)
        results: list[SearchResult] = []
        for doc_id, bd in page:
            d = docs.get(doc_id)
            if d is None:
                continue
            results.append(SearchResult(
                doc_id=doc_id, title=d.title or d.url, url=d.url, domain=d.domain,
                snippet_html=make_snippet(self.tok, d.body, terms), score=bd.total,
                relevance=max(1, round(100 * bd.total / top)) if top > 0 else 0, breakdown=bd,
                source=d.source, favorite=d.favorite, fetched_at=d.fetched_at))
        return SearchResponse(text, results, len(ranked), (time.perf_counter() - t0) * 1000, offset)

    # ------------------------------------------------------------ internals
    def _ranked(self, q: Query) -> list[tuple[int, ScoreBreakdown]]:
        key = (q.key, self.store.version)
        if key == self._cache_key:
            return self._cache_value

        postings = self.store.get_postings(q.terms)
        df = {t: len(postings[t]) for t in q.terms}
        candidates = {d for t in q.terms for d in postings[t]}
        if q.excluded:
            for plist in self.store.get_postings(q.excluded).values():
                candidates -= set(plist)
        if not candidates:
            return self._remember(key, [])

        stats = self.store.get_doc_stats(list(candidates))
        if q.site:
            stats = {i: s for i, s in stats.items() if self._site_match(s, q.site)}

        n_docs, avg_len = self.store.corpus_stats()
        scored: list[tuple[int, ScoreBreakdown]] = []
        for doc_id, st in stats.items():
            per_doc = {t: postings[t][doc_id] for t in q.terms if doc_id in postings[t]}
            scored.append((doc_id, self.ranker.score(terms=q.terms, doc_postings=per_doc, df=df,
                                                     n_docs=n_docs, avg_len=avg_len, stats=st)))
        scored.sort(key=lambda x: (-x[1].total, x[0]))
        scored = scored[:self.max_candidates]

        scored = self._phrase_pass(q, scored)
        scored.sort(key=lambda x: (-x[1].total, x[0]))
        return self._remember(key, scored)

    def _phrase_pass(self, q: Query, scored: list[tuple[int, ScoreBreakdown]]) -> list[tuple[int, ScoreBreakdown]]:
        bonus_phrases = q.phrases or ([q.soft_phrase] if q.soft_phrase else [])
        if not bonus_phrases:
            return scored
        check_ids = [i for i, _ in scored] if q.phrases else [i for i, _ in scored[:SOFT_PHRASE_TOP_K]]
        by_id = dict(scored)
        keep: set[int] = set(by_id) if not q.phrases else set()
        for doc in self.store.iter_documents(check_ids):
            norm_title = f" {self.tok.normalize_text(doc.title)} "
            norm_body = f" {self.tok.normalize_text(doc.title + ' ' + doc.headings + ' ' + doc.body)} "
            in_title = any(f" {p} " in norm_title for p in bonus_phrases)
            in_body = all(f" {p} " in norm_body for p in bonus_phrases)
            if q.phrases:
                if not in_body:
                    continue
                keep.add(doc.doc_id)
            self.ranker.apply_phrase(by_id[doc.doc_id], in_title, in_body)
        return [(i, by_id[i]) for i, _ in scored if i in keep]

    @staticmethod
    def _site_match(st: DocStats, site: str) -> bool:
        return st.domain == site or st.domain.endswith("." + site)

    def _remember(self, key: tuple, value: list) -> list:
        self._cache_key, self._cache_value = key, value
        return value
