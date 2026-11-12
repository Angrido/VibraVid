# 12.11.26
# ruff: noqa: E402

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
import requests
from django.core.management import call_command
from django.test import Client

from searchapp.arr import library_service
from searchapp.models import ArrMediaRequest, ArrProcessingQueue

POSTER = {"coverType": "poster", "remoteUrl": "https://img.example/poster.jpg"}
FANART = {"coverType": "fanart", "remoteUrl": "https://img.example/fanart.jpg"}


def _not_found():
    response = requests.Response()
    response.status_code = 404
    return requests.HTTPError(response=response)


def _rejected_key():
    response = requests.Response()
    response.status_code = 401
    return requests.HTTPError(response=response)


class FakeSonarr:
    label = "Sonarr"
    down = False

    def get_series(self):
        if self.down:
            raise self.down if isinstance(self.down, Exception) else requests.ConnectionError("refused")
        return [
            {"id": 7, "title": "Zeta Show", "year": 2020, "monitored": True, "images": [POSTER], "added": "2024-05-01T10:00:00Z",
             "statistics": {"episodeCount": 4, "episodeFileCount": 1, "seasonCount": 2, "sizeOnDisk": 2048}},
            {"id": 8, "title": "alpha Done", "monitored": True, "statistics": {"episodeCount": 2, "episodeFileCount": 2}},
            {"id": 9, "title": "Muted", "monitored": False, "statistics": {"episodeCount": 3, "episodeFileCount": 0}},
        ]

    def get_series_by_id(self, series_id):
        if series_id != 7:
            raise _not_found()
        return {**self.get_series()[0], "overview": "A show.", "images": [POSTER, FANART], "network": "HBO", "status": "continuing"}

    def get_episodes_for_series(self, series_id):
        return [
            {"id": 701, "seasonNumber": 1, "episodeNumber": 1, "title": "Pilot", "hasFile": True, "monitored": True, "airDateUtc": "2020-01-01T20:00:00Z"},
            {"id": 702, "seasonNumber": 1, "episodeNumber": 2, "title": "Two", "hasFile": False, "monitored": True, "airDateUtc": "2020-01-08T20:00:00Z"},
            {"id": 703, "seasonNumber": 1, "episodeNumber": 3, "title": "Three", "hasFile": False, "monitored": True, "airDateUtc": "2020-01-15T20:00:00Z"},
            {"id": 704, "seasonNumber": 1, "episodeNumber": 4, "title": "Skipped", "hasFile": False, "monitored": False, "airDateUtc": "2020-01-22T20:00:00Z"},
            {"id": 801, "seasonNumber": 2, "episodeNumber": 1, "title": "Soon", "hasFile": False, "monitored": True, "airDateUtc": "2999-01-01T20:00:00Z"},
            {"id": 901, "seasonNumber": 0, "episodeNumber": 1, "title": "Special", "hasFile": False, "monitored": True, "airDateUtc": "2020-02-01T20:00:00Z"},
        ]


class FakeRadarr:
    label = "Radarr"

    def get_movies(self):
        return [
            {"id": 31, "title": "Alpha Movie", "year": 2021, "monitored": True, "hasFile": False, "isAvailable": True, "images": [POSTER]},
            {"id": 32, "title": "Owned", "monitored": True, "hasFile": True, "runtime": 101},
            {"id": 33, "title": "Upcoming", "monitored": True, "hasFile": False, "isAvailable": False},
        ]

    def get_movie_by_id(self, movie_id):
        movie = next((m for m in self.get_movies() if m["id"] == movie_id), None)
        if movie is None:
            raise _not_found()
        return {**movie, "overview": "A movie.", "studio": "Studio X"}


@pytest.fixture(autouse=True)
def db():
    call_command("migrate", verbosity=0)
    ArrMediaRequest.objects.all().delete()


@pytest.fixture
def arr(monkeypatch):
    clients = {"sonarr": FakeSonarr(), "radarr": FakeRadarr()}
    monkeypatch.setattr(library_service, "_load_arr_config", lambda: {})
    monkeypatch.setattr(library_service, "_build_clients", lambda cfg: (clients["sonarr"], clients["radarr"]))
    return clients


@pytest.fixture
def client():
    return Client(HTTP_HOST="localhost")


def _queue(dedup_key, status, last_error=""):
    source, arr_id = dedup_key.split("_")[:2]
    request = ArrMediaRequest.objects.create(
        arr_id=int(arr_id), arr_source=source, title="x", content_type="serie", status=status, last_error=last_error,
    )
    ArrProcessingQueue.objects.create(dedup_key=dedup_key, media_request=request)


def test_library_lists_titles_sorted_with_their_state(arr):
    library = library_service.scan_library()

    assert [(c["title"], c["state"], c["missing"]) for c in library["series"]] == [
        ("alpha Done", "complete", 0), ("Muted", "unmonitored", 0), ("Zeta Show", "missing", 3),
    ]
    assert [(c["title"], c["state"]) for c in library["movies"]] == [
        ("Alpha Movie", "missing"), ("Owned", "complete"), ("Upcoming", "unaired"),
    ]
    assert library["missing_episodes"] == 3 and library["missing_movies"] == 1
    assert library["series"][2]["percent"] == 25


def test_library_keeps_radarr_when_sonarr_does_not_answer(arr):
    arr["sonarr"].down = True

    library = library_service.scan_library()

    assert library["unreachable"] == ["Sonarr"] and library["series"] == []
    assert len(library["movies"]) == 3


def test_series_detail_marks_only_aired_monitored_missing_episodes_as_selectable(arr):
    _queue("sonarr_7_s1_e3", ArrMediaRequest.Status.DOWNLOADING)

    detail = library_service.series_detail(7)

    numbers = [season["number"] for season in detail["seasons"]]
    assert numbers == [2, 1, 0]
    episodes = {e["id"]: e for season in detail["seasons"] for e in season["episodes"]}
    assert [episodes[i]["state"] for i in (701, 702, 703, 704, 801)] == ["complete", "missing", "missing", "unmonitored", "unaired"]
    assert episodes[703]["queue"] == "downloading"
    assert [i for i, e in episodes.items() if e["selectable"]] == [702]
    assert detail["item"]["fanart"] == "https://img.example/fanart.jpg"
    assert [season["open"] for season in detail["seasons"]] == [False, True, True]


def test_movie_detail_is_selectable_only_when_missing_and_not_queued(arr):
    assert library_service.movie_detail(31)["selectable"] is True
    assert library_service.movie_detail(32)["selectable"] is False
    _queue("radarr_31", ArrMediaRequest.Status.PENDING)
    assert library_service.movie_detail(31)["selectable"] is False


def test_menu_links_to_the_library_page(client, arr):
    page = client.get("/arr/").content.decode()

    assert 'href="/arr/" aria-current="page"' in " ".join(page.split())
    assert 'href="/arr/series/7/"' in page and 'href="/arr/movie/31/"' in page
    assert 'src="https://img.example/poster.jpg"' in page
    assert "3 missing" in page


def test_library_page_explains_when_arr_is_not_connected(client, monkeypatch):
    monkeypatch.setattr(library_service, "_load_arr_config", lambda: {})
    monkeypatch.setattr(library_service, "_build_clients", lambda cfg: (None, None))

    assert "Sonarr and Radarr are not connected" in client.get("/arr/").content.decode()
    assert "Sonarr and Radarr are not connected" in client.get("/arr/series/7/").content.decode()


def test_series_page_shows_seasons_and_checkboxes_for_missing_episodes(client, arr):
    page = client.get("/arr/series/7/").content.decode()

    assert "Zeta Show" in page and "Season 1" in page and "Specials" in page
    assert 'data-am-episode="702"' in page and 'data-am-episode="701"' not in page
    assert 'data-am-check-episode="702"' in page
    assert 'src="https://img.example/fanart.jpg"' in page


def test_movie_page_offers_download_for_a_missing_movie(client, arr):
    page = client.get("/arr/movie/31/").content.decode()

    assert 'data-am-movie="31"' in page and "Select for download" in page


def test_unknown_title_is_not_found(client, arr):
    assert client.get("/arr/series/99/").status_code == 404
    assert client.get("/arr/movie/99/").status_code == 404


def test_title_page_explains_when_sonarr_does_not_answer(client, arr, monkeypatch):
    def refuse(series_id):
        raise requests.ConnectionError("refused")

    monkeypatch.setattr(arr["sonarr"], "get_series_by_id", refuse)

    response = client.get("/arr/series/7/")

    assert response.status_code == 200
    assert "This title could not be loaded" in response.content.decode()


def test_title_pages_trust_sonarr_and_radarr_over_an_old_queue_state(arr):
    _queue("sonarr_7_s1_e1", ArrMediaRequest.Status.COMPLETED)
    _queue("sonarr_7_s1_e2", ArrMediaRequest.Status.IMPORT_PENDING)
    _queue("radarr_32", ArrMediaRequest.Status.COMPLETED)

    episodes = {e["id"]: e for season in library_service.series_detail(7)["seasons"] for e in season["episodes"]}

    assert (episodes[701]["state"], episodes[701]["queue"]) == ("complete", "")
    assert episodes[702]["queue"] == "import_pending"
    assert library_service.movie_detail(32)["item"]["queue"] == ""


def test_library_tells_a_rejected_api_key_from_a_server_that_does_not_answer(client, arr):
    arr["sonarr"].down = _rejected_key()

    library = library_service.scan_library()
    page = client.get("/arr/").content.decode()

    assert library["unreachable"] == ["Sonarr"] and library["unauthorized"] == ["Sonarr"]
    assert len(library["movies"]) == 3
    assert "Sonarr rejected the API key" in page and "did not answer" not in page


def test_library_tiles_carry_what_sorting_needs(client, arr):
    page = client.get("/arr/").content.decode()

    assert 'data-added="2024-05-01T10:00:00Z" data-size="2048"' in page
    assert 'id="lib-sort"' in page and 'value="added"' in page


def test_activity_counts_what_is_downloading_queued_and_failed_for_each_title(arr):
    _queue("sonarr_7_s1_e2", ArrMediaRequest.Status.DOWNLOADING)
    _queue("sonarr_7_s1_e3", ArrMediaRequest.Status.PENDING)
    _queue("sonarr_7_s1_e4", ArrMediaRequest.Status.PENDING)
    _queue("radarr_31", ArrMediaRequest.Status.FAILED)
    _queue("radarr_33", ArrMediaRequest.Status.IMPORT_PENDING)
    _queue("radarr_32", ArrMediaRequest.Status.COMPLETED)
    _queue("sonarr_8_s1_e1", ArrMediaRequest.Status.SKIPPED)

    assert library_service.title_activity() == {
        "serie:7": {"downloading": 1, "queued": 2},
        "movie:31": {"failed": 1},
    }


def test_library_page_and_its_endpoint_share_the_activity_the_tiles_show(client, arr):
    _queue("radarr_31", ArrMediaRequest.Status.DOWNLOADING)

    page = client.get("/arr/").content.decode()
    live = client.get("/api/arr/library/activity/").json()

    assert '<script id="lib-activity" type="application/json">{"movie:31": {"downloading": 1}}</script>' in page
    assert 'data-activity-url="/api/arr/library/activity/"' in page and "data-lib-activity" in page
    assert live == {"status": "ok", "titles": {"movie:31": {"downloading": 1}}}


def test_series_page_marks_each_row_for_live_updates_and_keeps_a_busy_episode_pickable_later(client, arr):
    _queue("sonarr_7_s1_e3", ArrMediaRequest.Status.DOWNLOADING)

    page = " ".join(client.get("/arr/series/7/").content.decode().split())

    assert 'data-am-key="sonarr_7_s1_e2" data-am-state=""' in page
    assert 'data-am-key="sonarr_7_s1_e3" data-am-state="downloading"' in page
    assert 'data-am-key="sonarr_7_s1_e1"' not in page
    assert 'data-am-episode="703" disabled' in page and 'data-am-episode="702" >' in page
    assert 'data-states-url="/api/arr/missing/states/"' in page


def test_movie_page_marks_its_row_for_live_updates(client, arr):
    page = client.get("/arr/movie/31/").content.decode()

    assert 'data-am-key="radarr_31" data-am-state=""' in page
    assert 'data-states-url="/api/arr/missing/states/"' in page


def test_movie_that_cannot_be_downloaded_now_has_no_checkbox_for_a_live_update_to_enable(client, arr):
    _queue("radarr_33", ArrMediaRequest.Status.DOWNLOADING)

    page = client.get("/arr/movie/33/").content.decode()

    assert 'data-am-key="radarr_33" data-am-state="downloading"' in page
    assert "data-am-movie" not in page


def test_title_pages_explain_why_the_last_try_failed(client, arr):
    _queue("sonarr_7_s1_e2", ArrMediaRequest.Status.FAILED, "season_not_available")
    _queue("radarr_31", ArrMediaRequest.Status.FAILED)

    episodes = {e["id"]: e for season in library_service.series_detail(7)["seasons"] for e in season["episodes"]}

    assert episodes[702]["reason"] == "The provider does not have this season." and episodes[702]["selectable"]
    assert "The provider does not have this season." in client.get("/arr/series/7/").content.decode()
    assert "The download did not complete. Details are in the logs." in client.get("/arr/movie/31/").content.decode()
