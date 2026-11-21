# GUI (Django) — scoped rules

Project `webgui/` (settings, urls); app `searchapp/` (everything user-facing); `scheduleapp/` (scheduled downloads).

| Where | What |
|---|---|
| `searchapp/views/` | page views (`cinema.py`, `download.py`, `arr.py`, `auth.py`, ...) |
| `searchapp/api/<site>.py` | per-site adapter over the CLI service, subclass of `GenericStreamingAPI` (`api/generic.py`), auto-discovered |
| `searchapp/arr/` | Sonarr/Radarr/Seerr clients and the ARR download pipeline (`downloader_service.py`, `arr_service.py`: big files, read by symbol) |
| `searchapp/templates/searchapp/`, `static/searchapp/` | `cinema_*.html` pages, `cinema.css` (all shared styles), page JS |
| `searchapp/i18n/it.json` | Italian catalog, keyed by the English source string |

Rules:
- Visual work: follow `design-system/MASTER.md` (`cn-`/`--cn-` names are a contract, tokens only, no raw hex,
  no inline `style=""`, one coral CTA per screen).
- Every new or changed user-visible English string gets an entry in `searchapp/i18n/it.json` (keep `{placeholders}`).
  Provider content (titles, synopses) is never translated. Checked by `Test/GUI/test_gui_i18n.py`.
- Model change → `python GUI/manage.py makemigrations`; never hand-edit existing migrations.
- Never echo exception text or foreign host names back in responses (see recent `[GUI]` security commits).
- Tests: `python -m pytest -q Test/GUI`; layout/interaction changes also `Test/e2e` (Playwright, desktop + phone).
