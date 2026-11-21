# 21.11.26
# ruff: noqa: E402

"""Watchlist "New" badge: raised by a check, cleared by the user, and new episodes of a new season are reported."""

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

from searchapp.models import WatchlistItem
from searchapp.views import _shared


@pytest.fixture(autouse=True)
def db():
    call_command("migrate", verbosity=0)
    WatchlistItem.objects.all().delete()


def _show(**fields):
    return WatchlistItem.objects.create(
        name="Show", source_alias="streamingcommunity", item_payload=json.dumps({"name": "Show", "type": "tv"}), **fields
    )


def _provider(monkeypatch, *episode_counts):
    seasons = [SimpleNamespace(number=n, episode_count=c) for n, c in enumerate(episode_counts, 1)]
    monkeypatch.setattr(_shared, "get_api", lambda _site: SimpleNamespace(get_series_metadata=lambda _item: seasons))


def test_a_new_short_season_resets_the_episode_count_so_its_next_episodes_are_reported(monkeypatch):
    item = _show(num_seasons=1, last_season_episodes=10)

    _provider(monkeypatch, 10, 1)
    assert _shared._update_single_item(item) is True
    item.refresh_from_db()
    assert (item.num_seasons, item.last_season_episodes, item.has_new_seasons) == (2, 1, True)

    WatchlistItem.objects.filter(pk=item.pk).update(has_new_seasons=False)
    _provider(monkeypatch, 10, 2)
    assert _shared._update_single_item(item) is True
    item.refresh_from_db()
    assert (item.last_season_episodes, item.has_new_episodes) == (2, True)


def test_mark_as_seen_clears_the_new_badge():
    item = _show(num_seasons=2, has_new_seasons=True, has_new_episodes=True)
    client = Client(HTTP_HOST="localhost")

    page = client.get("/watchlist/").content.decode()
    assert "Mark as seen" in page

    response = client.post(f"/watchlist/seen/{item.pk}/")

    assert response.status_code == 302
    item.refresh_from_db()
    assert (item.has_new_seasons, item.has_new_episodes) == (False, False)
    assert "Mark as seen" not in client.get("/watchlist/").content.decode()


def test_mark_as_seen_needs_a_post():
    item = _show(has_new_episodes=True)

    assert Client(HTTP_HOST="localhost").get(f"/watchlist/seen/{item.pk}/").status_code == 405
