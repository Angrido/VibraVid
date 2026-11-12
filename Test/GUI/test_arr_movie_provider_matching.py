# 12.11.26
# ruff: noqa: E402

import os
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GUI_DIR = ROOT / "GUI"
for path in (ROOT, GUI_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "webgui.settings")

import django

django.setup()

import pytest

from searchapp.api.base import Entries
from searchapp.arr.downloader_service import ArrDownloaderService

MOVIE_TITLE = "Bleach: Thousand-Year Blood War - The Calamity"


class FakeProvider:
    def __init__(self, results, resolve=None):
        self.results = results
        self.resolve = resolve

    def search(self, query):
        return self.results

    def resolve_tmdb_id(self, item):
        return self.resolve(item) if self.resolve else None


@pytest.fixture
def service(monkeypatch):
    monkeypatch.setattr(ArrDownloaderService, "_strict_tmdb_matching_enabled", classmethod(lambda cls: True))
    monkeypatch.setattr(ArrDownloaderService, "_tmdb_client", classmethod(lambda cls: None))
    return ArrDownloaderService(None, None)


def _use_provider(monkeypatch, provider):
    monkeypatch.setattr("searchapp.api.get_api", lambda name: provider)


def _anime(name, episodes, type_="TV"):
    return Entries(id=hash(name) % 1000, name=name, type=type_, raw_data={"episodes_count": episodes})


def test_single_episode_anime_entry_with_the_exact_title_satisfies_a_movie(service, monkeypatch):
    _use_provider(monkeypatch, FakeProvider([_anime("Bleach", 366), _anime(f"{MOVIE_TITLE} (ITA)", 1)]))

    payload = service._search_and_build_payload(MOVIE_TITLE, "animeunity", tmdb_id=1669841, media_type="movie")

    assert payload["name"] == f"{MOVIE_TITLE} (ITA)"
    assert payload["is_movie"] is True and payload["tmdb_id"] == "1669841"


def test_multi_episode_series_with_the_movie_title_is_reported_not_downloaded(service, monkeypatch):
    _use_provider(monkeypatch, FakeProvider([_anime(MOVIE_TITLE, 13)]))

    payload = service._search_and_build_payload(MOVIE_TITLE, "animeunity", tmdb_id=1669841, media_type="movie")

    assert payload is None
    assert service.series_only_match == {"provider": "animeunity", "match": MOVIE_TITLE}


def test_series_with_a_different_title_is_not_reported_as_the_movie(service, monkeypatch):
    _use_provider(monkeypatch, FakeProvider([_anime("Bleach", 366)]))

    assert service._search_and_build_payload(MOVIE_TITLE, "animeunity", tmdb_id=1669841, media_type="movie") is None
    assert service.series_only_match is None


def test_provider_identity_lookups_run_concurrently(service, monkeypatch):
    movies = [Entries(id=i, name=f"Movie {i}", type="movie") for i in range(3)]
    everyone_waiting = threading.Barrier(len(movies), timeout=5)

    def slow_detail_lookup(item):
        everyone_waiting.wait()
        return "1669841" if item.id == 2 else str(100 + item.id)

    _use_provider(monkeypatch, FakeProvider(movies, slow_detail_lookup))

    payload = service._search_and_build_payload("Movie", "streamingcommunity", tmdb_id=1669841, media_type="movie")

    assert payload["name"] == "Movie 2"


def test_earliest_provider_result_wins_when_several_match(service, monkeypatch):
    movies = [Entries(id=i, name=f"Movie {i}", type="movie") for i in range(4)]
    _use_provider(monkeypatch, FakeProvider(movies, lambda item: "1669841" if item.id >= 1 else "5"))

    payload = service._search_and_build_payload("Movie", "streamingcommunity", tmdb_id=1669841, media_type="movie")

    assert payload["name"] == "Movie 1"


def test_movies_released_years_apart_skip_the_identity_lookup(service, monkeypatch):
    looked_up = []
    movies = [
        Entries(id=1, name="K2 - L'ultima sfida", type="movie", year=1991),
        Entries(id=2, name="L'ultima sfida", type="movie", year=2024),
        Entries(id=3, name="L'ultima sfida", type="movie"),
    ]
    _use_provider(monkeypatch, FakeProvider(movies, lambda item: looked_up.append(item.id) or "7"))

    payload = service._search_and_build_payload(
        "L'ultima sfida", "streamingcommunity", tmdb_id=1443449, expected_year=2025, media_type="movie"
    )

    assert payload is None
    assert looked_up == [2, 3]


def test_locate_remembers_every_provider_it_searched(service, monkeypatch):
    monkeypatch.setattr(service, "_provider_order", lambda primary: ["streamingcommunity", "raiplay"])
    monkeypatch.setattr(service, "_resolve_request_tmdb_id", lambda item, media_type: 1590097)
    monkeypatch.setattr(service, "_resolve_radarr_title", lambda title, movie_id, tmdb_id: [title])
    _use_provider(monkeypatch, FakeProvider([]))

    payload, _ = service.locate({"content_type": "movie", "id": 5, "title": "Afterlight", "year": 2025})

    assert payload is None
    assert service.searched_providers == ["streamingcommunity", "raiplay"]
