# 21.11.26
# ruff: noqa: E402

"""A codec filter matches every variant of its family: ``H265`` maps to ``hvc1`` but must still match ``hev1.*`` streams (and ``H264`` ``avc3.*``)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

import pytest
from mock_streams import MockStream

from VibraVid.core.utils.selector import StreamSelector, _matches_codec


@pytest.mark.parametrize("token, codecs, expected", [
    ("H265", "hev1.1.6.L120.90", True),
    ("hvc1", "hev1.2.4.L150.B0", True),
    ("hevc", "hev1.1.6.L120.90", True),
    ("H.265", "hev1.1.6.L120.90", True),
    ("H264", "avc3.640028", True),
    ("avc1", "avc3.4d401f", True),
    ("H265", "avc1.640028", False),
    ("H264", "hev1.1.6.L120.90", False),
    ("H265", "hvc1.2.4.L120.B0", True),
    ("aac", "mp4a.40.2", True),
    ("aac", "ec-3", False),
])
def test_codec_filter_matches_the_whole_family(token, codecs, expected):
    stream_type = "audio" if token == "aac" else "video"
    assert _matches_codec(MockStream(type=stream_type, codecs=codecs), token) is expected


def test_h265_filter_selects_the_hev1_stream_instead_of_relaxing_to_any_codec():
    streams = [
        MockStream(type="video", height=1080, codecs="hev1.1.6.L120.90", bitrate=4_000_000, id="hev1080"),
        MockStream(type="video", height=2160, codecs="avc1.640033", bitrate=15_000_000, id="avc2160"),
    ]
    StreamSelector("res=best:codecs=H265:for=best", "false", "false").apply(streams)
    assert [s.id for s in streams if s.type == "video" and s.selected] == ["hev1080"]
