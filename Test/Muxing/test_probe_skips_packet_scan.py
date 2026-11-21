# 21.11.26

"""Callers that only need quality / HDR flags must not trigger the packet scan that reads the whole video to measure its bit rate."""

from VibraVid.core.muxing import hybrid, merge


def _recorder(asked):
    def fake(path, with_bitrate=True):
        asked.append(with_bitrate)
        return {"quality": "1080p"}

    return fake


def test_video_track_name_skips_the_bitrate_scan(monkeypatch):
    asked = []
    monkeypatch.setattr(merge, "get_media_metadata", _recorder(asked))

    assert merge.video_track_name("video.mp4") == "1080p"
    assert asked == [False]


def test_probe_media_file_skips_the_bitrate_scan(monkeypatch, tmp_path):
    asked = []
    media = tmp_path / "video.mkv"
    media.write_bytes(b"x")
    monkeypatch.setattr(hybrid, "get_media_metadata", _recorder(asked))
    monkeypatch.setattr(hybrid, "get_ffprobe_path", lambda: (_ for _ in ()).throw(RuntimeError("no stream probe in this test")))

    assert hybrid.probe_media_file.__wrapped__(str(media))["quality"] == "1080p"
    assert asked == [False]
