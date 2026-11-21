# 21.11.26

"""A muxer that fails or is killed may still leave a truncated, non-empty file: only its exit code / timeout tell, so a failed pass must never be kept as the result."""

import io

import pytest

from VibraVid.core.muxing import capture, merge


@pytest.fixture
def muxer(monkeypatch):
    """Stub every probe; ``muxer["result"]`` is what the fake muxer returns after writing a (partial) output."""
    state = {"result": {"exit_code": 0, "timed_out": False}}

    def fake_capture(cmd, label, duration, **kwargs):
        out = next(t for t in reversed(cmd) if t not in ("-y",))
        if "--output" in cmd or "-o" in cmd:
            out = cmd[cmd.index("--output" if "--output" in cmd else "-o") + 1]
        with open(out, "wb") as f:
            f.write(b"partial")
        return dict(state["result"])

    monkeypatch.setattr(merge, "capture_ffmpeg_real_time", fake_capture)
    monkeypatch.setattr(merge, "get_ffmpeg_path", lambda: "ffmpeg")
    monkeypatch.setattr(merge, "get_mkvmerge_path", lambda: "mkvmerge")
    monkeypatch.setattr(merge, "get_video_duration", lambda path: 10.0)
    monkeypatch.setattr(merge, "is_mpegts_file", lambda path: False)
    monkeypatch.setattr(merge, "detect_ts_timestamp_issues", lambda path: False)
    monkeypatch.setattr(merge, "has_audio", lambda path: False)
    monkeypatch.setattr(merge, "_strip_drm_boxes", lambda path: path)
    monkeypatch.setattr(merge, "USE_GPU", False)
    monkeypatch.setattr(merge, "EXTRACT_EMBEDDED_CC", False)
    monkeypatch.setattr(merge, "_build_global_metadata_flags", lambda: [])
    monkeypatch.setattr(merge, "_maybe_tag_hevc_for_mkv", lambda *a, **k: None)
    monkeypatch.setattr(merge, "add_encoding_params", lambda cmd: cmd.extend(["-c", "copy"]))
    monkeypatch.setattr(merge, "video_track_name", lambda *a, **k: "")
    monkeypatch.setattr(merge, "get_stream_codecs", lambda path: [])
    monkeypatch.setattr(merge, "get_cached_tmdb_image", lambda url: b"\xff\xd8jpeg")
    return state


# ---------------------------------------------------------------- join_media


@pytest.mark.parametrize("result", [{"exit_code": 1, "timed_out": False}, {"exit_code": 0, "timed_out": True}, {"timed_out": True}])
def test_ffmpeg_join_discards_a_failed_or_killed_output(muxer, tmp_path, result):
    muxer["result"] = result
    out = tmp_path / "out.mkv"

    merged, result_json = merge._join_media_ffmpeg("video.mp4", [], [], str(out), False)

    assert merged == "" and not out.exists()
    assert result_json.get("timed_out") == result.get("timed_out")


def test_ffmpeg_join_keeps_a_clean_output(muxer, tmp_path):
    out = tmp_path / "out.mkv"
    merged, _ = merge._join_media_ffmpeg("video.mp4", [], [], str(out), False)
    assert merged == str(out) and out.exists()


@pytest.mark.parametrize("exit_code, kept", [(0, True), (1, True), (2, False)])
def test_mkvmerge_join_treats_exit_1_as_warnings_and_2_as_failure(muxer, tmp_path, exit_code, kept):
    muxer["result"] = {"exit_code": exit_code, "timed_out": False}
    out = tmp_path / "out.mkv"

    merged, _ = merge._join_media_mkvmerge("video.mp4", [], [], str(out))

    assert out.exists() is kept
    assert merged == (str(out) if kept else "")


def test_mkvmerge_join_discards_a_timed_out_output(muxer, tmp_path):
    muxer["result"] = {"exit_code": 1, "timed_out": True}
    out = tmp_path / "out.mkv"
    merged, _ = merge._join_media_mkvmerge("video.mp4", [], [], str(out))
    assert merged == "" and not out.exists()


def test_join_media_returns_an_empty_path_for_a_failed_mux(muxer, monkeypatch, tmp_path):
    muxer["result"] = {"exit_code": 1, "timed_out": False}
    monkeypatch.setattr(merge, "MUX_ENGINE", "ffmpeg")
    monkeypatch.setattr(merge, "_apply_compatible_extension", lambda video_path, out_path: out_path)

    merged, result_json = merge.join_media("video.mp4", [], [], str(tmp_path / "out.mkv"))

    assert merged == "" and result_json["exit_code"] == 1
    assert not (tmp_path / "out.mkv").exists()


# ---------------------------------------------------------------- inject_chapters / embed_poster


CHAPTERS = [{"name": "One", "seconds": 0}, {"name": "Two", "seconds": 5}]


@pytest.mark.parametrize("result", [{"exit_code": 1, "timed_out": False}, {"exit_code": 0, "timed_out": True}])
def test_failed_chapter_injection_keeps_the_original(muxer, monkeypatch, tmp_path, result):
    muxer["result"] = result
    monkeypatch.setattr(merge, "MUX_ENGINE", "ffmpeg")
    original = tmp_path / "movie.mp4"
    original.write_bytes(b"finished file")

    path, _ = merge.inject_chapters(str(original), list(CHAPTERS))

    assert path == str(original) and original.read_bytes() == b"finished file"
    assert not (tmp_path / "movie_chapters.mp4").exists()


def test_successful_chapter_injection_replaces_the_original(muxer, monkeypatch, tmp_path):
    monkeypatch.setattr(merge, "MUX_ENGINE", "ffmpeg")
    original = tmp_path / "movie.mp4"
    original.write_bytes(b"finished file")

    path, _ = merge.inject_chapters(str(original), list(CHAPTERS))

    assert path == str(original) and original.read_bytes() == b"partial"


def test_mkvmerge_chapter_injection_with_warnings_replaces_the_original(muxer, monkeypatch, tmp_path):
    muxer["result"] = {"exit_code": 1, "timed_out": False}
    monkeypatch.setattr(merge, "MUX_ENGINE", "mkvmerge")
    original = tmp_path / "movie.mkv"
    original.write_bytes(b"finished file")

    merge.inject_chapters(str(original), list(CHAPTERS))

    assert original.read_bytes() == b"partial"


@pytest.mark.parametrize("engine, result", [
    ("ffmpeg", {"exit_code": 1, "timed_out": False}),
    ("ffmpeg", {"exit_code": 0, "timed_out": True}),
    ("mkvmerge", {"exit_code": 2, "timed_out": False}),
])
def test_failed_poster_embedding_keeps_the_original(muxer, monkeypatch, tmp_path, engine, result):
    muxer["result"] = result
    monkeypatch.setattr(merge, "MUX_ENGINE", engine)
    original = tmp_path / "movie.mkv"
    original.write_bytes(b"finished file")

    path, _ = merge.embed_poster(str(original), "https://img/x.jpg")

    assert path == str(original) and original.read_bytes() == b"finished file"
    assert not (tmp_path / "movie_poster.mkv").exists()


def test_successful_poster_embedding_replaces_the_original(muxer, monkeypatch, tmp_path):
    monkeypatch.setattr(merge, "MUX_ENGINE", "ffmpeg")
    original = tmp_path / "movie.mkv"
    original.write_bytes(b"finished file")

    merge.embed_poster(str(original), "https://img/x.jpg")

    assert original.read_bytes() == b"partial"


# ---------------------------------------------------------------- capture: timeout and progress parsing


class _FakePopen:
    waited: list = []

    def __init__(self, *args, **kwargs):
        self.stdout = io.StringIO("")
        self.returncode = 0

    def wait(self, timeout=None):
        _FakePopen.waited.append(timeout)
        return 0

    def poll(self):
        return 0


@pytest.fixture
def fake_popen(monkeypatch):
    _FakePopen.waited = []
    monkeypatch.setattr(capture.subprocess, "Popen", _FakePopen)
    monkeypatch.setattr(capture, "log_command", lambda *a, **k: None)
    return _FakePopen.waited


def test_a_long_media_is_not_killed_by_a_fixed_30_minute_cap(fake_popen):
    three_hours = 3 * 3600.0
    capture.capture_ffmpeg_real_time(["ffmpeg"], "join", three_hours)
    assert fake_popen[0] > three_hours  # a re-encode runs slower than real time: the cap must exceed the media itself


def test_an_unknown_duration_still_gets_a_bounded_generous_wait(fake_popen):
    capture.capture_ffmpeg_real_time(["ffmpeg"], "join", None)
    assert 1800.0 <= fake_popen[0] < float("inf")


def test_an_explicit_wait_timeout_is_honoured(fake_popen):
    capture.capture_ffmpeg_real_time(["ffmpeg"], "join", 3 * 3600.0, wait_timeout_seconds=42.0)
    assert fake_popen == [42.0]


class _LinesProcess:
    def __init__(self, text):
        self.stdout = io.StringIO(text)

    def poll(self):
        return 0


def _progress(line, total_duration):
    data = capture.ProgressData()
    capture.capture_output(_LinesProcess(line + "\n"), "join", data, None, total_duration)
    return data.get()


def test_size_n_a_progress_line_is_parsed_instead_of_raising():
    data = _progress("frame=  10 fps=0.0 q=-1.0 size=N/A time=00:00:05.00 bitrate=N/A speed=2.0x", 25.0)
    assert data is not None and data["speed"] == "2.0x"


def test_eta_is_wall_time_remaining_media_time_divided_by_speed():
    data = _progress("frame=  10 fps=0.0 q=-1.0 size=    1024kB time=00:00:05.00 bitrate=N/A speed=2.0x", 25.0)
    assert data["eta"] == "10s"  # 20 s of media left at 2x


def test_eta_falls_back_to_remaining_media_time_without_a_speed():
    data = _progress("frame=  10 fps=0.0 q=-1.0 size=    1024kB time=00:00:05.00 bitrate=N/A speed=N/A", 25.0)
    assert data["eta"] == "20s"
