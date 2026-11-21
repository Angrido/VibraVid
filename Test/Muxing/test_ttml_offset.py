# 16.09.26

import re

from VibraVid.core.muxing.helper.sub.ttml import convert_ttml_to_format


def _tt_block(begin_end_text: list[tuple[str, str, str]]) -> bytes:
    cues = "".join(
        f'<p begin="{begin}" end="{end}">{text}</p>' for begin, end, text in begin_end_text
    )
    return (
        '<tt xmlns="http://www.w3.org/ns/ttml" xml:lang="en">'
        f"<body><div>{cues}</div></body></tt>"
    ).encode("utf-8")


def _cue_times(srt_text: str) -> list[tuple[str, str]]:
    return re.findall(r"(\d{2}:\d{2}:\d{2},\d{3}) --> (\d{2}:\d{2}:\d{2},\d{3})", srt_text)


def test_already_absolute_blocks_are_not_double_shifted(tmp_path):
    # Mirrors the Canal+ DASH stpp case: each ~1-minute block already carries
    # absolute program time and must NOT be re-based on top of itself.
    blocks = [
        _tt_block([("00:00:08.000", "00:00:10.000", "one")]),
        _tt_block([("00:01:00.000", "00:01:02.000", "two")]),
        _tt_block([("00:02:03.000", "00:02:05.000", "three")]),
    ]
    src = tmp_path / "sub.mp4"
    src.write_bytes(b"".join(blocks))
    out = tmp_path / "sub.srt"

    assert convert_ttml_to_format(str(src), str(out), "srt")
    times = _cue_times(out.read_text(encoding="utf-8"))
    assert times == [
        ("00:00:08,000", "00:00:10,000"),
        ("00:01:00,000", "00:01:02,000"),
        ("00:02:03,000", "00:02:05,000"),
    ]


def test_zero_restarting_blocks_are_rebased_ism_style(tmp_path):
    # Genuine ISM-style chunking: each block's own cues restart near zero and
    # must be shifted onto the running timeline. Chunks are long enough (~5-9s)
    # that the running offset clearly outgrows the near-zero restart tolerance.
    blocks = [
        _tt_block([("00:00:01.000", "00:00:06.000", "one")]),
        _tt_block([("00:00:00.500", "00:00:09.000", "two")]),
        _tt_block([("00:00:00.200", "00:00:08.000", "three")]),
    ]
    src = tmp_path / "sub.mp4"
    src.write_bytes(b"".join(blocks))
    out = tmp_path / "sub.srt"

    assert convert_ttml_to_format(str(src), str(out), "srt")
    times = _cue_times(out.read_text(encoding="utf-8"))
    assert times == [
        ("00:00:01,000", "00:00:06,000"),
        ("00:00:06,500", "00:00:15,000"),
        ("00:00:15,200", "00:00:23,000"),
    ]


def test_exact_offsets_do_not_shift_absolute_blocks(tmp_path):
    # TIMvision DASH stpp: the manifest gives exact chunk offsets (30s segments) but the
    # cues inside each fragment are already absolute, so the offsets must not be added.
    blocks = [
        _tt_block([("00:00:08.000", "00:00:10.000", "one")]),
        _tt_block([("00:00:31.000", "00:00:33.000", "two")]),
        _tt_block([("00:01:03.000", "00:01:05.000", "three")]),
    ]
    src = tmp_path / "sub.mp4"
    src.write_bytes(b"".join(blocks))
    out = tmp_path / "sub.srt"

    assert convert_ttml_to_format(str(src), str(out), "srt", chunk_offsets=[0.0, 30.0, 60.0])
    times = _cue_times(out.read_text(encoding="utf-8"))
    assert times == [
        ("00:00:08,000", "00:00:10,000"),
        ("00:00:31,000", "00:00:33,000"),
        ("00:01:03,000", "00:01:05,000"),
    ]


def test_exact_offsets_rebase_zero_restarting_blocks(tmp_path):
    # ISM-style chunks (cues relative to their own chunk) still get the exact manifest offset.
    blocks = [
        _tt_block([("00:00:01.000", "00:00:03.000", "one")]),
        _tt_block([("00:00:02.000", "00:00:04.000", "two")]),
        _tt_block([("00:00:05.000", "00:00:07.000", "three")]),
    ]
    src = tmp_path / "sub.mp4"
    src.write_bytes(b"".join(blocks))
    out = tmp_path / "sub.srt"

    assert convert_ttml_to_format(str(src), str(out), "srt", chunk_offsets=[0.0, 30.0, 60.0])
    times = _cue_times(out.read_text(encoding="utf-8"))
    assert times == [
        ("00:00:01,000", "00:00:03,000"),
        ("00:00:32,000", "00:00:34,000"),
        ("00:01:05,000", "00:01:07,000"),
    ]


def _late_forced_track(tmp_path, first_cue: str = "01:12:30.000", end: str = "01:12:33.000"):
    src = tmp_path / "forced.ttml"
    src.write_bytes(_tt_block([(first_cue, end, "forced narrative")]))
    return src, tmp_path / "forced.srt"


def test_late_first_cue_inside_the_media_is_kept(tmp_path):
    # A forced-narrative track whose only cue is at 01:12:30 of a 1h30 film is correct as it is.
    src, out = _late_forced_track(tmp_path)

    assert convert_ttml_to_format(str(src), str(out), "srt", media_duration=5400.0)
    assert _cue_times(out.read_text(encoding="utf-8")) == [("01:12:30,000", "01:12:33,000")]


def test_first_cue_beyond_the_media_is_rebased(tmp_path):
    # Wall-clock timestamps (10h in) on a 1h30 film: only a rebase can put them on the media timeline.
    src, out = _late_forced_track(tmp_path, "10:00:05.000", "10:00:07.000")

    assert convert_ttml_to_format(str(src), str(out), "srt", media_duration=5400.0)
    assert _cue_times(out.read_text(encoding="utf-8")) == [("00:00:00,000", "00:00:02,000")]


def test_without_a_duration_a_late_first_cue_is_still_rebased(tmp_path):
    src, out = _late_forced_track(tmp_path)

    assert convert_ttml_to_format(str(src), str(out), "srt")
    assert _cue_times(out.read_text(encoding="utf-8")) == [("00:00:00,000", "00:00:03,000")]


def test_join_passes_the_video_duration_to_the_ttml_conversion(tmp_path, monkeypatch):
    from VibraVid.core.muxing import merge

    src, _ = _late_forced_track(tmp_path)
    monkeypatch.setattr(merge, "FORCE_SUBTITLE", "auto")
    monkeypatch.setattr(merge, "get_video_duration", lambda _path: 5400.0)
    monkeypatch.setattr(merge, "get_subtitle_duration", lambda _path: None)

    processed = merge._prepare_subtitle_tracks(str(tmp_path / "video.mp4"), [{"path": str(src), "language": "ita"}])
    assert _cue_times(open(processed[0]["path"], encoding="utf-8").read()) == [("01:12:30,000", "01:12:33,000")]
