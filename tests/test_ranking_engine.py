import tempfile
import unittest
from pathlib import Path

import _helpers  # noqa: F401
from core.models import ParsedPage
from database.database import Database
from index.indexer import Indexer
from search.engine import SearchEngine


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "t.db")
        self.indexer = Indexer(self.db)
        self.engine = SearchEngine(self.db)
        filler = "palavras genéricas de preenchimento " * 20
        pages = [
            ParsedPage("https://a.com/pitagoras", "Teorema de Pitágoras", text="Triângulo retângulo e hipotenusa. " + filler,
                       headings=["Pitágoras"]),
            ParsedPage("https://b.com/historia", "História da Grécia", text="Pitágoras nasceu em Samos. " + filler),
            ParsedPage("https://c.com/python", "Python básico", text="Linguagem de programação. " + filler),
            ParsedPage("https://d.com/juros", "Juros", text="Juros simples e juros compostos. " + filler),
        ]
        for p in pages:
            self.assertEqual(self.indexer.add_page(p).status, "indexed")

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_title_ranks_first(self):
        r = self.engine.search("pitagoras")
        self.assertEqual([x.url for x in r.results][:2], ["https://a.com/pitagoras", "https://b.com/historia"])
        self.assertEqual(r.results[0].relevance, 100)
        self.assertLess(r.results[1].relevance, 100)
        self.assertIn("<b>", r.results[1].snippet_html)

    def test_accent_insensitive_and_plural(self):
        self.assertEqual(self.engine.search("PITÁGORAS").total, 2)
        self.assertEqual(self.engine.search("triangulos").total, 1)

    def test_coverage_prefers_all_terms(self):
        r = self.engine.search("juros programação")
        self.assertEqual(len(r.results), 2)  # OR com preferência por quem cobre mais
        r2 = self.engine.search("python programação")
        self.assertEqual(r2.results[0].url, "https://c.com/python")

    def test_phrase_filter_and_exclusion(self):
        self.assertEqual(self.engine.search('"juros compostos"').total, 1)
        self.assertEqual(self.engine.search('"compostos juros"').total, 0)
        self.assertEqual(self.engine.search("pitagoras -samos").total, 1)

    def test_site_filter(self):
        self.assertEqual(self.engine.search("pitagoras site:b.com").total, 1)

    def test_duplicates_and_noindex(self):
        dup = ParsedPage("https://z.com/copia", "Teorema de Pitágoras",
                         text="Triângulo retângulo e hipotenusa. " + "palavras genéricas de preenchimento " * 20,
                         headings=["Pitágoras"])
        out = self.indexer.add_page(dup)
        self.assertEqual((out.status, out.duplicate_of), ("duplicate", "https://a.com/pitagoras"))
        self.assertEqual(self.indexer.add_page(ParsedPage("https://n.com", "X", text="algo", noindex=True)).status, "noindex")

    def test_update_replaces_postings(self):
        self.indexer.add_page(ParsedPage("https://c.com/python", "Python avançado", text="Decoradores e geradores " * 20))
        self.assertEqual(self.engine.search("decoradores").total, 1)
        self.assertEqual(self.engine.search("programacao").total, 0)

    def test_favorite_boost_and_pagination(self):
        for i in range(25):
            self.indexer.add_page(ParsedPage(f"https://m.com/{i}", f"Matemática {i}", text=f"matemática exercício {i} " * 10))
        r = self.engine.search("matematica", offset=20, limit=10)
        self.assertEqual((r.total, len(r.results), r.has_more), (25, 5, False))
        self.db.set_favorite("https://m.com/7", True)
        self.assertEqual(self.engine.search("matematica").results[0].url, "https://m.com/7")
        self.assertTrue(self.engine.search("matematica").results[0].favorite)

    def test_empty_query(self):
        self.assertTrue(self.engine.search("o que é").message)


if __name__ == "__main__":
    unittest.main()
