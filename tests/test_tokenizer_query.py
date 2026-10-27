import unittest

import _helpers  # noqa: F401
from index.tokenizer import Tokenizer, normalize, stem
from search.query import parse_query


class TokenizerTests(unittest.TestCase):
    def setUp(self):
        self.tok = Tokenizer()

    def test_normalize_accents_case(self):
        self.assertEqual(normalize("Pitágoras ÇÃO"), "pitagoras cao")

    def test_stopwords_and_stemming(self):
        self.assertEqual(self.tok.tokenize("As funções do Python"), ["funcao", "python"])
        self.assertEqual(stem("professores"), "professor")
        self.assertEqual(stem("matemáticas".replace("á", "a")), "matematica")

    def test_digits_kept(self):
        self.assertIn("3", self.tok.tokenize("python 3"))

    def test_analyze_keeps_positions(self):
        text = "O Python é bom"
        toks = [t for t in self.tok.analyze(text) if t.term]
        self.assertEqual(text[toks[0].start:toks[0].end], "Python")


class QueryTests(unittest.TestCase):
    def setUp(self):
        self.tok = Tokenizer()

    def test_operators(self):
        q = parse_query('"teorema de pitágoras" triângulo -java site:www.exemplo.com', self.tok)
        self.assertEqual(q.phrases, ["teorema de pitagoras"])
        self.assertIn("triangulo", q.terms)
        self.assertEqual(q.excluded, ["java"])
        self.assertEqual(q.site, "exemplo.com")

    def test_soft_phrase(self):
        q = parse_query("juros compostos", self.tok)
        self.assertEqual(q.soft_phrase, "juros compostos")

    def test_only_stopwords_is_empty(self):
        self.assertTrue(parse_query("o que e", self.tok).is_empty)


if __name__ == "__main__":
    unittest.main()
