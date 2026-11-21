# Services — scoped rules

One package per site, auto-discovered by `_base/site_loader.py`. Full walkthrough (DRM patterns, ads, chapters,
batch, live, TMDB search, music): `.github/MkDoc/docs/add-service.md`. Read only the section you need.

Contract of a service package:
- `__init__.py` must define `indice` (list position) and `_useFor` (`Anime`, `Film_Serie`, `Live`, `Serie`, `Song`, `Tor`).
- Usual files: `client.py` (auth/session), `scrapper.py` (metadata, `GetSerieInfo`), `downloader.py` (builds the download).
- Optional CLI flags: `register_cli_args(parser)`; values land in `context_tracker.site_options`.
- Credentials: `config_manager.login.get("<site>", "<key>", default="")` (reads `Conf/login.toml`); add the empty
  key to `Conf/login.toml`. Never hard-code tokens or cookies.
- A GUI adapter lives in `GUI/searchapp/api/<site>.py`; folder names that are not identifiers need
  `resolve_service_submodule()`.
- Copy the structure of the closest existing site (e.g. `la7`, `raiplay` for TV; `crunchyroll` for anime with DRM;
  `youtube_music` for music) instead of starting from scratch. Shared logic belongs in `_base/`, not in one site.
- Hide a work-in-progress site with `hidden_services` in `config.toml`.
