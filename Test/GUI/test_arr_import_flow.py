# ruff: noqa: E402

"""#789: an episode the provider does not have must stop before rescan/manual import."""

import errno
import os
import sys
import threading
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

from VibraVid.core.ui.tracker import download_tracker


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


class FakeManualImport:
    """Sonarr/Radarr manual import: the lookup lists every file of the folder, the library's own included."""

    def __init__(self, names):
        self.names = names
        self.submitted = []

    def manual_import_lookup(self, folder, **_ids):
        return [{"path": f"{folder}/{name}", "episodes": []} for name in self.names]

    def manual_import(self, items):
        self.submitted.extend(items)
        return {}

    def get_episode(self, _id):
        return {"hasFile": True}

    def get_movie_by_id(self, _id):
        return {"hasFile": True}


def test_episode_manual_import_submits_only_the_file_just_downloaded(monkeypatch):
    """Episodes already in the season folder must not be rebound to the one just downloaded (import mode is Move)."""
    sonarr = FakeManualImport(["Serie1 S01E01.mkv", "Serie1 S01E02.mkv", "Serie1 Episodio 13.mkv"])
    svc = ArrDownloaderService(sonarr, None)
    monkeypatch.setattr(time, "sleep", lambda *_: None)

    published = [Path("D:/library/Serie1/Season 1/Serie1 Episodio 13.mkv")]
    assert svc._confirm_episode_import(1, 99, ["/tv/Serie1/Season 1"], published, force_episode=True)

    assert [(item["path"], item["episodes"]) for item in sonarr.submitted] == [
        ("/tv/Serie1/Season 1/Serie1 Episodio 13.mkv", [{"id": 99}])
    ]


def test_movie_manual_import_submits_only_the_file_just_downloaded(monkeypatch):
    radarr = FakeManualImport(["Parasite (2019) - old cut.mkv", "Parasite.mkv"])
    svc = ArrDownloaderService(None, radarr)
    monkeypatch.setattr(time, "sleep", lambda *_: None)

    assert svc._confirm_movie_import(7, ["/movies/Parasite (2019)"], [Path("/data/Parasite (2019)/Parasite.mkv")])

    assert [(item["path"], item["movieId"]) for item in radarr.submitted] == [("/movies/Parasite (2019)/Parasite.mkv", 7)]


def test_episodes_of_the_same_season_get_separate_staging_folders(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBRAVID_TEMP_DIR", str(tmp_path))
    season_folder = str(tmp_path / "Serie1" / "Season 1")

    first = ArrDownloaderService._staging_folder(season_folder, "S1E1")
    second = ArrDownloaderService._staging_folder(season_folder, "S1E2")

    assert first != second
    assert first == ArrDownloaderService._staging_folder(season_folder, "S1E1")


def _hanging_download(monkeypatch, svc):
    """A download whose worker never returns (stalled CDN, hung muxer)."""
    future = Future()
    future.download_id = "streamingcommunity_hung"
    future.started = threading.Event()
    future.started.set()
    svc.calls = 0

    def fake_download(**kwargs):
        svc.calls += 1
        svc.download_kwargs = kwargs
        (Path(kwargs["output_path"]) / "partial.mkv").write_bytes(b"x")
        return future

    monkeypatch.setattr(views, "_run_download_in_thread", fake_download)
    stops = []
    monkeypatch.setattr(download_tracker, "request_stop", stops.append)
    svc.download_timeout = 0.05
    svc._STOP_GRACE_SECONDS = 0
    return future, stops


def test_timed_out_episode_is_stopped_and_its_staging_left_to_the_running_worker(monkeypatch, tmp_path):
    svc, sonarr, serie = _service(monkeypatch, tmp_path, download_result=True, writes_file=False)
    future, stops = _hanging_download(monkeypatch, svc)

    assert svc._process_serie_item(serie) is False

    assert stops == ["streamingcommunity_hung"]
    assert svc.last_error == "interrupted"
    assert (Path(svc.download_kwargs["output_path"]) / "partial.mkv").exists()
    assert sonarr.calls == []
    future.set_result(False)


def test_retry_does_not_start_a_second_worker_in_a_staging_folder_still_in_use(monkeypatch, tmp_path):
    svc, sonarr, serie = _service(monkeypatch, tmp_path, download_result=True, writes_file=False)
    future, _stops = _hanging_download(monkeypatch, svc)
    svc._process_serie_item(serie)

    assert svc._process_serie_item(serie) is False
    assert svc.calls == 1

    future.set_result(False)
    svc._process_serie_item(serie)
    assert svc.calls == 2


def test_download_timeout_starts_when_the_job_gets_a_slot_not_while_it_is_queued(monkeypatch, tmp_path):
    svc, sonarr, serie = _service(monkeypatch, tmp_path, download_result=True, writes_file=True)
    queued = Future()
    queued.download_id = "streamingcommunity_queued"
    queued.started = threading.Event()

    def fake_download(**kwargs):
        (Path(kwargs["output_path"]) / "Serie1 S01E13.mkv").write_bytes(b"x")
        threading.Timer(0.4, queued.started.set).start()
        threading.Timer(0.45, queued.set_result, args=(True,)).start()
        return queued

    monkeypatch.setattr(views, "_run_download_in_thread", fake_download)
    svc.download_timeout = 0.3

    assert svc._process_serie_item(serie) is True


class FakeRadarr:
    def is_movie_in_queue(self, _id):
        return False

    def movie_exists(self, _id):
        return True


def test_timed_out_movie_is_stopped_and_its_staging_left_to_the_running_worker(monkeypatch, tmp_path):
    svc = ArrDownloaderService(None, FakeRadarr())
    for name, value in {
        "_resolve_request_tmdb_id": lambda *a, **k: 123,
        "_strict_tmdb_matching_enabled": lambda *a, **k: False,
        "_is_radarr_movie_still_monitored": lambda *a, **k: True,
        "_resolve_radarr_title": lambda *a, **k: ["Film1"],
        "_search_with_fallback_titles": lambda *a, **k: ({"name": "Film1"}, "streamingcommunity", "Film1"),
        "_translate_path": lambda path, reverse=False: path,
    }.items():
        monkeypatch.setattr(svc, name, value)
    monkeypatch.setattr(time, "sleep", lambda *_: None)
    monkeypatch.setenv("VIBRAVID_TEMP_DIR", str(tmp_path / "vibravid_tmp"))
    future, stops = _hanging_download(monkeypatch, svc)
    movie = {"id": 7, "title": "Film1", "provider": "streamingcommunity", "path": str(tmp_path / "Film1")}

    assert svc._process_movie_item(movie) is False

    assert stops == ["streamingcommunity_hung"]
    assert svc.last_error == "interrupted"
    assert (Path(svc.download_kwargs["output_path"]) / "partial.mkv").exists()
    assert svc._process_movie_item(movie) is False and svc.calls == 1
    future.set_result(False)
