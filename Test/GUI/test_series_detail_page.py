# 21.11.26
# ruff: noqa: E402

"""The series page is reached by Post/Redirect/Get, so Back, Reload and the language switch never resubmit a form."""

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
GUI_DIR = ROOT / "GUI"
for path in (ROOT, GUI_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "webgui.settings")

import django

django.setup()

import pytest
from django.core.management import call_command
from django.test import Client

from searchapp.views import series

PAYLOAD = json.dumps({"name": "Glass Orchard", "type": "tv", "slug": "glass-orchard", "tmdb_id": 5, "secret_token": "x" * 50})


@pytest.fixture
def client(monkeypatch):
    call_command("migrate", verbosity=0)
    monkeypatch.setattr(series, "get_api", lambda site: SimpleNamespace(get_series_metadata=lambda item: []))
    monkeypatch.setattr(series.tmdb_client, "get_backdrop_url", lambda *a, **k: None)
    return Client(HTTP_HOST="localhost")


def test_opening_a_title_redirects_to_a_short_get_url_that_renders_the_page(client):
    response = client.post("/series-detail/", {"source_alias": "streamingcommunity", "item_payload": PAYLOAD})

    assert response.status_code == 302
    assert response["Location"].startswith("/series-detail/?page=")
    assert "secret_token" not in response["Location"] and len(response["Location"]) < 60

    page = client.get(response["Location"])
    assert page.status_code == 200
    assert "Glass Orchard" in page.content.decode()
    assert client.get(response["Location"]).status_code == 200  # reload


def test_an_unknown_page_key_goes_back_to_search_with_a_message(client):
    response = client.get("/series-detail/?page=nope", follow=True)

    assert response.redirect_chain[-1][0] == "/"
    assert "This page has expired. Open the title again from the search results." in response.content.decode()


def test_another_browser_session_cannot_open_the_page_key(client):
    location = client.post("/series-detail/", {"source_alias": "streamingcommunity", "item_payload": PAYLOAD})["Location"]

    assert Client(HTTP_HOST="localhost").get(location).status_code == 302
