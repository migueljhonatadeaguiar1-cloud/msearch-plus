"""Configurações e caminhos do M-Search+ (tudo local, salvo em JSON)."""
from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

APP_NAME = "M-Search+"
BOT_TOKEN = "SearchPlusBot"
VERSION = "1.0.0"


def default_data_dir() -> Path:
    """Pasta de dados do usuário. Pode ser trocada com SEARCH_PLUS_HOME."""
    env = os.environ.get("SEARCH_PLUS_HOME")
    if env:
        return Path(env)
    if sys.platform.startswith("win"):
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / "SearchPlus"


@dataclass
class AppPaths:
    root: Path

    @property
    def db_file(self) -> Path:
        return self.root / "searchplus.db"

    @property
    def settings_file(self) -> Path:
        return self.root / "settings.json"

    @property
    def offline_view_dir(self) -> Path:
        return self.root / "offline_view"

    @property
    def saved_pages_dir(self) -> Path:
        """Páginas completas salvas para uso offline (HTML + CSS + JS + imagens + fontes)."""
        return self.root / "conteudo_offline"

    @property
    def webengine_dir(self) -> Path:
        return self.root / "webengine"

    @property
    def web_cache_dir(self) -> Path:
        return self.root / "webcache"

    @property
    def web_data_dir(self) -> Path:
        return self.root / "webdata"

    @property
    def web_wipe_flag(self) -> Path:
        return self.root / "wipe_web_data.flag"

    def ensure(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.offline_view_dir.mkdir(parents=True, exist_ok=True)
        self.saved_pages_dir.mkdir(parents=True, exist_ok=True)


@dataclass
class Settings:
    # --- geral ---
    theme: str = "light"                    # light | dark
    results_per_page: int = 10
    # --- conectividade ---
    connectivity_mode: str = "auto"         # auto | online (forçado) | offline (forçado)
    connectivity_check_host: str = "1.1.1.1"  # só abre uma conexão TCP; nenhum dado é enviado
    connectivity_check_port: int = 53
    connectivity_interval_s: int = 20
    # --- crawler ---
    user_agent: str = f"{BOT_TOKEN}/{VERSION} (crawler local e educado; respeita robots.txt)"
    request_delay_s: float = 1.5            # intervalo mínimo por domínio
    timeout_s: float = 10.0
    max_redirects: int = 5
    max_page_bytes: int = 2_000_000
    max_pages_per_run: int = 50
    max_depth: int = 1
    follow_external_links: bool = False
    allow_local_network: bool = False       # bloqueia 127.0.0.1, 192.168.x.x etc. por padrão
    cache_enabled: bool = True
    recrawl_after_hours: int = 24
    seeds: list[str] = field(default_factory=list)
    # --- navegador interno ---
    browser_javascript: bool = True
    browser_allow_cookies: bool = False     # cookies de terceiros NUNCA são aceitos
    browser_store_history: bool = False     # histórico de navegação (local), desligado por padrão
    browser_keep_cache: bool = False        # cache em disco; desligado = cache só em memória
    download_dir: str = ""                  # vazio = pasta Downloads do usuário
    # --- privacidade ---
    save_search_history: bool = False       # histórico local, desligado por padrão
    clear_data_on_exit: bool = False
    # --- navegador interno ---
    open_in_internal_browser: bool = True
    allow_cookies: bool = True              # só da sessão e do próprio site; nunca gravados em disco
    save_browsing_history: bool = False     # histórico de navegação local, desligado por padrão
    keep_web_cache: bool = False            # cache em disco do WebEngine (desligado = só memória)
    javascript_enabled: bool = True
    block_trackers: bool = True
    download_dir: str = ""                  # vazio = ~/Downloads/SearchPlus


def load_settings(path: Path) -> Settings:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        known = {f.name for f in fields(Settings)}
        return Settings(**{k: v for k, v in data.items() if k in known})
    except (OSError, ValueError, TypeError):
        return Settings()


def save_settings(settings: Settings, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(settings), indent=2, ensure_ascii=False), encoding="utf-8")
