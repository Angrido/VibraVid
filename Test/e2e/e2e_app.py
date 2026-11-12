# 12.11.26
# ruff: noqa: E402

import atexit
import importlib
import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

from playwright import sync_api

ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT, ROOT / "GUI"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

DB_DIR = tempfile.mkdtemp(prefix="vibravid_e2e_")
atexit.register(shutil.rmtree, DB_DIR, ignore_errors=True)
os.environ.setdefault("DJANGO_DB_DIR", DB_DIR)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "webgui.settings")

import django

django.setup()

from django.core.management import call_command
from django.test.testcases import LiveServerThread
from searchapp.api import get_available_sites
from searchapp.api.base import Entries, Episode, Season

from VibraVid.core.ui.tracker import download_tracker
from VibraVid.provider.tmdb import tmdb_client

DEVICES = {
    "desktop": {"viewport": {"width": 1440, "height": 900}},
    "mobile": {"viewport": {"width": 390, "height": 844}, "is_mobile": True, "has_touch": True, "device_scale_factor": 2},
}
OFFLINE_STUBS = {
    "/api/version/check/": {"update_available": False},
    "/api/site-status/": {"sites": []},
    "/api/resolve-tmdb-posters/": {"posters": {}, "episode_info": {}},
}

SEARCH_RESULTS = [
    Entries(name="Night Harbor", type="film", year=2023, slug="night-harbor", id=1),
    Entries(name="Glass Orchard", type="tv", year=2021, slug="glass-orchard", id=2),
    Entries(name="Paper Comets", type="tv", year=2019, slug="paper-comets", id=3),
]
SEASONS = [
    Season(number=1, episodes=[Episode(number=n, name=f"Chapter {n}") for n in range(1, 7)]),
    Season(number=2, episodes=[Episode(number=n, name=f"Return {n}") for n in range(1, 5)]),
]
ACTIVE_DOWNLOAD = {
    "id": "dl-1", "title": "Night Harbor", "site": "streamingcommunity", "type": "Film",
    "status": "Downloading", "progress": 42.0, "speed": "8.4 MB/s", "size": "1.2 GB / 2.9 GB",
    "start_time": 0, "tasks": {},
}


class FakeProvider:
    search_warnings: list = []

    def search(self, query):
        return list(SEARCH_RESULTS)

    def get_series_metadata(self, media_item):
        return list(SEASONS)


@pytest.fixture(scope="session")
def live_url():
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
        call_command("migrate", verbosity=0, interactive=False)
    server = LiveServerThread("127.0.0.1", lambda app: app, port=0)
    server.daemon = True
    server.start()
    server.is_ready.wait()
    if server.error:
        raise server.error
    yield f"http://127.0.0.1:{server.port}"
    server.terminate()


@pytest.fixture(autouse=True)
def offline_app(monkeypatch):
    monkeypatch.delenv("VIBRAVID_USERNAME", raising=False)
    monkeypatch.delenv("VIBRAVID_PASSWORD", raising=False)
    search_view = importlib.import_module("searchapp.views.search")
    series_view = importlib.import_module("searchapp.views.series")

    monkeypatch.setattr(tmdb_client, "_api_key", "")
    monkeypatch.setattr(search_view, "get_api", lambda site: FakeProvider())
    monkeypatch.setattr(series_view, "get_api", lambda site: FakeProvider())
    monkeypatch.setattr(download_tracker, "get_active_downloads", lambda: [])
    monkeypatch.setattr(download_tracker, "get_history", lambda: [])


@pytest.fixture
def active_download(monkeypatch):
    monkeypatch.setattr(download_tracker, "get_active_downloads", lambda: [dict(ACTIVE_DOWNLOAD)])


@pytest.fixture(scope="session")
def site_name():
    return get_available_sites()[0]


@pytest.fixture(scope="session")
def browser():
    with sync_api.sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        yield browser
        browser.close()


def _stub_network(route, live_url):
    url = route.request.url
    if not url.startswith(live_url):
        route.abort()
        return
    path = url[len(live_url):].split("?")[0]
    if path in OFFLINE_STUBS:
        route.fulfill(json=OFFLINE_STUBS[path])
        return
    route.continue_()


@pytest.fixture
def open_context(browser, live_url):
    contexts = []

    def open_one(device, **options):
        context = browser.new_context(base_url=live_url, **DEVICES[device], **options)
        context.route("**/*", lambda route: _stub_network(route, live_url))
        contexts.append(context)
        return context

    yield open_one
    for context in contexts:
        context.close()


@pytest.fixture(params=sorted(DEVICES))
def device(request):
    return request.param


@pytest.fixture
def page(open_context, device):
    page = open_context(device).new_page()
    page.errors = []
    page.on("pageerror", lambda error: page.errors.append(str(error)))
    return page
