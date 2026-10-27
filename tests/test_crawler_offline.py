import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import _helpers  # noqa: F401
from core.service import OfflineError, SearchPlusService
from offline.offline_engine import OFFLINE_MESSAGE

BODY = "<p>" + "Conteúdo de teste sobre geometria e triângulos. " * 8 + "</p>"
PAGES = {
    "/": '<title>Início</title><h1>Início do site</h1><a href="/a">a</a><a href="/dup">dup</a>'
         '<a href="/private/x">p</a><a href="/redir">r</a><a href="/noindex">n</a><a href="/img.png">i</a>'
         '<a href="http://outro.invalid/">fora</a><p>Página inicial com <b>teorema</b>.</p>',
    "/a": f"<title>Teorema de Pitágoras</title><h1>Pitágoras</h1>{BODY}<a href='/b'>b</a>",
    "/b": f"<title>Página B profunda</title>{BODY} única de B",
    "/dup": f"<title>Teorema de Pitágoras</title><h1>Pitágoras</h1>{BODY}",
    "/private/x": "<title>Segredo</title><p>não deve ser indexado nunca</p>",
    "/noindex": '<meta name="robots" content="noindex"><title>Oculta</title><p>conteúdo oculto</p>',
}


class Handler(BaseHTTPRequestHandler):
    hits: list[str] = []

    def log_message(self, *a):
        pass

    def do_GET(self):
        Handler.hits.append(self.path)
        if self.path == "/robots.txt":
            return self._send(200, "User-agent: *\nDisallow: /private/\nCrawl-delay: 0\n", "text/plain")
        if self.path == "/redir":
            self.send_response(302)
            self.send_header("Location", "/a?utm_source=x")
            self.end_headers()
            return
        if self.path in PAGES:
            return self._send(200, f"<!doctype html><html><head>{PAGES[self.path]}</head></html>")
        self._send(404, "nada")

    def _send(self, code, body, ctype="text/html; charset=utf-8"):
        data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class CrawlerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def setUp(self):
        Handler.hits.clear()
        self.tmp = tempfile.TemporaryDirectory()
        self.service = SearchPlusService(self.tmp.name)
        s = self.service.settings
        s.allow_local_network, s.request_delay_s, s.timeout_s = True, 0.0, 5.0
        s.connectivity_mode = "online"
        self.service.connectivity.probe()

    def tearDown(self):
        self.service.close()
        self.tmp.cleanup()

    def test_crawl_respects_robots_dedupes_and_indexes(self):
        stats = self.service.crawl([self.base], max_depth=2, max_pages=20)
        self.assertNotIn("/private/x", Handler.hits)              # robots.txt respeitado
        self.assertIn("/robots.txt", Handler.hits)
        self.assertNotIn("/img.png", Handler.hits)                # extensão ignorada
        self.assertEqual(stats.blocked_by_robots, 1)
        self.assertGreaterEqual(stats.duplicates, 1)              # /dup e/ou /redir
        self.assertEqual(stats.noindex, 1)
        self.assertEqual(self.service.search("segredo").total, 0)
        self.assertEqual(self.service.search("oculta").total, 0)
        r = self.service.search("pitagoras")
        self.assertEqual(r.total, 1)
        self.assertEqual(r.results[0].domain, "127.0.0.1")
        self.assertEqual(self.service.search("profunda").total, 1)  # profundidade 2 alcançada
        self.assertTrue(self.service.offline.has_cached_copy(r.results[0].url))

    def test_recrawl_uses_cache(self):
        self.service.crawl([self.base], max_depth=0)
        Handler.hits.clear()
        stats = self.service.crawl([self.base], max_depth=0)
        self.assertEqual(stats.from_cache, 1)
        self.assertNotIn("/", [h for h in Handler.hits if h != "/robots.txt"])

    def test_offline_mode(self):
        self.service.crawl([self.base], max_depth=1)
        self.service.settings.connectivity_mode = "offline"
        self.service.connectivity.probe()
        with self.assertRaises(OfflineError):
            self.service.crawl([self.base])
        self.assertGreater(self.service.search("pitagoras").total, 0)     # índice local continua funcionando
        miss = self.service.search("inexistente")
        self.assertEqual((miss.total, miss.mode, miss.message), (0, "offline", OFFLINE_MESSAGE))

    def test_cached_copy_is_sanitized(self):
        self.service.crawl([self.base], max_depth=1)
        url = self.service.search("pitagoras").results[0].url
        path = self.service.offline.cached_copy_path(url)
        html = Path(path).read_text(encoding="utf-8")
        self.assertIn("Content-Security-Policy", html)
        self.assertNotIn("<script", html.lower())

    def test_local_import_bookmarks_and_privacy(self):
        folder = Path(self.tmp.name) / "notas"
        folder.mkdir()
        (folder / "aula.md").write_text("# Bhaskara\nEquação do segundo grau e discriminante.", encoding="utf-8")
        self.assertEqual(self.service.offline.import_path(folder)["imported"], 1)
        self.assertEqual(self.service.search("discriminante").results[0].source, "local")
        self.service.offline.set_favorite("https://fav.example/x", "Meu favorito de álgebra")
        r = self.service.search("algebra")
        self.assertEqual((r.total, r.results[0].source, r.results[0].favorite), (1, "bookmark", True))
        self.assertEqual(self.service.stats()["history"], 0)             # histórico desligado por padrão
        self.service.settings.save_search_history = True
        self.service.search("algebra")
        self.assertEqual(self.service.stats()["history"], 1)
        self.service.privacy.clear_all()
        st = self.service.stats()
        self.assertEqual((st["documents"], st["history"], st["cached_pages"]), (0, 0, 0))

    def test_private_network_blocked_by_default(self):
        self.service.settings.allow_local_network = False
        stats = self.service.crawl([self.base], max_depth=0)
        self.assertEqual(stats.processed, 0)
        self.assertGreaterEqual(stats.blocked_by_robots + stats.errors, 1)


if __name__ == "__main__":
    unittest.main()
