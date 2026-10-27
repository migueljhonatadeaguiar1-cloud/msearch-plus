"""Privacidade: política em linguagem clara + apagamento de dados locais."""
from __future__ import annotations

import shutil

from config.settings import AppPaths, Settings
from database.database import Database

PRIVACY_NOTICE_HTML = """
<h3>Princípios do M-Search+</h3>
<ul>
<li><b>Suas buscas ficam no seu computador.</b> O índice é local; a consulta não é enviada a nenhum serviço de busca.</li>
<li><b>Sem perfil, sem anúncios, sem rastreamento, sem fingerprinting.</b> O M-Search+ não cria perfil de usuário nem usa cookies.</li>
<li><b>Histórico:</b> desligado por padrão. Se ativado, fica apenas neste computador e pode ser apagado a qualquer momento.</li>
<li><b>Tudo é local:</b> índice, cache e configurações ficam na pasta de dados do aplicativo. Você pode apagar tudo aqui.</li>
</ul>
<h3>O que ainda pode ser observado (não há anonimato absoluto)</h3>
<ul>
<li><b>Ao indexar (crawler):</b> cada site visitado vê seu endereço IP, o horário e o User-Agent fixo do M-Search+
(<i>SearchPlusBot</i>), além das páginas pedidas. O servidor guarda isso nos logs dele.</li>
<li><b>Sua rede/provedor (ISP), Wi-Fi ou empresa</b> podem ver os domínios acessados (via DNS e SNI do TLS), mesmo com HTTPS;
o conteúdo das páginas HTTPS fica cifrado, mas o destino não.</li>
<li><b>Seu resolvedor DNS</b> vê os nomes de domínio consultados.</li>
<li><b>Verificação de conexão:</b> no modo automático, o app abre uma conexão TCP curta com o endereço configurado
(padrão 1.1.1.1:53), sem enviar dados. Esse servidor pode ver seu IP. Para evitar, force o modo Online ou Offline nas Configurações.</li>
<li><b>Navegador interno:</b> os sites abertos dentro do M-Search+ veem seu IP, o horário e o User-Agent do motor
Chromium embutido (QtWebEngine), que identifica o Chromium/Qt usado. Os recursos de conta e sincronização do Google
Chrome não fazem parte do QtWebEngine, mas os sites podem rastrear você pelo conteúdo que carregam. O M-Search+ bloqueia
cookies de terceiros, uma lista pequena de rastreadores conhecidos e não grava cookies em disco; o cache em disco e o
histórico de navegação ficam desligados por padrão e podem ser apagados em “Limpar dados de navegação”.</li>
<li><b>“Abrir no navegador externo”</b> (opcional, no menu de contexto): a partir daí valem as regras do seu navegador.
A “Cópia salva” abre sem scripts e sem requisições externas.</li>
<li><b>Seu computador:</b> quem tem acesso a ele (ou ao backup) pode ler os dados locais; o banco não é criptografado.</li>
</ul>
<p>O M-Search+ respeita <code>robots.txt</code> e limites de requisição, mas isso não esconde sua identidade de rede.
Para maior proteção, use VPN/Tor por sua conta e avalie os riscos.</p>
"""


class PrivacyManager:
    def __init__(self, db: Database, paths: AppPaths, settings: Settings):
        self.db, self.paths, self.settings = db, paths, settings

    @property
    def notice_html(self) -> str:
        return PRIVACY_NOTICE_HTML

    def record_search(self, query: str) -> None:
        if self.settings.save_search_history and query.strip():
            self.db.add_history(query.strip())

    def history(self, limit: int = 50) -> list[tuple[str, float]]:
        return self.db.list_history(limit)

    def clear_history(self) -> None:
        self.db.clear_history()

    def clear_browse_history(self) -> None:
        self.db.clear_browse_history()

    def schedule_web_wipe(self) -> None:
        """Pede a remoção dos dados em disco do WebEngine na próxima abertura (arquivos podem estar em uso)."""
        try:
            self.paths.web_wipe_flag.write_text("1", encoding="utf-8")
        except OSError:
            pass

    def clear_cache(self) -> None:
        self.db.clear_cache()
        self._clear_offline_view()

    def clear_index(self) -> None:
        self.db.clear_index()

    def clear_saved_pages(self) -> None:
        shutil.rmtree(self.paths.saved_pages_dir, ignore_errors=True)
        self.paths.saved_pages_dir.mkdir(parents=True, exist_ok=True)
        self.db.saved_pages_clear()

    def clear_browsing_history(self) -> None:
        self.db.clear_visits()

    def clear_all(self) -> None:
        self.db.clear_all()
        self.clear_saved_pages()
        self._clear_offline_view()
        self.schedule_web_wipe()

    def on_exit(self) -> None:
        if self.settings.clear_data_on_exit:
            self.clear_all()

    def _clear_offline_view(self) -> None:
        shutil.rmtree(self.paths.offline_view_dir, ignore_errors=True)
        self.paths.offline_view_dir.mkdir(parents=True, exist_ok=True)


def run_scheduled_web_wipe(paths: AppPaths) -> bool:
    """Chamada na inicialização, antes de criar o perfil do WebEngine."""
    if not paths.web_wipe_flag.exists():
        return False
    for d in (paths.web_cache_dir, paths.web_data_dir):
        shutil.rmtree(d, ignore_errors=True)
    try:
        paths.web_wipe_flag.unlink()
    except OSError:
        pass
    return True
