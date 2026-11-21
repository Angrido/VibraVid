# 21.11.26

"""A failed swap of the normalized track must never lose the merged track (e.g. a Windows sharing violation)."""

import os
from pathlib import Path

from VibraVid.core.muxing.helper import video as video_helper
from VibraVid.core.velora._decrypt_pipeline import pipeline as pipeline_module
from VibraVid.core.velora._decrypt_pipeline.pipeline import DecryptPipelineMixin


def _setup(monkeypatch, tmp_path):
    track = tmp_path / "movie.mp4"
    track.write_bytes(b"merged")
    norm = tmp_path / "movie.norm.mp4"

    def fake_normalize(src, _log=None):
        norm.write_bytes(b"normalized")
        return norm

    monkeypatch.setattr(video_helper, "normalize_timestamps", fake_normalize)
    monkeypatch.setattr(
        pipeline_module.config_manager.config, "get_bool", lambda section, key, data_type=bool, default=None: True
    )
    return track, norm


def _locked(*_args, **_kwargs):
    raise PermissionError(32, "The process cannot access the file because it is being used by another process")


def test_locked_target_keeps_the_merged_track(monkeypatch, tmp_path):
    track, norm = _setup(monkeypatch, tmp_path)
    monkeypatch.setattr(os, "replace", _locked)
    monkeypatch.setattr(os, "rename", _locked)
    monkeypatch.setattr(Path, "replace", _locked)
    monkeypatch.setattr(Path, "rename", _locked)

    DecryptPipelineMixin._normalize_out_path(object(), track, False)

    assert track.read_bytes() == b"merged"


def test_successful_swap_replaces_the_track(monkeypatch, tmp_path):
    track, norm = _setup(monkeypatch, tmp_path)

    DecryptPipelineMixin._normalize_out_path(object(), track, False)

    assert track.read_bytes() == b"normalized"
    assert not norm.exists()
