# 21.11.26

"""The "already downloaded" pre-check matches only this title, and the temp folder survives a final file that never arrived."""

import pytest

from VibraVid.core.downloader import base


def _bare(tmp_path, name="ep1"):
    d = object.__new__(base.BaseDownloader)
    d.output_dir = str(tmp_path / ".temp")
    d.output_path = str(tmp_path / f"{name}.{base.EXTENSION_OUTPUT}")
    d.filename_base = name
    return d


def test_a_longer_sibling_title_is_not_this_file(tmp_path):
    (tmp_path / f"ep10.{base.EXTENSION_OUTPUT}").write_bytes(b"x")
    assert _bare(tmp_path)._finished_file_exists() is False


def test_exact_and_media_token_names_count_as_finished(tmp_path):
    d = _bare(tmp_path)
    (tmp_path / f"ep1 [1080p].{base.EXTENSION_OUTPUT}").write_bytes(b"x")
    assert d._finished_file_exists() is True

    other = tmp_path / "exact"
    other.mkdir()
    (other / f"ep1.{base.EXTENSION_OUTPUT}").write_bytes(b"x")
    assert _bare(other)._finished_file_exists() is True


def test_a_media_download_error_is_not_muxed(tmp_path):
    """The velora deadline returns {"error": ...}: even a streaming-mux result must not go on to the merge."""
    d = _bare(tmp_path)
    d.download_id = None
    d.media_downloader = type("MD", (), {"streaming_mux_result": object()})()

    result = d._check_download_status({"error": "media download still running after 7200s (stopped)"})

    assert result is not None and not result.ok and "7200s" in result.error


def test_a_failed_mux_says_why(tmp_path, monkeypatch):
    """join_media returns "" when ffmpeg/mkvmerge failed or timed out: the download must fail with a reason."""
    video = tmp_path / "video.mp4"
    video.write_bytes(b"v")
    d = _bare(tmp_path)
    d.download_id = None
    d.media_downloader = None
    d.chapters = None
    d._error = None
    d._decrypt_failure_message = lambda: None
    monkeypatch.setattr(base, "join_media", lambda **kwargs: ("", None))

    assert d._merge_files({"video": {"path": str(video), "probe": {"streams": []}}, "audios": []}) is None
    assert d.error and "Merge failed" in d.error


@pytest.fixture
def removed(monkeypatch):
    calls = []
    monkeypatch.setattr(base, "CLEANUP_TMP", True)
    monkeypatch.setattr(base.os_manager, "fast_rmtree", lambda path: calls.append(path))
    monkeypatch.setattr(base.os_manager, "sweep_trash", lambda path: None)
    monkeypatch.setattr(base, "retag_file", lambda path: None)
    monkeypatch.setattr(base.Sidecars, "write_for", lambda *a, **k: None)
    return calls


def _finalizing(tmp_path):
    d = _bare(tmp_path)
    d.copied_subtitles = []
    d.copied_audios = []
    d.download_id = None
    return d


def test_missing_final_file_keeps_the_temp_folder(tmp_path, removed):
    """Audio-only: _move_copied_audios points output_path at the destination before a move that may fail."""
    d = _finalizing(tmp_path)

    d._finalize(final_file="")

    assert removed == []


def test_empty_final_file_keeps_the_temp_folder(tmp_path, removed):
    d = _finalizing(tmp_path)
    open(d.output_path, "wb").close()

    d._finalize(final_file="")

    assert removed == []


def test_present_final_file_cleans_the_temp_folder(tmp_path, removed):
    d = _finalizing(tmp_path)
    with open(d.output_path, "wb") as fh:
        fh.write(b"muxed")

    d._finalize(final_file="")

    assert removed == [d.output_dir]
