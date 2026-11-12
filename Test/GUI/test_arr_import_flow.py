# ruff: noqa: E402

"""#789: an episode the provider does not have must stop before rescan/manual import."""

import errno
import os
import sys
import time
from concurrent.futures import Future
from pathlib import Path
from types import SimpleNamespace

repo_root = Path(__file__).resolve().parents[2]
for p in (str(repo_root), str(repo_root / "GUI")):
    if p not in sys.path:
        sys.path.insert(0, p)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "webgui.settings")

import django

django.setup()

import pytest

from searchapp import views
from searchapp.arr.downloader_service import ArrDownloaderService


class FakeSonarr:
    def __init__(self):
        self.calls = []

    def is_episode_in_queue(self, _id):
        return False

    def series_exists(self, _id):
        return True

    def command_rescan_series(self, _id):
        self.calls.append("rescan")

    def command_rename_series(self, _id):
        self.calls.append("rename")


def _service(monkeypatch, tmp_path, download_result, writes_file):
    sonarr = FakeSonarr()
    svc = ArrDownloaderService(sonarr, None)
    series_root = tmp_path / "Serie1"
    (series_root / "Season 1").mkdir(parents=True)

    for name, value in {
        "_resolve_request_tmdb_id": lambda *a, **k: 123,
        "_strict_tmdb_matching_enabled": lambda *a, **k: False,
        "_resolve_sonarr_title": lambda *a, **k: ["Serie1"],
        "_is_sonarr_episode_still_monitored": lambda *a, **k: True,
        "_search_with_fallback_titles": lambda *a, **k: ({"name": "Serie1"}, "streamingcommunity", "Serie1"),
        "_auto_map_by_episode_names": lambda *a, **k: None,
        "_provider_lacks_season": lambda *a, **k: False,
        "_sonarr_season_folder": lambda *a, **k: "Season 1",
        "_translate_path": lambda path, reverse=False: path,
        "_wait_episode_has_file": lambda *a, **k: True,
        "_warn_if_sonarr_rename_disabled": lambda *a, **k: None,
    }.items():
        monkeypatch.setattr(svc, name, value)
    monkeypatch.setattr(time, "sleep", lambda *_: None)
    svc.manual_import_calls = []
    monkeypatch.setattr(svc, "_confirm_episode_import", lambda *a, **k: svc.manual_import_calls.append(1) or False)

    monkeypatch.setenv("VIBRAVID_TEMP_DIR", str(tmp_path / "vibravid_tmp"))
    svc.download_kwargs = {}

    def fake_download(**kwargs):
        svc.download_kwargs = kwargs
        output = Path(kwargs["output_path"])
        if writes_file:
            resumable = output / ".Serie1 S01E13_temp"
            resumable.mkdir(parents=True, exist_ok=True)
            (resumable / "segment_0001.ts").write_bytes(b"s")
            (output / "Serie1 S01E13.mkv").write_bytes(b"x")
        future = Future()
        future.set_result(download_result)
        return future

    monkeypatch.setattr(views, "_run_download_in_thread", fake_download)
    serie = {
        "id": 1, "title": "Serie1", "provider": "streamingcommunity", "path": str(series_root),
        "seasons": [{"number": 1, "episodes": [{"episodeNumber": 13, "id": 99}]}],
    }
    return svc, sonarr, serie


def test_episode_missing_on_provider_skips_rescan_and_manual_import(monkeypatch, tmp_path):
    svc, sonarr, serie = _service(monkeypatch, tmp_path, download_result=False, writes_file=False)

    assert svc._process_serie_item(serie) is False
    assert svc.last_error == "episode_not_available"
    assert sonarr.calls == [] and svc.manual_import_calls == []


def test_download_that_wrote_a_file_still_goes_through_import(monkeypatch, tmp_path):
    """A provider result of False is not trusted blindly: a file on disk means the import proceeds."""
    svc, sonarr, serie = _service(monkeypatch, tmp_path, download_result=False, writes_file=True)

    assert svc._process_serie_item(serie) is True
    assert "rescan" in sonarr.calls


def test_successful_download_is_imported(monkeypatch, tmp_path):
    svc, sonarr, serie = _service(monkeypatch, tmp_path, download_result=True, writes_file=True)

    assert svc._process_serie_item(serie) is True
    assert sonarr.calls[:1] == ["rescan"] and svc.last_error is None


def test_download_is_staged_outside_the_series_folder_and_only_the_final_file_is_moved(monkeypatch, tmp_path):
    svc, sonarr, serie = _service(monkeypatch, tmp_path, download_result=True, writes_file=True)
    season_folder = Path(serie["path"]) / "Season 1"

    assert svc._process_serie_item(serie) is True

    staging = Path(svc.download_kwargs["output_path"])
    assert staging.is_relative_to(tmp_path / "vibravid_tmp")
    assert not staging.is_relative_to(Path(serie["path"]))
    assert sorted(p.name for p in season_folder.iterdir()) == ["Serie1 S01E13.mkv"]
    assert not staging.exists()


def test_failed_import_keeps_the_series_folder_clean_and_the_segments_resumable(monkeypatch, tmp_path):
    svc, sonarr, serie = _service(monkeypatch, tmp_path, download_result=True, writes_file=True)
    monkeypatch.setattr(sonarr, "series_exists", lambda _id: False)
    season_folder = Path(serie["path"]) / "Season 1"

    assert svc._process_serie_item(serie) is False

    staging = Path(svc.download_kwargs["output_path"])
    assert list(season_folder.iterdir()) == []
    assert sorted(p.name for p in staging.iterdir()) == [".Serie1 S01E13_temp"]


def test_staged_file_on_another_filesystem_is_copied_then_renamed(monkeypatch, tmp_path):
    staging = tmp_path / "staging"
    destination = tmp_path / "library" / "Season 1"
    staging.mkdir()
    (staging / "Serie1 S01E13.mkv").write_bytes(b"video")
    (staging / "Serie1 S01E13.it.srt").write_bytes(b"sub")
    real_replace = os.replace

    def replace_across_devices(src, dst):
        if Path(src).parent == staging:
            raise OSError(errno.EXDEV, "Invalid cross-device link")
        real_replace(src, dst)

    monkeypatch.setattr(os, "replace", replace_across_devices)

    published = ArrDownloaderService._publish_staged_files(staging, destination)

    assert sorted(p.name for p in published) == ["Serie1 S01E13.it.srt", "Serie1 S01E13.mkv"]
    assert sorted(p.name for p in destination.iterdir()) == ["Serie1 S01E13.it.srt", "Serie1 S01E13.mkv"]
    assert (destination / "Serie1 S01E13.mkv").read_bytes() == b"video"
    assert list(staging.iterdir()) == []


def test_episodes_of_the_same_season_get_separate_staging_folders(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBRAVID_TEMP_DIR", str(tmp_path))
    season_folder = str(tmp_path / "Serie1" / "Season 1")

    first = ArrDownloaderService._staging_folder(season_folder, "S1E1")
    second = ArrDownloaderService._staging_folder(season_folder, "S1E2")

    assert first != second
    assert first == ArrDownloaderService._staging_folder(season_folder, "S1E1")
