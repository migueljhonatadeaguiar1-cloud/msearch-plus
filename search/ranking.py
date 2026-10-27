"""Ranking do M-Search+  —  como a pontuação é calculada
=====================================================

Para cada documento candidato (que contém ao menos um termo da consulta):

1) TEXTO  —  BM25 com campos ponderados
   Para cada termo t da consulta:
       wtf(t)  = 5·tf_título + 3·tf_cabeçalhos + 2·tf_url + 1·tf_corpo
       parte   = (k1+1)·wtf / (wtf + k1·(1 − b + b·len/avg_len))        k1=1.2  b=0.75
       idf(t)  = ln(1 + (N − df + 0.5) / (df + 0.5))                    (termos raros valem mais)
       score_t = idf(t) · parte
   text_score = Σ score_t

2) COBERTURA  —  quantos termos da consulta o documento contém
       cobertura = termos_encontrados / termos_da_consulta
       base      = text_score · cobertura²        (quem tem TODOS os termos passa na frente)

3) BÔNUS (multiplicativos, somados entre si)
       +30%  todos os termos aparecem no título
       +25%  frase da consulta aparece inteira no título
       +15%  frase da consulta aparece inteira no texto
       +15%  página marcada como favorita
       +5%·ln(1 + links_recebidos), no máximo +20%   (links vindos de outras páginas indexadas)

4) PENALIDADE: páginas com menos de 30 palavras úteis ×0.8

       total = base · (1 + soma_dos_bônus) · fator_tamanho

A "relevância" exibida (0–100%) é total / total_do_melhor_resultado: ela é RELATIVA à consulta,
não uma nota absoluta de qualidade. Todos os pesos estão em RankingParams.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from core.models import DocStats, Posting, ScoreBreakdown


@dataclass
class RankingParams:
    w_title: float = 5.0
    w_headings: float = 3.0
    w_url: float = 2.0
    w_body: float = 1.0
    k1: float = 1.2
    b: float = 0.75
    coverage_power: float = 2.0
    bonus_title_all: float = 0.30
    bonus_phrase_title: float = 0.25
    bonus_phrase_body: float = 0.15
    bonus_favorite: float = 0.15
    bonus_inlinks_weight: float = 0.05
    bonus_inlinks_max: float = 0.20
    short_page_words: int = 30
    short_page_factor: float = 0.8


class Ranker:
    def __init__(self, params: RankingParams | None = None):
        self.p = params or RankingParams()

    @staticmethod
    def idf(n_docs: int, df: int) -> float:
        return math.log(1.0 + (n_docs - df + 0.5) / (df + 0.5))

    def score(self, *, terms: list[str], doc_postings: dict[str, Posting], df: dict[str, int],
              n_docs: int, avg_len: float, stats: DocStats) -> ScoreBreakdown:
        p = self.p
        bd = ScoreBreakdown(total_terms=len(terms), favorite=stats.favorite, inlinks=stats.inlinks,
                            short_page=stats.length < p.short_page_words)
        avg = max(avg_len, 1.0)
        norm = 1.0 - p.b + p.b * (max(stats.length, 1) / avg)
        title_hits = 0
        for t in terms:
            post = doc_postings.get(t)
            if post is None:
                continue
            bd.matched_terms += 1
            if post.tf_title > 0:
                title_hits += 1
            wtf = (p.w_title * post.tf_title + p.w_headings * post.tf_headings
                   + p.w_url * post.tf_url + p.w_body * post.tf_body)
            part = (p.k1 + 1.0) * wtf / (wtf + p.k1 * norm)
            s = self.idf(n_docs, df[t]) * part
            bd.per_term[t] = s
            bd.text_score += s
        bd.coverage = bd.matched_terms / max(len(terms), 1)
        bd.title_all = bool(terms) and title_hits == len(terms)
        return self._finalize(bd)

    def apply_phrase(self, bd: ScoreBreakdown, in_title: bool, in_body: bool) -> ScoreBreakdown:
        bd.phrase_in_title, bd.phrase_in_body = in_title, in_body
        return self._finalize(bd)

    def _finalize(self, bd: ScoreBreakdown) -> ScoreBreakdown:
        p = self.p
        bd.base = bd.text_score * (bd.coverage ** p.coverage_power)
        bonus = 0.0
        if bd.title_all:
            bonus += p.bonus_title_all
        if bd.phrase_in_title:
            bonus += p.bonus_phrase_title
        if bd.phrase_in_body:
            bonus += p.bonus_phrase_body
        if bd.favorite:
            bonus += p.bonus_favorite
        if bd.inlinks:
            bonus += min(p.bonus_inlinks_max, p.bonus_inlinks_weight * math.log(1 + bd.inlinks))
        bd.bonus_total = bonus
        bd.length_factor = p.short_page_factor if bd.short_page else 1.0
        bd.total = bd.base * (1.0 + bonus) * bd.length_factor
        return bd
