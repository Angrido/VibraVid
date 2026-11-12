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
from django.core.management import call_command
from django.test import Client
from django.utils import timezone

from searchapp.arr import arr_service, manual_service
from searchapp.models import ArrMediaRequest, ArrProcessingQueue

MOVIE = {"content_type": "movie", "id": 31, "title": "Alpha Movie"}
SERIE = {"content_type": "serie", "id": 7, "title": "Zeta Show"}


@pytest.fixture(autouse=True)
def db():
    call_command("migrate", verbosity=0)
    ArrMediaRequest.objects.all().delete()


@pytest.fixture
def client():
    return Client(HTTP_HOST="localhost")


@pytest.fixture
def started(monkeypatch):
    calls = []

    def start(movie_ids, episode_ids):
        calls.append((movie_ids, episode_ids))
        return {"queued": 1, "skipped": 0, "gone": 0}

    monkeypatch.setattr(manual_service, "start_selected_downloads", start)
    return calls


def _request(dedup_key, status, closed=True, **fields):
    source, arr_id = dedup_key.split("_")[:2]
    request = ArrMediaRequest.objects.create(
        arr_id=int(arr_id), arr_source=source, title="Zeta Show", status=status,
        content_type="movie" if source == "radarr" else "serie", **fields,
    )
    return ArrProcessingQueue.objects.create(
        dedup_key=dedup_key, media_request=request, completed_at=timezone.now() if closed else None,
    )


def test_a_failed_download_keeps_the_reason_the_downloader_gave():
    _request("sonarr_7_s2_e1", ArrMediaRequest.Status.DOWNLOADING, closed=False)

    arr_service._mark_failed(SERIE, "season_not_available", 2, 1)

    request = ArrMediaRequest.objects.get()
    assert (request.status, request.last_error) == ("failed", "season_not_available")
    assert request.failure_reason == "The provider does not have this season."


def test_an_unexpected_error_is_stored_as_a_generic_reason_without_its_text():
    _request("radarr_31", ArrMediaRequest.Status.DOWNLOADING, closed=False)

    arr_service._mark_failed(MOVIE, "HTTPSConnectionPool: https://cdn.example/video?token=SECRET timed out")

    request = ArrMediaRequest.objects.get()
    assert request.last_error == "download_failed"
    assert request.failure_reason == "The download did not complete. Details are in the logs."


def test_a_download_left_running_by_a_restart_is_reported_as_interrupted():
    entry = _request("radarr_31", ArrMediaRequest.Status.DOWNLOADING, closed=False)
    ArrProcessingQueue.objects.filter(pk=entry.pk).update(started_at=timezone.now())

    assert arr_service._reconcile_orphaned_downloads() == 1
    assert ArrMediaRequest.objects.get().failure_reason == "The download was interrupted before it finished."


@pytest.mark.parametrize("status", ["pending", "downloading", "completed", "skipped"])
def test_a_request_that_did_not_fail_has_no_failure_reason(status):
    assert ArrMediaRequest(status=status, last_error="search_no_results").failure_reason == ""


def test_a_download_that_was_not_imported_says_so_even_when_it_predates_the_stored_reason():
    assert ArrMediaRequest(status="import_pending").failure_reason == "Downloaded, but the file was not imported."


def test_queue_page_shows_the_reason_and_offers_retry_only_on_failed_rows(client):
    failed = _request("radarr_31", ArrMediaRequest.Status.FAILED, last_error="search_no_results")
    done = _request("radarr_32", ArrMediaRequest.Status.COMPLETED)

    page = client.get("/arr-stack/").content.decode()

    assert "Not found on any configured provider." in page
    assert f'data-url="/api/arr/queue/{failed.pk}/retry/"' in page
    assert f'data-url="/api/arr/queue/{done.pk}/retry/"' not in page


def test_retry_queues_the_failed_episode_again(client, started):
    entry = _request("sonarr_7_s1_e2", ArrMediaRequest.Status.FAILED, episode_id=702)

    response = client.post(f"/api/arr/queue/{entry.pk}/retry/")

    assert response.status_code == 200 and response.json()["status"] == "ok"
    assert started == [(set(), {702})]


def test_retry_queues_the_failed_movie_again(client, started):
    entry = _request("radarr_31", ArrMediaRequest.Status.IMPORT_PENDING)

    assert client.post(f"/api/arr/queue/{entry.pk}/retry/").status_code == 200
    assert started == [({31}, set())]


def test_retry_refuses_a_request_that_is_still_open(client, started):
    entry = _request("radarr_31", ArrMediaRequest.Status.DOWNLOADING, closed=False)

    assert client.post(f"/api/arr/queue/{entry.pk}/retry/").status_code == 409
    assert started == []


def test_retry_says_when_the_item_is_no_longer_missing(client, monkeypatch):
    entry = _request("radarr_31", ArrMediaRequest.Status.FAILED)
    monkeypatch.setattr(manual_service, "start_selected_downloads", lambda movies, episodes: {"queued": 0, "skipped": 0, "gone": 1})

    response = client.post(f"/api/arr/queue/{entry.pk}/retry/")

    assert response.status_code == 409 and "no longer lists it as missing" in response.json()["message"]


def test_retry_needs_an_episode_id_and_an_existing_request(client, started):
    entry = _request("sonarr_7_s1_e2", ArrMediaRequest.Status.FAILED)

    assert client.post(f"/api/arr/queue/{entry.pk}/retry/").status_code == 400
    assert client.post("/api/arr/queue/999999/retry/").status_code == 404
    assert client.get(f"/api/arr/queue/{entry.pk}/retry/").status_code == 405
    assert started == []
