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

from searchapp.views import _shared, dashboard
from VibraVid.core.ui.tracker import ContextTracker, context_tracker, download_tracker

PAYLOAD = {"name": "Dark", "type": "tv", "url": "https://example.invalid/dark"}


@pytest.fixture(autouse=True)
def _isolated_tracker():
    call_command("migrate", verbosity=0, interactive=False)
    saved_global = ContextTracker._global_is_gui
    saved_local = dict(context_tracker.local.__dict__)
    download_tracker.clear_history()
    yield
    download_tracker.clear_history()
    ContextTracker._global_is_gui = saved_global
    context_tracker.local.__dict__.clear()
    context_tracker.local.__dict__.update(saved_local)


class _FailingProvider:
    supports_audio_selection = False
    supports_quality_discovery = True

    def get_series_metadata(self, media_item):
        return []

    def start_download(self, media_item, season=None, episodes=None):
        return False


def _run_failing_gui_download(monkeypatch, season="2", episodes="5"):
    provider = _FailingProvider()
    monkeypatch.setattr(_shared, "get_api", lambda site: provider)
    monkeypatch.setattr(_shared, "_add_scheduled_download", lambda *args, **kwargs: None)
    monkeypatch.setattr(_shared, "_remove_scheduled_download", lambda *args, **kwargs: None)
    monkeypatch.setattr(_shared, "_acquire_download_slot", lambda: None)
    monkeypatch.setattr(_shared, "_release_download_slot", lambda: None)
    monkeypatch.setattr(_shared, "_is_scheduled_cancelled", lambda download_id: False)
    monkeypatch.setattr(_shared, "_log_gui_equivalent_command", lambda *args, **kwargs: None)
    monkeypatch.setattr(_shared, "_submit_download_task", lambda fn: fn)

    task = _shared._run_download_in_thread("somesite", PAYLOAD, season, episodes, "Serie", quality="1080p")
    with pytest.raises(RuntimeError):
        task()
    return download_tracker.get_history()[0]


def _retry(client, body):
    return client.post("/api/retry-download/", data=json.dumps(body), content_type="application/json", HTTP_HOST="127.0.0.1")


def test_failed_gui_download_can_be_retried_with_the_same_request(monkeypatch):
    failed = _run_failing_gui_download(monkeypatch)
    calls = []
    monkeypatch.setattr(dashboard, "_run_download_in_thread", lambda *args, **kwargs: calls.append((args, kwargs)))

    response = _retry(Client(), {"download_id": failed["id"]})

    assert response.status_code == 200
    assert calls == [(("somesite", PAYLOAD, "2", "5", "Serie"), {"quality": "1080p", "audio_language": None, "audio_format": None})]


def test_history_exposes_retryable_but_not_the_stored_request(monkeypatch):
    _run_failing_gui_download(monkeypatch)

    entry = Client().get("/api/get-downloads/", HTTP_HOST="127.0.0.1").json()["history"][0]

    assert entry["retryable"] is True
    assert "retry" not in entry


def test_retry_refuses_unknown_or_not_failed_downloads(monkeypatch):
    download_tracker.start_download("cli_job", "From the CLI", "somesite")
    download_tracker.complete_download("cli_job", success=False, error="boom")
    calls = []
    monkeypatch.setattr(dashboard, "_run_download_in_thread", lambda *args, **kwargs: calls.append(args))
    client = Client()

    assert _retry(client, {"download_id": "missing"}).status_code == 404
    assert _retry(client, {"download_id": "cli_job"}).status_code == 404
    assert _retry(client, ["not", "an", "object"]).status_code == 400
    assert calls == []
