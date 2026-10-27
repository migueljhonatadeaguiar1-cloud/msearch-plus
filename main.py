"""M-Search+ V1 — ponto de entrada.

    python main.py                          # abre a interface (PyQt6)
    python main.py --cli "pitágoras"        # busca no terminal (sem interface)
    python main.py --crawl https://example.com --depth 1
    python main.py --load-samples           # importa as páginas de exemplo
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from core.service import SearchPlusService  # noqa: E402


def run_cli(args) -> int:
    service = SearchPlusService(args.data_dir)
    try:
        if args.load_samples:
            print("Importados:", service.load_sample_pages())
        if args.crawl:
            stats = service.crawl(args.crawl, max_pages=args.max_pages, max_depth=args.depth,
                                  on_event=lambda kind, msg: print(f"[{kind}] {msg}"))
            print(stats.summary())
        if args.cli:
            resp = service.search(args.cli)
            print(f"\n{resp.total} resultado(s) em {resp.elapsed_ms:.1f} ms  [{resp.mode}]")
            if resp.message:
                print(resp.message)
            for i, r in enumerate(resp.results, 1):
                print(f"\n{i}. {r.title}  ({r.relevance}%)\n   {r.url}")
        return 0
    finally:
        service.close()


def run_gui(args) -> int:
    from PyQt6.QtCore import QCoreApplication, QTimer, Qt
    from PyQt6.QtWidgets import QApplication
    from ui.browser import WEBENGINE_AVAILABLE, WEBENGINE_ERROR   # importa o WebEngine ANTES do QApplication
    from ui.main_window import MainWindow

    if WEBENGINE_AVAILABLE:
        from ui.browser.offline_scheme import register_scheme
        QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
        register_scheme()                                         # esquema searchplus-offline:// (antes do app)
    else:
        print("Aviso: navegador interno indisponível:", WEBENGINE_ERROR, "\n       pip install PyQt6-WebEngine")
    app = QApplication(sys.argv)
    app.setApplicationName("M-Search+")
    service = SearchPlusService(args.data_dir)
    window = MainWindow(service)
    window.show()
    if args.open_url:
        QTimer.singleShot(1000, lambda: window.open_url(args.open_url))
    code = app.exec()
    service.close()
    return code


def main() -> int:
    p = argparse.ArgumentParser(description="M-Search+ — mecanismo de busca próprio")
    p.add_argument("--data-dir", help="pasta de dados (padrão: pasta do usuário)")
    p.add_argument("--cli", metavar="CONSULTA", help="pesquisa no terminal")
    p.add_argument("--crawl", nargs="+", metavar="URL", help="indexa as URLs semente")
    p.add_argument("--depth", type=int, default=1)
    p.add_argument("--max-pages", type=int, default=20)
    p.add_argument("--load-samples", action="store_true", help="importa as páginas de exemplo")
    p.add_argument("--open-url", metavar="URL", help="abre uma URL no navegador interno")
    args = p.parse_args()
    if args.cli or args.crawl or args.load_samples:
        return run_cli(args)
    return run_gui(args)


if __name__ == "__main__":
    raise SystemExit(main())
