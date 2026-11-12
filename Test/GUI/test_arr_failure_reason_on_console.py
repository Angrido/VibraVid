# 12.11.26
# ruff: noqa: E402

import logging
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

from searchapp.arr import arr_service
from searchapp.arr.item_log import NoItemFilter


class FailingDownloader:
    last_error = "season_not_available"

    def _process_serie(self, _item):
        return False

    def _process_movie(self, _item):
        return False


class ConsoleRecords(logging.Handler):
    def __init__(self):
        super().__init__()
        self.addFilter(NoItemFilter())
        self.messages = []

    def emit(self, record):
        self.messages.append(record.getMessage())


@pytest.fixture
def console(monkeypatch):
    monkeypatch.setattr(arr_service, "_mark_downloading", lambda *a, **k: None)
    monkeypatch.setattr(arr_service, "_mark_failed", lambda *a, **k: None)
    handler = ConsoleRecords()
    arr_logger = logging.getLogger("ARR")
    arr_logger.addHandler(handler)
    yield handler.messages
    arr_logger.removeHandler(handler)


def test_failed_episode_reports_its_reason_on_the_console(console):
    item = {"title": "Monster", "id": 188}

    arr_service.download_episode(FailingDownloader(), item, {"number": 4}, {"episodeNumber": 1, "id": 9})

    assert "'Monster' S4E1 not downloaded: season_not_available" in console


def test_failed_movie_reports_its_reason_on_the_console(console):
    arr_service.download_movie(FailingDownloader(), {"title": "Above & Below", "id": 732})

    assert "'Above & Below' not downloaded: season_not_available" in console
