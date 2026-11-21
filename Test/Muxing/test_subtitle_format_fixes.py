# 21.11.26

"""Subtitle format detection / conversion / VTT sanitizing edge cases: ffprobe's ``subrip`` is SRT, an unknown ``force_subtitle`` is not an extension, and a stray ``<`` is sanitized in every cue."""

import json
import logging
from types import SimpleNamespace

import pytest

from VibraVid.core.muxing.helper.sub import convert as sub_convert
from VibraVid.core.muxing.helper.sub import detect
from VibraVid.core.muxing.helper.sub.sanitize import sanitize_vtt_file
from VibraVid.core.utils.codec import get_codec_extension

SRT = "1\n00:00:00,000 --> 00:00:01,000\nHello\n"


@pytest.fixture
def ffprobe_says(monkeypatch):
    """``ffprobe_says["codec"]`` is the codec ffprobe reports; every ffmpeg run fails (like writing a file onto itself)."""
    state = {"codec": "subrip", "ffmpeg_calls": []}

    def fake_run(cmd, *args, **kwargs):
        if cmd[0] == "ffprobe":
            return SimpleNamespace(returncode=0, stdout=json.dumps({"streams": [{"codec_name": state["codec"]}]}), stderr="")
        state["ffmpeg_calls"].append(list(cmd))
        return SimpleNamespace(returncode=1, stdout="", stderr="Output same as Input")

    monkeypatch.setattr(detect, "get_ffprobe_path", lambda: "ffprobe")
    monkeypatch.setattr(sub_convert, "get_ffmpeg_path", lambda: "ffmpeg")
    monkeypatch.setattr(detect.subprocess, "run", fake_run)
    return state


def test_subrip_codec_maps_to_srt():
    assert get_codec_extension("subrip", default="vtt") == "srt"


def test_srt_is_detected_as_srt(ffprobe_says, tmp_path):
    path = tmp_path / "sub.srt"
    path.write_text(SRT, encoding="utf-8")
    assert detect.detect_subtitle_format(str(path)) == "srt"


def test_auto_mode_keeps_an_srt_named_srt(ffprobe_says, tmp_path):
    path = tmp_path / "sub.srt"
    path.write_text(SRT, encoding="utf-8")

    assert sub_convert.convert_subtitle(str(path), "auto") == str(path)
    assert path.exists() and not (tmp_path / "sub.vtt").exists()


@pytest.mark.parametrize("value", ["on", "off", "bogus"])
def test_an_unsupported_force_subtitle_value_behaves_like_auto(ffprobe_says, tmp_path, caplog, value):
    path = tmp_path / "sub.srt"
    path.write_text(SRT, encoding="utf-8")
    sub_convert._warned_force_values.discard(value)

    with caplog.at_level(logging.WARNING):
        first = sub_convert.convert_subtitle(str(path), value)
        second = sub_convert.convert_subtitle(str(path), value)

    assert first == second == str(path)
    assert not ffprobe_says["ffmpeg_calls"]
    assert not list(tmp_path.glob(f"*.{value}"))
    assert sum(value in r.getMessage() for r in caplog.records) == 1  # one warning, not one per subtitle


def test_conversion_onto_the_same_path_keeps_the_subtitle(ffprobe_says, tmp_path):
    # VTT content in a .srt file: converting it "to srt" would make ffmpeg write the file onto itself and fail
    ffprobe_says["codec"] = "webvtt"
    path = tmp_path / "sub.srt"
    path.write_text("WEBVTT\n\n00:00.000 --> 00:01.000\nHello\n", encoding="utf-8")

    assert sub_convert.convert_subtitle(str(path), "srt") == str(path)
    assert path.exists() and not ffprobe_says["ffmpeg_calls"]


def test_stray_lt_is_sanitized_in_every_cue_not_only_the_last(tmp_path):
    path = tmp_path / "sub.vtt"
    path.write_text(
        "WEBVTT\n\n00:00.000 --> 00:01.000\na < b\n\n00:01.000 --> 00:02.000\n<i>tagged</i> c < d\n",
        encoding="utf-8",
    )

    sanitize_vtt_file(str(path))

    text = path.read_text(encoding="utf-8")
    assert "a < b" not in text and "a -  b" in text  # a following cue's "-->" must not count as the closing ">"
    assert "c -  d" in text
    assert "<i>tagged</i>" in text
