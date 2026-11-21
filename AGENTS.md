# VibraVid — agent guide

Python media downloader (HLS/DASH/ISM/MP4, Widevine/PlayReady) with four front-ends sharing one core:
CLI, Textual TUI, Django web GUI (+ Sonarr/Radarr "ARR" integration), Telegram bot. Python >=3.10, CI on 3.13.

## Map

| Path | What lives there |
|---|---|
| `VibraVid/cli/` | argparse entry: `bootstrap.py` (`vibravid` script, `manual.py`), `command/` |
| `VibraVid/services/<site>/` | one package per site, auto-discovered. Read `VibraVid/services/AGENTS.md` before editing |
| `VibraVid/services/_base/` | shared service plumbing (loader, search, TV/season managers, output paths) |
| `VibraVid/core/velora/` | in-house segment downloader (VOD, live, decrypt pipeline) |
| `VibraVid/core/{downloader,manifest,drm,decryptor,muxing}/` | per-format download, MPD/HLS parsing, CDM/licence, decryption, ffmpeg muxing |
| `VibraVid/core/ui/`, `VibraVid/core/utils/selector.py` | progress bars, track selection |
| `VibraVid/tui/` | Textual app (`python tui.py`) |
| `VibraVid/remote/` | remote-CDM / licence relay client + server |
| `VibraVid/provider/`, `VibraVid/player/` | TMDB/TVDB/IMDB metadata, embedded-player extractors |
| `VibraVid/setup/` | external binaries (ffmpeg, mkvtoolnix, ...) discovery/download |
| `VibraVid/utils/` | `config.py` (reads `Conf/*.toml`), `http_client.py`, `vault/` (key cache), `hooks.py` |
| `GUI/` | Django project. Read `GUI/AGENTS.md` before editing |
| `docker/`, `docker/telegram_bot/` | container entrypoints, Telegram bot |
| `Conf/config.toml`, `Conf/login.toml` | shipped defaults (copied into the wheel). Keep them empty templates |
| `Test/` | pytest, one folder per area; `Test/e2e` = Playwright GUI tests |

## Commands

```bash
pip install -r requirements.txt -r GUI/requirements.txt pytest anyio   # dev setup
ruff check .                         # lint (line length 120; Test/ excluded)
python -m pytest -q Test/<Area>      # run the area you touched; full suite: python -m pytest -q
python -m pytest -q Test/e2e         # needs `pip install playwright && playwright install chromium`; runs only when targeted by path
python manual.py ...                 # CLI     | python tui.py  → TUI
python GUI/manage.py runserver       # web GUI
```

Muxing/retag tests need `ffmpeg`/`ffprobe`/`mkvpropedit` on PATH. Tests never download binaries
(`Test/conftest.py`); set `VIBRAVID_TEST_ALLOW_DOWNLOAD=1` only if you mean it.

## Conventions

- New `.py` files start with a creation-date comment `# DD.MM.YY` (e.g. `# 21.11.26`), like every existing file.
- Commit subject `[Area] Verb ...` (`[GUI]`, `[Velora]`, `[ARR]`, `[Docs]`, `[Test]`, `[CI]`...). The verb drives the
  automatic version bump: `Add/Introduce/Implement/Support/Allow/Enable/New` = minor, `BREAKING` = major, else patch.
- A commit written by an agent ends with `Co-Authored-By: Lucio Gigliofiorito <lucio.g95@outlook.com>` (the
  maintainer), next to the agent's own attribution line.
- Never edit the version by hand (`pyproject.toml`, `VibraVid/utils/upload/version.py`): CI bumps it on `main`.
- Comments and docstrings explain *why*; user-facing docs live in `.github/MkDoc/docs/` and must follow behaviour changes.

## Do not touch / do not read

- Secrets and local state: `.env`, `Conf/login.toml` with real values, `Conf/domains.json`, `Conf/remote.json`,
  `GUI/.django_secret_key`, `GUI/db.sqlite3`, `.cache/`, `Video/`, `data/`.
- Generated: `GUI/*/migrations/` (create with `makemigrations`, never hand-edit old ones).
- Binary/noise, skip when searching: `.github/MkDoc/docs/assets/`, `GUI/searchapp/static/searchapp/fonts/`,
  `Test/*/fixtures/`, `.agentsroom/` (tooling, not source).

## Docs on demand (read only when the task needs it)

| Task | Read |
|---|---|
| Add/modify a site | `.github/MkDoc/docs/add-service.md` |
| Config keys (`config.toml`) | `.github/MkDoc/docs/configuration.md` (large: grep the key) |
| CLI flags | `.github/MkDoc/docs/cli.md` |
| ARR / Sonarr / Radarr | `.github/MkDoc/docs/arr.md` |
| GUI visual work | `design-system/MASTER.md` |
| Agent plugins and skills (Claude Code) | `.github/CONTRIBUTING.md`, section "Working with AI coding agents" |
| Docker, NAS, Telegram, remote CDM, hooks, vault, login | matching file in `.github/MkDoc/docs/` |
