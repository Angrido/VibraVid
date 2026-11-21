# 21.11.26

"""A failed audio conversion must never cost the user the original song: process_song deletes the original only after a real success."""

import pytest

from VibraVid.core.muxing.helper.audio import convert


@pytest.fixture
def song(monkeypatch, tmp_path):
    """A downloaded song plus a fake ffmpeg that writes ``state["written"]`` and returns ``state["result"]``."""
    state = {"result": {"exit_code": 0, "timed_out": False}, "written": b"converted"}
    source = tmp_path / "song.flac"
    source.write_bytes(b"original audio")

    def fake_capture(cmd, label, duration, **kwargs):
        if state["written"] is not None:
            with open(cmd[-1], "wb") as f:
                f.write(state["written"])
        return dict(state["result"])

    monkeypatch.setattr(convert, "capture_ffmpeg_real_time", fake_capture)
    monkeypatch.setattr(convert, "get_ffmpeg_path", lambda: "ffmpeg")
    monkeypatch.setattr(convert, "get_video_duration", lambda path: 10.0)
    monkeypatch.setattr(convert, "tag_track", lambda **kwargs: None)
    monkeypatch.setattr(convert, "fix_container_mismatch", lambda path: path)
    monkeypatch.setattr("VibraVid.remote.capture.record_post_process", lambda *a, **k: False)
    monkeypatch.setattr(convert, "ffmpeg_params", ["-c:a", "libopus", "-b:a", "128k"])
    return state, source


@pytest.mark.parametrize("result, written", [
    ({"exit_code": 1, "timed_out": False}, b"half"),
    ({"exit_code": 0, "timed_out": True}, b"half"),
    ({"exit_code": 0, "timed_out": False}, b""),
])
def test_convert_audio_rejects_a_failed_conversion_and_removes_its_output(song, result, written):
    state, source = song
    state["result"], state["written"] = result, written

    assert convert.convert_audio(str(source), convert.ffmpeg_params) is None
    assert not source.with_suffix(".opus").exists()


@pytest.mark.parametrize("result, written", [
    ({"exit_code": 1, "timed_out": False}, b"half"),
    ({"exit_code": 0, "timed_out": True}, b"half"),
])
def test_process_song_keeps_the_original_when_conversion_fails(song, result, written):
    state, source = song
    state["result"], state["written"] = result, written

    final = convert.process_song(str(source), "Title", "Artist")

    assert final == str(source)
    assert source.read_bytes() == b"original audio"


def test_process_song_replaces_the_original_after_a_real_success(song):
    _state, source = song

    final = convert.process_song(str(source), "Title", "Artist")

    assert final == str(source.with_suffix(".opus"))
    assert not source.exists()
