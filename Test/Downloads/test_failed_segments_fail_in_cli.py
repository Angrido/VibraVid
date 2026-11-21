# 21.11.26

"""Missing segments fail the download in the CLI too, before the mux, so the temp folder a rerun resumes from is kept."""

import pytest

from VibraVid.core.downloader import base
from VibraVid.core.ui.tracker import context_tracker


@pytest.fixture
def cli(monkeypatch):
    monkeypatch.setattr(context_tracker, "is_gui", False)


def _with_failed_segments(tmp_path, count):
    d = object.__new__(base.BaseDownloader)
    d.output_dir = str(tmp_path / ".temp")
    d.output_path = str(tmp_path / f"ep1.{base.EXTENSION_OUTPUT}")
    d.download_id = None
    d.media_downloader = type("MD", (), {"had_failed_segments": count, "streaming_mux_result": None})()
    return d


def test_failed_segments_fail_the_download_status_check(tmp_path, cli):
    d = _with_failed_segments(tmp_path, 3)

    result = d._check_download_status({"video": {"path": str(tmp_path / "v.mp4")}, "audios": []})

    assert result is not None and not result.ok and result.stopped
    assert "3 segment(s)" in result.error


def test_failed_segments_are_never_muxed(tmp_path, cli, monkeypatch):
    d = _with_failed_segments(tmp_path, 2)
    monkeypatch.setattr(d, "_merge_files", lambda _status: pytest.fail("a file with missing segments was muxed"), raising=False)

    result = d._merge_and_finalize({"video": {"path": str(tmp_path / "v.mp4")}, "audios": []})

    assert result.stopped and "2 segment(s)" in result.error


def test_no_failed_segments_goes_on(tmp_path, cli):
    d = _with_failed_segments(tmp_path, 0)

    assert d._check_download_status({"video": {"path": str(tmp_path / "v.mp4")}, "audios": []}) is None


def test_generic_downloader_counts_failed_segments_in_cli(cli):
    from VibraVid.core.downloader import _generic

    d = object.__new__(_generic.Generic_Downloader)
    md = type("MD", (), {"_failed_segments": [("video", [1, 2]), ("audio", [7])]})()
    d._active = [(md, {})]

    assert d._generic_failed_segments() == 3
