import unittest

import _helpers  # noqa: F401
from crawler.parser import parse_html
from crawler.urls import is_crawlable_extension, normalize_url

HTML = """<!doctype html><html lang="pt-BR"><head><title> Minha  Página </title>
<meta name="description" content="Resumo da página"><meta name="keywords" content="a, b">
<base href="https://exemplo.com/dir/"><link rel="canonical" href="/canon">
<style>.x{color:red}</style><script>var x = "não indexar";</script></head>
<body><nav><a href="/menu">menu</a> texto do menu</nav><h1>Cabeçalho Um</h1><p>Texto &amp; mais texto.</p>
<a href="pagina2.html#topo">link</a><a href="mailto:a@b.c">mail</a><a rel="nofollow" href="/nf">nf</a>
<footer>rodapé</footer></body></html>"""


class ParserTests(unittest.TestCase):
    def test_extraction(self):
        p = parse_html(HTML, "https://exemplo.com/")
        self.assertEqual(p.title, "Minha Página")
        self.assertEqual(p.description, "Resumo da página")
        self.assertEqual(p.lang, "pt-br")
        self.assertEqual(p.headings, ["Cabeçalho Um"])
        self.assertIn("Texto & mais texto.", p.text)
        self.assertNotIn("não indexar", p.text)
        self.assertNotIn("rodapé", p.text)
        self.assertIn("https://exemplo.com/dir/pagina2.html#topo", p.links)
        self.assertNotIn("https://exemplo.com/nf", p.links)
        self.assertEqual(p.canonical, "https://exemplo.com/canon")

    def test_robots_meta(self):
        p = parse_html('<meta name="robots" content="noindex, nofollow"><p>x</p>', "https://a.com/")
        self.assertTrue(p.noindex and p.nofollow)

    def test_broken_html_does_not_crash(self):
        parse_html("<div><p>aberto <b>sem fechar <a href='/x'>", "https://a.com/")

    def test_normalize_url(self):
        self.assertEqual(normalize_url("HTTP://Exemplo.com:80/a?utm_source=x&b=1#frag"), "http://exemplo.com/a?b=1")
        self.assertIsNone(normalize_url("javascript:alert(1)"))
        self.assertIsNone(normalize_url("mailto:a@b.c"))
        self.assertEqual(normalize_url("../x", "https://a.com/d/e/"), "https://a.com/d/x")
        self.assertFalse(is_crawlable_extension("https://a.com/f.pdf"))
        self.assertTrue(is_crawlable_extension("https://a.com/pagina"))


if __name__ == "__main__":
    unittest.main()
