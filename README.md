# M-Search+

An open-source search engine of your own that runs on your computer: **crawler**, **indexer**, **BM25F ranking**, **local SQLite database**, **offline mode**, and a **built-in tabbed browser** (Python + PyQt6).

> **No third-party search API** (Google, Bing, SerpAPI, Brave, DuckDuckGo…) is used. Your queries never leave your computer: the index is local.

It is part of a set with [JARVIS](https://github.com/migueljhonatadeaguiar1-cloud/jarvis), which can query the M-Search+ index by voice and text, but it works completely on its own.

> The sample pages and the UI are in Brazilian Portuguese; the search itself works with any language.

## Features

- Polite crawler: honors `robots.txt` (including `Crawl-delay`), `noindex`/`nofollow`, a minimum interval per domain, and blocks local/private networks by default.
- SQLite inverted index, with deduplication by URL and by content hash.
- BM25 ranking with weighted fields (title, headings, URL, body), bonuses, and a score explanation in the interface.
- Query syntax: terms, `"exact phrase"`, `-exclusion`, and `site:domain.com`; ignores accents and letter case.
- **Offline mode:** searches only the local index, imported files (`.html`/`.md`/`.txt`), bookmarks, and fully saved pages (HTML + CSS/JS/images).
- **Built-in browser (Qt WebEngine):** tabs, an address bar that also searches, controlled downloads, a PDF viewer.
- **Private by default:** no account, no cookies, no history, no analytics, no ads.

## Requirements

- Python 3.10 or later
- `PyQt6` and `PyQt6-WebEngine` (the interface). The search engine itself uses only the standard library.

## Install and use

```bash
git clone https://github.com/migueljhonatadeaguiar1-cloud/msearch-plus.git
cd msearch-plus

python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

python3 main.py                    # opens the interface
```

On first use, click **Carregar páginas de exemplo** (load sample pages; works without internet) and search for "pitágoras" or "juros compostos". To index real sites, use **Indexar** (index), enter the URLs, and click *Iniciar indexação* (start indexing).

### Command line (no interface)

```bash
python3 main.py --load-samples --cli "teorema de pitágoras"
python3 main.py --crawl https://example.com --depth 1 --max-pages 50 --cli "example"
python3 main.py --open-url https://example.com     # opens the URL in the built-in browser
python3 main.py --data-dir ./my-data --cli "python"
```

Tests (34 tests, no network):

```bash
python3 -m unittest discover -s tests -v
```

### Where data is stored

| System | Folder |
|---|---|
| Windows | `%APPDATA%\SearchPlus` |
| Linux | `~/.local/share/SearchPlus` |
| macOS | `~/Library/Application Support/SearchPlus` |

Change it with the `SEARCH_PLUS_HOME` environment variable or the `--data-dir` option.

## Query syntax

| Query | Effect |
|---|---|
| `python lists` | prefers documents containing all terms |
| `"pythagorean theorem"` | exact phrase |
| `-java` | excludes documents containing the term |
| `site:example.com` | restricts to a domain |

## Architecture

```text
ui/ (PyQt6 + ui/browser/ WebEngine) ──► core/service.py   SearchPlusService (single entry point)
                  ├─ search/    query · ranking · snippet · engine
                  ├─ crawler/   http · robots · parser · urls · crawler
                  ├─ index/     tokenizer · indexer
                  ├─ database/  interfaces.py (IndexStore) · database.py (SQLite)
                  ├─ offline/   connectivity · bookmarks · page_saver · page_library
                  └─ privacy/   policy + data erasure
```

- **Search:** text → `parse_query` → tokenization → postings in the index → BM25F → filters (phrase/exclusion/site) → snippet.
- **Indexing:** URL → `robots.txt` → recently cached? → per-domain wait → HTTP → parser → indexer → new links enter the queue.
- The engine depends only on the `database/interfaces.py::IndexStore` contract; you can swap SQLite for another store without touching ranking, the engine, or the UI.

## How ranking works

For each document containing at least one query term:

1. **BM25 with weighted fields:** `wtf = 5·title + 3·headings + 2·url + 1·body`, with `k1 = 1.2` and `b = 0.75`.
2. **Coverage:** the text score is multiplied by `(terms_found / query_terms)²`.
3. **Bonuses** (`×(1 + sum)`): all terms in the title (+30%), the whole phrase in the title (+25%) or in the text (+15%), bookmarked (+15%), and inbound links (up to +20%).
4. **Penalty:** pages with fewer than 30 useful words get ×0.8.

The displayed relevance (%) is relative to the best result for the query, not an absolute grade. All weights are in `search/ranking.py::RankingParams`.

## Built-in browser and security

Clicking a result opens the page in a new tab **inside M-Search+**, using Qt's `QWebEngineView` (no Selenium and no external browser).

| Risk | Handling |
|---|---|
| Local files | `file://` is never loaded; local files open as an isolated copy |
| Permissions | camera, microphone, location, notifications, and clipboard are always denied |
| Pop-ups | blocked without a user gesture |
| Insecure content | mixed content blocked; invalid certificate = page does not load |
| Schemes | only `http(s)` and `searchplus-offline`; `javascript:`, `data:`, `ftp:`, etc. are refused |
| Downloads | fixed folder, sanitized name, warning for executables, nothing opens automatically |

## Offline mode

- **Save offline** downloads the page with its resources (CSS, JS, images, fonts, media) and rewrites the paths. Limits: 300 resources, 15 MB per file, 60 MB per page.
- Saved copies open through the custom `searchplus-offline://` scheme in the same built-in browser, with a per-page isolated origin. http(s) requests are **blocked**; nothing is faked, and the notice bar tells you what is unavailable offline.
- Limitation: it saves the HTML as delivered by the server (not the DOM after JavaScript runs).

## Privacy: what the app does and what it does not guarantee

The app uses no account, profile, cookies, ads, or fingerprinting; history is off by default and everything can be erased under *Configurações → Privacidade* (Settings → Privacy). Still, absolute anonymity does not exist:

- Sites visited by the crawler see your IP, the time, the pages requested, and the M-Search+ User-Agent.
- Your network/ISP and DNS resolver see the domains accessed.
- In automatic mode, the connectivity check makes a short TCP connection (no data) to `1.1.1.1:53`, configurable in `config/settings.py`. Force Online/Offline to avoid it.
- The local database is **not encrypted**.

## JARVIS integration

JARVIS uses M-Search+ through the CLI (`main.py --cli`) and opens URLs with `--open-url`. For it to find M-Search+, keep the folders side by side (`jarvis/` and `msearch-plus/`) or set `SEARCH_PLUS_DIR` in JARVIS' `.env`.

## Known limitations (V1)

- Exact-term search with light stemming: no synonyms, spell correction, or semantics.
- Exact phrases are checked by reading the candidates' text (fine for thousands of pages).
- No JavaScript rendering in the crawler.
- Single-threaded crawler, on purpose, to be polite to sites.

## Roadmap

- **V2:** own API (e.g., FastAPI) exposing `SearchPlusService` (`GET /search`, `POST /crawl`, `GET /stats`).
- **V3:** web frontend consuming the API.
- **V4:** new `IndexStore` (PostgreSQL, OpenSearch, Tantivy…), a persistent crawl queue, and multiple workers.

## License

Choose a license before publishing (for example, by adding a `LICENSE` file).
