import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import _helpers  # noqa: F401
from core.service import OfflineError, SearchPlusService
from offline.fsutil import is_dangerous_filename, safe_filename, unique_path
from offline.page_library import SCHEME, page_id_for
from ui.browser.url_utils import resolve_input, security_state

PNG = bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d49444154789c63000100000005000100"
                    "0d0a2db40000000049454e44ae426082")
SITE = {
    "/aula/": ("text/html; charset=utf-8", """<!doctype html><html><head><title>Aula de Funções</title>
<base href="/aula/"><meta charset="iso-8859-1"><meta http-equiv="Content-Security-Policy" content="default-src 'none'">
<link rel="stylesheet" href="../static/style.css" integrity="sha384-xxx" crossorigin="anonymous">
<link rel="icon" href="/favicon.png"><link rel="canonical" href="/aula/">
<style>.hero{background:url('/static/bg.png')}</style>
<script src="/static/app.js" integrity="sha384-yyy"></script></head>
<body><h1>Funções do segundo grau</h1>
<img src="logo.png" srcset="logo.png 1x, /static/logo2.png 2x" alt="x">
<div style="background:url(/static/bg.png)">fundo</div>
<a href="questoes">Questões</a><a href="#topo">topo</a><a href="mailto:a@b.c">mail</a>
<img src="/static/missing.png"><script>var s = '<img src="/static/NAO_BAIXAR.png">';</script>
<!-- <img src="/static/comentario.png"> -->
<img src="https://cdn.exemplo.invalid/externo.png"></body></html>"""),
    "/static/style.css": ("text/css", "@import url('base.css');\n@font-face{font-family:F;src:url(/static/fonte.woff2) format('woff2')}\n"
                          ".a{background:url(\"img/pixel.png\")}"),
    "/static/base.css": ("text/css", "body{margin:0}"),
    "/static/fonte.woff2": ("font/woff2", "FONTDATA"),
    "/static/img/pixel.png": ("image/png", PNG),
    "/static/bg.png": ("image/png", PNG),
    "/static/app.js": ("application/javascript", "document.title += ' ok';"),
    "/aula/logo.png": ("image/png", PNG),
    "/static/logo2.png": ("image/png", PNG),
    "/favicon.png": ("image/png", PNG),
}
Hits: list[str] = []


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        path = self.path.split("?")[0]
        Hits.append(path)
        item = SITE.get(path)
        if item is None:
            self.send_response(404)
            self.end_headers()
            return
        ctype, body = item
        data = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class SaverTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def setUp(self):
        Hits.clear()
        self.tmp = tempfile.TemporaryDirectory()
        self.service = SearchPlusService(self.tmp.name)
        s = self.service.settings
        s.allow_local_network, s.connectivity_mode, s.timeout_s = True, "online", 5.0
        self.service.connectivity.probe()

    def tearDown(self):
        self.service.close()
        self.tmp.cleanup()

    def test_full_page_is_saved_with_resources_and_rewritten(self):
        url = f"{self.base}/aula/"
        report = self.service.save_page_offline(url)
        folder = self.service.paths.saved_pages_dir / report.page_id
        html = (folder / "index.html").read_text(encoding="utf-8")

        for rel in ("css/style.css", "css/base.css", "fonts/fonte.woff2", "js/app.js", "images/bg.png",
                    "images/logo.png", "images/logo2.png", "images/favicon.png", "images/pixel.png"):
            self.assertTrue((folder / rel).is_file(), rel)
        # HTML reescrito para caminhos locais
        self.assertIn('href="css/style.css"', html)
        self.assertIn('src="js/app.js"', html)
        self.assertIn('src="images/logo.png"', html)
        self.assertIn("images/logo.png 1x, images/logo2.png 2x", html)
        self.assertIn("url(images/bg.png)", html)                 # style="" inline
        self.assertIn("url('images/bg.png')", html)               # <style>
        self.assertNotIn("<base", html)
        self.assertNotIn("Content-Security-Policy", html)
        self.assertNotIn("integrity", html)
        self.assertNotIn("crossorigin", html)
        self.assertIn('<meta charset="utf-8">', html)
        self.assertNotIn("iso-8859-1", html)
        self.assertIn(f'href="{self.base}/aula/questoes"', html)  # links viram absolutos
        self.assertIn('href="#topo"', html)
        self.assertIn('href="mailto:a@b.c"', html)
        # CSS: caminhos relativos ao arquivo CSS
        css = (folder / "css/style.css").read_text(encoding="utf-8")
        self.assertIn("url('base.css')", css)
        self.assertIn("../fonts/fonte.woff2", css)
        self.assertIn('"../images/pixel.png"', css)
        # não baixa o que está em script/comentário; falhas ficam com URL original
        self.assertNotIn("/static/NAO_BAIXAR.png", Hits)
        self.assertNotIn("/static/comentario.png", Hits)
        self.assertIn("https://cdn.exemplo.invalid/externo.png", html)
        self.assertEqual(len(report.failed), 2)                   # missing.png + externo.invalid
        self.assertEqual(json.loads((folder / "manifest.json").read_text())["url"], url)
        # indexada e registrada
        self.assertEqual(self.service.search("segundo grau").total, 1)
        self.assertEqual(self.service.offline.library.find_by_url(url).kind, "full")

    def test_offline_target_uses_saved_copy_or_reports_unavailable(self):
        url = f"{self.base}/aula/"
        self.service.save_page_offline(url)
        self.service.settings.connectivity_mode = "offline"
        self.service.connectivity.probe()
        target, mode = self.service.browser_target(url)
        self.assertEqual(mode, "offline")
        self.assertEqual(target, f"{SCHEME}://{page_id_for(url)}/index.html")
        self.assertEqual(self.service.browser_target("https://nao-salva.example/")[1], "unavailable")
        with self.assertRaises(OfflineError):
            self.service.save_page_offline(url)
        self.service.settings.connectivity_mode = "online"
        self.service.connectivity.probe()
        self.assertEqual(self.service.browser_target("https://qualquer.example/x"), ("https://qualquer.example/x", "online"))

    def test_cache_fallback_creates_html_only_copy(self):
        self.service.crawl([f"{self.base}/aula/"], max_depth=0)
        self.service.settings.connectivity_mode = "offline"
        self.service.connectivity.probe()
        target, mode = self.service.browser_target(f"{self.base}/aula/")
        self.assertEqual(mode, "offline")
        page = self.service.offline.library.find_by_url(f"{self.base}/aula/")
        self.assertEqual(page.kind, "html_only")

    def test_library_resolution_is_sandboxed(self):
        report = self.service.save_page_offline(f"{self.base}/aula/")
        lib, pid = self.service.offline.library, report.page_id
        secret = Path(self.tmp.name) / "segredo.txt"
        secret.write_text("x")
        self.assertIsNotNone(lib.resolve_file(pid, "/css/style.css"))
        self.assertIsNotNone(lib.resolve_file(pid, "/"))                      # → index.html
        for evil in ("/../segredo.txt", "/%2e%2e/segredo.txt", "/css/../../segredo.txt", "/..%2f..%2fsegredo.txt",
                     "/css/\x00x"):
            self.assertIsNone(lib.resolve_file(pid, evil), evil)
        self.assertIsNone(lib.resolve_file("../etc", "/passwd"))
        self.assertIsNone(lib.resolve_file("p000000000000", "/index.html"))

    def test_local_html_is_isolated_copy_and_never_touches_network(self):
        site = Path(self.tmp.name) / "meusite"
        (site / "css").mkdir(parents=True)
        (site / "css" / "a.css").write_text("body{background:url(../bg.png)}", encoding="utf-8")
        (site / "bg.png").write_bytes(PNG)
        (Path(self.tmp.name) / "fora.txt").write_text("privado")
        page = site / "index.html"
        page.write_text('<title>Local</title><link rel="stylesheet" href="css/a.css"><img src="../fora.txt">'
                        '<img src="http://127.0.0.1/x.png"><p>conteúdo local</p>', encoding="utf-8")
        target = self.service.offline.ensure_local_copy(page.as_uri())
        self.assertTrue(target.startswith(f"{SCHEME}://"))
        pid = target.split("//")[1].split("/")[0]
        folder = self.service.paths.saved_pages_dir / pid
        self.assertTrue((folder / "css/a.css").is_file())
        self.assertTrue((folder / "images/bg.png").is_file())
        self.assertFalse((folder / "other/fora.txt").exists())     # fora da pasta-raiz: não copia
        self.assertNotIn("fora.txt", (folder / "index.html").read_text(encoding="utf-8"))
        self.assertEqual(Hits, [])                                 # nenhuma requisição de rede
        txt = Path(self.tmp.name) / "nota.md"
        txt.write_text("# Título\n<script>alert(1)</script>", encoding="utf-8")
        t2 = self.service.offline.ensure_local_copy(txt.as_uri())
        html = (self.service.paths.saved_pages_dir / t2.split("//")[1].split("/")[0] / "index.html").read_text()
        self.assertIn("&lt;script&gt;", html)
        self.assertIsNone(self.service.offline.ensure_local_copy((Path(self.tmp.name) / "nao.html").as_uri()))

    def test_privacy_clear_removes_saved_pages(self):
        report = self.service.save_page_offline(f"{self.base}/aula/")
        self.service.privacy.clear_saved_pages()
        self.assertFalse((self.service.paths.saved_pages_dir / report.page_id).exists())
        self.assertEqual(self.service.stats()["saved_pages"], 0)


class UtilTests(unittest.TestCase):
    def test_address_bar(self):
        self.assertEqual(resolve_input("obmep.org.br/q").value, "https://obmep.org.br/q")
        self.assertEqual(resolve_input("OBMEP fase 2 2024").kind, "search")
        self.assertEqual(resolve_input("localhost:8000").value, "http://localhost:8000")
        for bad in ("javascript:alert(1)", "data:text/html,x", "ftp://x.com", "vbscript:x", "http://", "https://a b.com"):
            self.assertEqual(resolve_input(bad).kind, "invalid", bad)
        self.assertEqual(resolve_input("").kind, "blank")
        self.assertEqual(security_state("https://a.com"), "secure")
        self.assertEqual(security_state("http://a.com"), "insecure")
        self.assertEqual(security_state(f"{SCHEME}://p1/index.html"), "offline")

    def test_filenames(self):
        self.assertEqual(safe_filename("../../etc/passwd"), "passwd")
        self.assertEqual(safe_filename("a:b*c?.pdf"), "a_b_c_.pdf")
        self.assertEqual(safe_filename("CON.txt"), "_CON.txt")
        self.assertEqual(safe_filename("..."), "arquivo")
        self.assertTrue(is_dangerous_filename("setup.EXE"))
        self.assertFalse(is_dangerous_filename("prova.pdf"))
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "a.pdf").write_text("x")
            self.assertEqual(unique_path(Path(d), "a.pdf").name, "a (1).pdf")


if __name__ == "__main__":
    unittest.main()
