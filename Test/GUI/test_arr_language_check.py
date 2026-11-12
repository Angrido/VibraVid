# 12.11.26
# ruff: noqa: E402

import json
import os
import sys
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
from django.core.management import call_command
from django.test import Client

from searchapp.arr import language_check, library_service, manual_service
from searchapp.models import ArrLanguageCheck

SERIES = {"id": 7, "title": "Zeta Show", "path": "/tv/zeta", "tags": [], "year": 2020, "tmdbId": 70}
AUDIO = {
    "movie:31": ["en"],
    "episode:701": ["it", "ja"],
    "episode:702": ["ja"],
}


class FakeSonarr:
    label = "Sonarr"

    def is_available(self):
        return True

    def get_tags_map(self):
        return {}

    def get_all_missing(self):
        return [
            {"id": 701, "title": "One", "seasonNumber": 1, "episodeNumber": 1, "series": SERIES},
            {"id": 702, "title": "Two", "seasonNumber": 1, "episodeNumber": 2, "series": SERIES},
        ]

    def get_series(self):
        return [{"id": 7, "title": "Zeta Show", "monitored": True, "statistics": {"episodeCount": 3, "episodeFileCount": 1}}]


class FakeRadarr:
    label = "Radarr"

    def is_available(self):
        return True

    def get_tags_map(self):
        return {}

    def get_all_missing(self):
        return [{"id": 31, "title": "Alpha Movie", "year": 2021, "path": "/movies/alpha", "tags": [], "tmdbId": 310}]

    def get_movies(self):
        return [{"id": 31, "title": "Alpha Movie", "monitored": True, "hasFile": False, "isAvailable": True}]


class FakeApi:
    def get_available_audio_languages(self, item, season, episode):
        return [{"code": code} for code in AUDIO[item.name]]


class InlineThread:
    def __init__(self, target, args=(), daemon=None, name=None):
        self.target, self.args = target, args

    def start(self):
        self.target(*self.args)


@pytest.fixture(autouse=True)
def db():
    call_command("migrate", verbosity=0)
    ArrLanguageCheck.objects.all().delete()


@pytest.fixture
def arr(monkeypatch):
    clients = (FakeSonarr(), FakeRadarr())
    for module in (language_check, manual_service, library_service):
        monkeypatch.setattr(module, "_load_arr_config", lambda: {"enabled": True})
        monkeypatch.setattr(module, "_build_clients", lambda cfg: clients)

    def find_on_provider(movie_id=None, episode_id=None):
        key = language_check.movie_key(movie_id) if movie_id else language_check.episode_key(episode_id)
        return {"payload": {"name": key, "type": "movie"}, "provider": "streamingcommunity", "season": None, "episode": None}

    monkeypatch.setattr(manual_service, "find_on_provider", find_on_provider)
    monkeypatch.setattr("searchapp.api.get_api", lambda provider: FakeApi())
    monkeypatch.setattr(language_check.threading, "Thread", InlineThread)
    downloads = []
    monkeypatch.setattr(manual_service, "_run_jobs", lambda *args: downloads.append(args))
    return downloads


@pytest.fixture
def client():
    return Client(HTTP_HOST="localhost")


def _verdicts():
    return dict(ArrLanguageCheck.objects.values_list("media_key", "verdict"))


@pytest.mark.parametrize(("name", "supported", "codes", "verdict"), [
    ("Show", True, ["it", "ja"], "available"),
    ("Show", True, ["it-IT"], "available"),
    ("Show", True, ["ja"], "absent"),
    ("Show", True, [], "unknown"),
    ("Show", False, [], "unknown"),
    ("Show (ITA)", False, [], "available"),
])
def test_verdict_looks_for_italian_audio(name, supported, codes, verdict):
    assert language_check.verdict_for(name, supported, codes) == verdict


def test_checking_all_missing_records_every_movie_and_episode_without_downloading(arr):
    assert language_check.start_check() is True

    assert _verdicts() == {"movie:31": "absent", "episode:701": "available", "episode:702": "absent"}
    assert arr == []
    status = language_check.check_status()
    assert status["running"] is False and (status["done"], status["total"]) == (3, 3)
    assert status["titles"]["serie:7"] == {"tone": "warn", "label": "Italian audio", "count": "1/2", "source": {}}
    assert status["titles"]["movie:31"]["tone"] == "bad"


def test_checking_one_series_keeps_other_titles_and_drops_episodes_no_longer_missing(arr):
    language_check.record("movie:99", "movie:99", "available", ["it"], "x")
    language_check.record("episode:700", "serie:7", "absent", [], "x")

    language_check.start_check(movie_ids=set(), series_ids={7})

    assert _verdicts() == {"movie:99": "available", "episode:701": "available", "episode:702": "absent"}


def test_a_provider_error_is_recorded_as_failed_and_the_rest_continues(arr, monkeypatch):
    original = manual_service.find_on_provider

    def flaky(movie_id=None, episode_id=None):
        if movie_id:
            raise ConnectionError("provider down")
        return original(movie_id=movie_id, episode_id=episode_id)

    monkeypatch.setattr(manual_service, "find_on_provider", flaky)

    language_check.start_check()

    assert _verdicts()["movie:31"] == "failed"
    assert _verdicts()["episode:701"] == "available"


def test_a_second_check_is_refused_while_one_is_running(arr):
    language_check._run_lock.acquire()
    try:
        assert language_check.start_check() is False
    finally:
        language_check._run_lock.release()


def test_scheduled_check_runs_without_downloading(arr):
    language_check.run_scheduled_check()

    assert len(_verdicts()) == 3 and arr == []
    assert not language_check._run_lock.locked()


@pytest.mark.parametrize(("raw", "hours"), [(None, 0), (6, 6), ("12", 12), (5, 0), ("x", 0)])
def test_interval_accepts_only_the_offered_choices(monkeypatch, raw, hours):
    monkeypatch.setattr(language_check, "_load_arr_config", lambda: {language_check.INTERVAL_KEY: raw})

    assert language_check.interval_hours() == hours


def test_library_page_shows_the_result_and_a_check_button_on_missing_titles(client, arr):
    language_check.start_check()

    page = " ".join(client.get("/arr/").content.decode().split())

    assert "Check all missing" in page and "Automatic check" in page
    assert 'data-lib-check="series" data-lib-id="7"' in page
    assert 'data-lib-check="movie" data-lib-id="31"' in page
    assert "No Italian audio" in page and '<span class="cn-num">1/2</span>' in page


@pytest.mark.parametrize("body", [{}, {"movie": 1, "series": 2}, {"movie": "1"}, {"scope": "some"}])
def test_start_endpoint_needs_one_title_or_the_whole_library(client, body):
    response = client.post("/api/arr/language-check/", data=json.dumps(body), content_type="application/json")

    assert response.status_code == 400


def test_start_endpoint_checks_one_movie(client, arr):
    response = client.post("/api/arr/language-check/", data=json.dumps({"movie": 31}), content_type="application/json")

    assert response.status_code == 200
    assert _verdicts() == {"movie:31": "absent"}


def test_interval_endpoint_saves_only_offered_choices(client, monkeypatch):
    saved = []
    monkeypatch.setattr(language_check, "set_interval_hours", saved.append)

    bad = client.post("/api/arr/language-check/interval/", data=json.dumps({"hours": 5}), content_type="application/json")
    good = client.post("/api/arr/language-check/interval/", data=json.dumps({"hours": 24}), content_type="application/json")

    assert bad.status_code == 400 and good.status_code == 200
    assert saved == [24]


def test_single_language_check_from_a_title_page_updates_the_library_badge(client, monkeypatch):
    from searchapp.views import download as download_views

    monkeypatch.setattr(manual_service, "find_on_provider", lambda movie_id=None, episode_id=None: {
        "payload": {"name": "Alpha Movie", "type": "movie", "id": 1}, "provider": "streamingcommunity", "season": None, "episode": None,
    })
    monkeypatch.setattr("searchapp.api.get_api", lambda provider: object())
    monkeypatch.setattr(download_views, "track_report", lambda api, item, season, episode, description: {
        "qualities": ["1080p"], "audio_supported": True, "audio_languages": [{"code": "it", "name": "Italian"}],
    })

    client.post("/api/arr/missing/check/", data=json.dumps({"movie": 31}), content_type="application/json")

    assert language_check.title_summaries()["movie:31"]["tone"] == "good"


@pytest.mark.parametrize(("provider", "payload", "url"), [
    ("streamingcommunity", {"id": 12, "slug": "alpha-movie", "provider_language": "en"}, "https://sc.example/en/titles/12-alpha-movie"),
    ("streamingcommunity", {"id": 12, "slug": "alpha-movie"}, "https://sc.example/it/titles/12-alpha-movie"),
    ("animeunity", {"id": 5, "slug": "bleach"}, "https://au.example/anime/5-bleach"),
    ("raiplay", {"url": "https://www.raiplay.it/programmi/alpha"}, "https://www.raiplay.it/programmi/alpha"),
    ("raiplay", {"url": "javascript:alert(1)"}, ""),
    ("raiplay", {"url": "/programmi/alpha"}, ""),
    ("aurora", {"name": "Alpha"}, ""),
    ("raiplay", None, ""),
])
def test_provider_page_url_points_to_the_title_on_the_provider(monkeypatch, provider, payload, url):
    domains = {"streamingcommunity": "https://sc.example/", "animeunity": "https://au.example"}
    monkeypatch.setattr("VibraVid.utils.config_manager.domain.get", lambda site, key: domains[site])
    assert manual_service.provider_page_url(provider, payload) == url


def test_check_remembers_the_provider_page_and_the_library_shows_it(arr, client, monkeypatch):
    original = manual_service.find_on_provider
    monkeypatch.setattr(manual_service, "find_on_provider", lambda movie_id=None, episode_id=None: {
        **original(movie_id, episode_id), "url": "https://sc.example/it/titles/31-alpha",
    })

    assert language_check.start_check() is True

    row = ArrLanguageCheck.objects.get(media_key="movie:31")
    assert row.source_url == "https://sc.example/it/titles/31-alpha"
    summary = language_check.title_summaries()["serie:7"]
    assert summary["source"] == {"url": "https://sc.example/it/titles/31-alpha", "provider": "streamingcommunity"}
    page = client.get("/arr/").content.decode()
    assert 'href="https://sc.example/it/titles/31-alpha"' in page and 'rel="noopener noreferrer"' in page


def test_title_without_a_provider_page_has_no_source(arr):
    assert language_check.start_check() is True

    assert language_check.title_summaries()["movie:31"]["source"] == {}
