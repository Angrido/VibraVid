# 21.11.26
# ruff: noqa: E402

"""DASH S@r=-1, Smooth Streaming c@r, Representation/MPD BaseURL resolution and HLS rendition ids."""

import sys
from pathlib import Path
from unittest.mock import patch

workspace_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(workspace_root))

from VibraVid.core.manifest.ism import ISMParser
from VibraVid.core.manifest.m3u8 import HLSParser
from VibraVid.core.manifest.mpd import DashParser

_MPD_URL = "https://cdn.example/path/manifest.mpd"


def _dash_streams(mpd: str):
    parser = DashParser(_MPD_URL, content=mpd, quiet=True)
    parser.fetch_manifest()
    return parser.parse_streams()


def _timeline_mpd(timeline: str) -> str:
    return f"""<?xml version="1.0" encoding="utf-8"?>
<MPD xmlns="urn:mpeg:dash:schema:mpd:2011" type="static" mediaPresentationDuration="PT20S">
  <Period duration="PT20S">
    <AdaptationSet contentType="video" mimeType="video/mp4">
      <Representation id="v1" bandwidth="1000" width="640" height="360" codecs="avc1.4d401e">
        <SegmentTemplate timescale="1000" media="v1/$Time$.m4s" initialization="v1/init.mp4">
          <SegmentTimeline>{timeline}</SegmentTimeline>
        </SegmentTemplate>
      </Representation>
    </AdaptationSet>
  </Period>
</MPD>
"""


def _media_times(timeline: str) -> list[str]:
    (stream,) = _dash_streams(_timeline_mpd(timeline))
    return [s.url.rsplit("/", 1)[-1] for s in stream.segments if s.seg_type == "media"]


def test_dash_negative_repeat_runs_to_the_end_of_the_period():
    times = _media_times('<S t="0" d="2000" r="-1"/>')
    assert times == [f"{i * 2000}.m4s" for i in range(10)]


def test_dash_negative_repeat_stops_at_the_next_explicit_time():
    times = _media_times('<S t="0" d="2000" r="-1"/><S t="6000" d="4000" r="1"/>')
    assert times == ["0.m4s", "2000.m4s", "4000.m4s", "6000.m4s", "10000.m4s"]


def _single_file_mpd(rep_base: str, segment_base: bool) -> str:
    seg = '<SegmentBase indexRange="800-1000"><Initialization range="0-799"/></SegmentBase>' if segment_base else ""
    return f"""<?xml version="1.0" encoding="utf-8"?>
<MPD xmlns="urn:mpeg:dash:schema:mpd:2011" type="static" mediaPresentationDuration="PT20S">
  <Period duration="PT20S">
    <AdaptationSet contentType="video" mimeType="video/mp4">
      <Representation id="v1" bandwidth="1000" width="640" height="360" codecs="avc1.4d401e">
        <BaseURL>{rep_base}</BaseURL>{seg}
      </Representation>
    </AdaptationSet>
  </Period>
</MPD>
"""


def test_dash_relative_representation_base_url_is_joined_once():
    for segment_base in (True, False):
        (stream,) = _dash_streams(_single_file_mpd("./video/v1.mp4", segment_base))
        assert [s.url for s in stream.segments] == ["https://cdn.example/path/video/v1.mp4"]

        (stream,) = _dash_streams(_single_file_mpd("../v1.mp4", segment_base))
        assert [s.url for s in stream.segments] == ["https://cdn.example/v1.mp4"]


def test_dash_scheme_relative_mpd_base_url_takes_the_manifest_scheme():
    mpd = _timeline_mpd('<S t="0" d="2000" r="1"/>').replace(
        "<Period ", "<BaseURL>//cdn2.example.com/content/</BaseURL>\n  <Period ", 1
    )
    (stream,) = _dash_streams(mpd)
    assert [s.url for s in stream.segments] == [
        "https://cdn2.example.com/content/v1/init.mp4",
        "https://cdn2.example.com/content/v1/0.m4s",
        "https://cdn2.example.com/content/v1/2000.m4s",
    ]


_ISM = """<?xml version="1.0" encoding="utf-8"?>
<SmoothStreamingMedia MajorVersion="2" MinorVersion="0" Duration="70000000" TimeScale="10000000">
  <StreamIndex Type="video" Chunks="4" Url="QualityLevels({bitrate})/Fragments(video={start time})" Name="video">
    <QualityLevel Index="0" Bitrate="1000" FourCC="H264" MaxWidth="640" MaxHeight="360" />
    <c t="0" d="20000000" r="3"/>
    <c d="10000000"/>
  </StreamIndex>
</SmoothStreamingMedia>
"""


def test_ism_repeat_is_the_total_fragment_count():
    parser = ISMParser("https://cdn.example/v.ism/Manifest", content=_ISM)
    parser.fetch_manifest()
    (stream,) = parser.parse_streams()
    starts = [int(s.url.rsplit("=", 1)[-1].rstrip(")")) for s in stream.segments if s.seg_type == "media"]
    # MS-SSTR: r="3" is three contiguous fragments, then the trailing <c> is the fourth (Chunks="4").
    assert starts == [0, 20000000, 40000000, 60000000]


_MASTER_TWIN_SUBS = """#EXTM3U
#EXT-X-VERSION:6
#EXT-X-MEDIA:TYPE=SUBTITLES,GROUP-ID="subs",NAME="English",LANGUAGE="en",URI="subs/en.m3u8"
#EXT-X-MEDIA:TYPE=SUBTITLES,GROUP-ID="subs",NAME="English",LANGUAGE="en",FORCED=YES,URI="subs/en_forced.m3u8"
#EXT-X-MEDIA:TYPE=SUBTITLES,GROUP-ID="subs",NAME="English SDH",LANGUAGE="en",CHARACTERISTICS="public.accessibility.describes-music-and-sound",URI="subs/en_sdh.m3u8"
#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="aud",NAME="English",LANGUAGE="en",URI="aud/en.m3u8"
#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="aud",NAME="English AD",LANGUAGE="en",CHARACTERISTICS="public.accessibility.describes-video",URI="aud/en_ad.m3u8"
#EXT-X-STREAM-INF:BANDWIDTH=2000000,CODECS="avc1.640028,mp4a.40.2",RESOLUTION=1280x720,AUDIO="aud",SUBTITLES="subs"
video/720p.m3u8
"""


def test_hls_renditions_sharing_a_language_are_all_kept():
    parser = HLSParser(m3u8_url="file:///dummy/master.m3u8", content=_MASTER_TWIN_SUBS)
    parser.fetch_manifest()
    with patch.object(HLSParser, "_resolve_drm", lambda self, streams, master_drm: None):
        streams = parser.parse_streams()

    subs = sorted(s.playlist_url.rsplit("/", 1)[-1] for s in streams if s.type == "subtitle")
    auds = sorted(s.playlist_url.rsplit("/", 1)[-1] for s in streams if s.type == "audio")
    assert subs == ["en.m3u8", "en_forced.m3u8", "en_sdh.m3u8"]
    assert auds == ["en.m3u8", "en_ad.m3u8"]
