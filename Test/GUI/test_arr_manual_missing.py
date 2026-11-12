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

    problem = ""

    def connection_problem(self):
        return self.problem

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

    def connection_problem(self):
        return ""

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
    assert scan["problems"] == {} and scan["polling_active"] is False


def test_scan_reports_an_unreachable_server_and_keeps_the_other(arr):
    clients, _ = arr
    clients["sonarr"].problem = "unreachable"

    scan = manual_service.scan_missing()

    assert scan["problems"] == {"Sonarr": "unreachable"}
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
        "url": "https://sc.example/it/titles/1-alpha",
    })
    monkeypatch.setattr("searchapp.api.get_api", lambda provider: object())
    monkeypatch.setattr(download_views, "track_report", lambda api, item, season, episode, description: {
        "qualities": ["1080p"], "audio_supported": True,
        "audio_languages": [{"code": "it", "name": "Italian"}, {"code": "ja", "name": "Japanese"}],
    })
    monkeypatch.setattr("VibraVid.core.utils.audio_selection.configured_audio_languages", lambda: [{"code": "it", "name": "Italian"}])

    result = _post(client, "/api/arr/missing/check/", {"movie": 31}).json()

    assert result["found"] is True and result["match"] == "Alpha Movie"
    assert result["url"] == "https://sc.example/it/titles/1-alpha"
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


def test_scan_gives_every_row_the_queue_key_the_page_polls(arr):
    scan = manual_service.scan_missing()

    assert [e["queue_key"] for e in scan["series"][0]["seasons"][0]["episodes"]] == ["sonarr_7_s1_e1", "sonarr_7_s1_e2"]
    assert scan["movies"][0]["queue_key"] == "radarr_31"


def test_states_endpoint_reports_a_failed_download_without_reloading(client):
    _queue("radarr_31", ArrMediaRequest.Status.FAILED)
    _queue("sonarr_7_s1_e2", ArrMediaRequest.Status.DOWNLOADING)

    states = client.get("/api/arr/missing/states/", {"keys": "radarr_31,sonarr_7_s1_e2,sonarr_7_s1_e1"}).json()["states"]

    assert states["radarr_31"]["state"] == "failed" and "Last try failed" in states["radarr_31"]["html"]
    assert states["sonarr_7_s1_e2"]["state"] == "downloading" and "Downloading" in states["sonarr_7_s1_e2"]["html"]
    assert states["sonarr_7_s1_e1"] == {"state": "", "html": ""}


@pytest.mark.parametrize("status, label", [("skipped", "Not downloaded (skipped)"), ("import_pending", "Downloaded, not imported")])
def test_states_endpoint_labels_every_closed_state(client, status, label):
    _queue("radarr_31", status)

    states = client.get("/api/arr/missing/states/", {"keys": "radarr_31"}).json()["states"]

    assert label in states["radarr_31"]["html"]


@pytest.mark.parametrize("keys", ["", "../etc", "radarr_x", ",".join(f"radarr_{n}" for n in range(1, 502))])
def test_states_endpoint_rejects_missing_or_invalid_keys(client, keys):
    assert client.get("/api/arr/missing/states/", {"keys": keys}).status_code == 400


def test_missing_page_marks_each_state_slot_for_live_updates(client, arr):
    _queue("radarr_31", ArrMediaRequest.Status.PENDING)

    page = client.get("/arr-missing/").content.decode()

    assert 'data-am-key="radarr_31" data-am-state="pending"' in page
    assert 'data-am-key="sonarr_7_s1_e1" data-am-state=""' in page
    assert 'data-states-url="/api/arr/missing/states/"' in page


class FilesOnArr:
    label = "Arr"

    def __init__(self, error=None):
        self.error = error

    def get_movie_by_id(self, movie_id):
        if self.error:
            raise self.error
        return {"id": movie_id, "hasFile": movie_id == 31}

    def get_episodes_for_series(self, series_id):
        if self.error:
            raise self.error
        return [
            {"seasonNumber": 1, "episodeNumber": 1, "hasFile": True},
            {"seasonNumber": 1, "episodeNumber": 2, "hasFile": False},
        ]


def test_states_endpoint_shows_imported_when_sonarr_or_radarr_has_the_file(client, monkeypatch):
    monkeypatch.setattr(manual_service, "_load_arr_config", lambda: {})
    monkeypatch.setattr(manual_service, "_build_clients", lambda cfg: (FilesOnArr(), FilesOnArr()))
    _queue("radarr_31", ArrMediaRequest.Status.COMPLETED)
    _queue("sonarr_7_s1_e1", ArrMediaRequest.Status.IMPORT_PENDING)
    _queue("sonarr_7_s1_e2", ArrMediaRequest.Status.COMPLETED)

    states = client.get("/api/arr/missing/states/", {"keys": "radarr_31,sonarr_7_s1_e1,sonarr_7_s1_e2"}).json()["states"]

    assert states["radarr_31"]["state"] == "imported" and "In library" in states["radarr_31"]["html"]
    assert states["sonarr_7_s1_e1"]["state"] == "imported"
    assert states["sonarr_7_s1_e2"]["state"] == "completed" and "Downloaded, not imported" in states["sonarr_7_s1_e2"]["html"]


def test_states_endpoint_keeps_the_queue_state_when_arr_does_not_answer(client, monkeypatch):
    import requests

    broken = FilesOnArr(requests.ConnectionError("refused"))
    monkeypatch.setattr(manual_service, "_load_arr_config", lambda: {})
    monkeypatch.setattr(manual_service, "_build_clients", lambda cfg: (broken, broken))
    _queue("radarr_31", ArrMediaRequest.Status.COMPLETED)

    states = client.get("/api/arr/missing/states/", {"keys": "radarr_31"}).json()["states"]

    assert states["radarr_31"]["state"] == "completed"


def test_scan_tells_a_rejected_api_key_from_a_server_that_does_not_answer(client, arr):
    clients, _ = arr
    clients["sonarr"].problem = "unauthorized"

    scan = manual_service.scan_missing()
    page = client.get("/arr-missing/").content.decode()

    assert scan["problems"] == {"Sonarr": "unauthorized"}
    assert "Sonarr rejected the API key" in page and "did not answer" not in page


def test_states_endpoint_explains_why_the_last_try_failed(client):
    _queue("radarr_31", ArrMediaRequest.Status.FAILED)
    ArrMediaRequest.objects.update(last_error="search_no_results")

    html = client.get("/api/arr/missing/states/", {"keys": "radarr_31"}).json()["states"]["radarr_31"]["html"]

    assert "Last try failed" in html and "Not found on any configured provider." in html
