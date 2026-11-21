# 21.11.26

"""The Dolby Vision hybrid mux writes tens of GB of raw HEVC into ``<name>_hybrid_tmp`` next to the output: a failed run must not leave it in the library folder."""

import pytest

from VibraVid.core.muxing import hybrid


@pytest.fixture
def hybrid_run(monkeypatch, tmp_path):
    base = tmp_path / "base.mp4"
    other = tmp_path / "dv.mp4"
    base.write_bytes(b"hdr10")
    other.write_bytes(b"dv")
    monkeypatch.setattr(hybrid, "get_dovi_tool_path", lambda: "dovi_tool")
    monkeypatch.setattr(hybrid, "get_mkvmerge_path", lambda: "mkvmerge")
    monkeypatch.setattr(hybrid, "_select_hybrid_video", lambda video_track, others: {"path": str(other), "probe": {"dolby_vision": True}})
    monkeypatch.setattr(hybrid, "CLEANUP_TMP", True)

    def run():
        return hybrid.build_hybrid_output(
            {"path": str(base), "probe": {"hdr": True}}, [], [], [], str(tmp_path / "out" / "Movie.mkv"), "Movie"
        )

    return run, tmp_path / "out" / "Movie_hybrid_tmp"


def test_a_failed_hybrid_mux_removes_its_work_dir(monkeypatch, hybrid_run):
    run, work_dir = hybrid_run

    def fail_after_writing(src, dst):
        dst.write_bytes(b"raw hevc")  # the intermediate a real run would leave behind
        return False

    monkeypatch.setattr(hybrid, "_to_annexb_hdr10", fail_after_writing)

    assert run() is None
    assert not work_dir.exists()


def test_the_work_dir_is_kept_when_cleanup_is_disabled(monkeypatch, hybrid_run):
    run, work_dir = hybrid_run
    monkeypatch.setattr(hybrid, "CLEANUP_TMP", False)
    monkeypatch.setattr(hybrid, "_to_annexb_hdr10", lambda src, dst: False)

    assert run() is None
    assert work_dir.exists()
