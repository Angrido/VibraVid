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

from searchapp.arr import manual_service
from searchapp.models import ArrMediaRequest, ArrProcessingQueue


class FakeSonarr:
    label = "Sonarr"

    def __init__(self, available=True):
        self.available = available

    def is_available(self):
        return self.available

    def get_tags_map(self):
        return {}

    def get_all_missing(self):
        series = {
            "id": 7, "title": "Zeta Show", "path": "/tv/zeta", "tags": [], "year": 2020, "tmdbId": 70,
            "images": [
                {"coverType": "banner", "remoteUrl": "https://img.example/zeta-banner.jpg"},
                {"coverType": "poster", "remoteUrl": "https://img.example/zeta-poster.jpg"},
            ],
        }
        return [
            {"id": 702, "title": "Two", "seasonNumber": 1, "episodeNumber": 2, "series": series},
            {"id": 701, "title": "One", "seasonNumber": 1, "episodeNumber": 1, "series": series},
            {"id": 799, "title": "Special", "seasonNumber": 0, "episodeNumber": 1, "series": series},
        ]


class FakeRadarr:
    label = "Radarr"

    def is_available(self):
        return True

    def get_tags_map(self):
        return {}

    def get_all_missing(self):
        return [{
            "id": 31, "title": "Alpha Movie", "year": 2021, "path": "/movies/alpha", "tags": [], "tmdbId": 310,
            "images": [{"coverType": "poster", "remoteUrl": "javascript:alert(1)"}],
        }]


@pytest.fixture(autouse=True)
def db():
    call_command("migrate", verbosity=0)
    ArrMediaRequest.objects.all().delete()


@pytest.fixture
def arr(monkeypatch):
    clients = {"sonarr": FakeSonarr(), "radarr": FakeRadarr()}
    monkeypatch.setattr(manual_service, "_load_arr_config", lambda: {"enabled": True, "enable_polling": False})
    monkeypatch.setattr(manual_service, "_build_clients", lambda cfg: (clients["sonarr"], clients["radarr"]))
    started = []
    monkeypatch.setattr(manual_service, "_run_jobs", lambda sonarr, radarr, jobs: started.extend(jobs))
    monkeypatch.setattr(manual_service.threading, "Thread", lambda target, args, daemon: type("T", (), {"start": lambda self: target(*args)})())
    return clients, started


def _queue(dedup_key, status):
    request = ArrMediaRequest.objects.create(arr_id=1, arr_source="sonarr", title="x", content_type="serie", status=status)
    ArrProcessingQueue.objects.create(dedup_key=dedup_key, media_request=request)


def test_scan_groups_missing_episodes_and_movies_with_queue_state(arr):
    _queue("sonarr_7_s1_e2", ArrMediaRequest.Status.DOWNLOADING)

    scan = manual_service.scan_missing()

    serie = scan["series"][0]
    episodes = serie["seasons"][0]["episodes"]
    assert [e["episodeNumber"] for e in episodes] == [1, 2]
    assert [e["state"] for e in episodes] == ["", "downloading"]
    assert serie["episode_count"] == 2 and scan["episode_total"] == 2
    assert [m["title"] for m in scan["movies"]] == ["Alpha Movie"]
    assert scan["unreachable"] == [] and scan["polling_active"] is False


def test_scan_reports_an_unreachable_server_and_keeps_the_other(arr):
    clients, _ = arr
    clients["sonarr"].available = False

    scan = manual_service.scan_missing()

    assert scan["unreachable"] == ["Sonarr"]
    assert scan["series"] == [] and len(scan["movies"]) == 1


def test_scan_without_clients_is_not_configured(monkeypatch):
    monkeypatch.setattr(manual_service, "_load_arr_config", lambda: {})
    monkeypatch.setattr(manual_service, "_build_clients", lambda cfg: (None, None))

    scan = manual_service.scan_missing()

    assert scan["configured"] is False and scan["series"] == [] and scan["movies"] == []


def test_only_selected_items_are_queued_and_nothing_else_downloads(arr):
    _, started = arr

    result = manual_service.start_selected_downloads(movie_ids=set(), episode_ids={702, 9999})

    assert result == {"queued": 1, "skipped": 0, "gone": 1}
    assert [(job[2]["id"]) for job in started] == [702]
    request = ArrMediaRequest.objects.get()
    assert (request.episode_number, request.sync_source) == (2, "manual_resync")


def test_selecting_an_item_already_in_the_queue_does_not_download_it_twice(arr):
    _, started = arr
    _queue("radarr_31", ArrMediaRequest.Status.PENDING)

    result = manual_service.start_selected_downloads(movie_ids={31}, episode_ids=set())

    assert result == {"queued": 0, "skipped": 1, "gone": 0}
    assert started == []


@pytest.fixture
def client():
    return Client(HTTP_HOST="localhost")


def _post(client, url, body):
    return client.post(url, data=json.dumps(body), content_type="application/json")


def test_missing_page_renders_items(client, arr):
    page = client.get("/arr-missing/").content.decode()

    assert "Zeta Show" in page and "Alpha Movie" in page
    assert 'data-am-episode="701"' in page and 'data-am-movie="31"' in page
    assert "Check languages" in page


def test_missing_page_shows_arr_posters_and_falls_back_to_initials(client, arr):
    page = client.get("/arr-missing/").content.decode()

    assert 'src="https://img.example/zeta-poster.jpg"' in page
    assert "zeta-banner" not in page
    assert "javascript:" not in page


def test_missing_page_explains_when_arr_is_not_connected(client, monkeypatch):
    monkeypatch.setattr(manual_service, "_load_arr_config", lambda: {})
    monkeypatch.setattr(manual_service, "_build_clients", lambda cfg: (None, None))

    page = client.get("/arr-missing/").content.decode()

    assert "Sonarr and Radarr are not connected" in page


@pytest.mark.parametrize("body", [{}, {"movies": [], "episodes": []}, {"movies": ["1"], "episodes": [True, -3]}])
def test_download_needs_a_valid_selection(client, body):
    response = _post(client, "/api/arr/missing/download/", body)

    assert response.status_code == 400


def test_download_endpoint_queues_the_selection(client, arr):
    response = _post(client, "/api/arr/missing/download/", {"movies": [31], "episodes": []})

    assert response.status_code == 200
    assert response.json()["queued"] == 1


@pytest.mark.parametrize("body", [{}, {"movie": 1, "episode": 2}, {"movie": "1"}])
def test_check_needs_exactly_one_item(client, body):
    response = _post(client, "/api/arr/missing/check/", body)

    assert response.status_code == 400


def test_check_marks_the_audio_languages_you_want(client, monkeypatch):
    from searchapp.views import download as download_views

    monkeypatch.setattr(manual_service, "find_on_provider", lambda movie_id=None, episode_id=None: {
        "payload": {"name": "Alpha Movie", "type": "movie", "id": 1}, "provider": "streamingcommunity", "season": None, "episode": None,
    })
    monkeypatch.setattr("searchapp.api.get_api", lambda provider: object())
    monkeypatch.setattr(download_views, "track_report", lambda api, item, season, episode, description: {
        "qualities": ["1080p"], "audio_supported": True,
        "audio_languages": [{"code": "it", "name": "Italian"}, {"code": "ja", "name": "Japanese"}],
    })
    monkeypatch.setattr("VibraVid.core.utils.audio_selection.configured_audio_languages", lambda: [{"code": "it", "name": "Italian"}])

    result = _post(client, "/api/arr/missing/check/", {"movie": 31}).json()

    assert result["found"] is True and result["match"] == "Alpha Movie"
    assert [(lang["code"], lang["wanted"]) for lang in result["audio_languages"]] == [("it", True), ("ja", False)]


def test_check_reports_a_title_missing_from_every_provider(client, monkeypatch):
    monkeypatch.setattr(manual_service, "find_on_provider", lambda movie_id=None, episode_id=None: {
        "payload": None, "provider": "streamingcommunity", "season": 1, "episode": 2,
        "searched": ["streamingcommunity", "raiplay"],
    })

    result = _post(client, "/api/arr/missing/check/", {"episode": 702}).json()

    assert result["found"] is False
    assert result["searched"] == ["streamingcommunity", "raiplay"]


def test_check_says_when_a_movie_exists_only_as_a_series(client, monkeypatch):
    monkeypatch.setattr(manual_service, "find_on_provider", lambda movie_id=None, episode_id=None: {
        "payload": None, "provider": "animeunity", "season": None, "episode": None,
        "series_only": {"provider": "animeunity", "match": "Bleach: The Calamity (ITA)"},
    })

    result = _post(client, "/api/arr/missing/check/", {"movie": 31}).json()

    assert result["found"] is False and result["series_only"] is True
    assert result["match"] == "Bleach: The Calamity (ITA)" and result["provider"] == "animeunity"
