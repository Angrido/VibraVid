# 21.11.26
# ruff: noqa: E402

import sys
from pathlib import Path

workspace_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(workspace_root))

from VibraVid.core.manifest.mpd import DashParser

# Periods without @duration: each one lasts until the next @start (the last until the end of the presentation), not the
# whole mediaPresentationDuration, which would size every $Number$ template at 30 segments and request 404s.
_MPD = """<?xml version="1.0" encoding="utf-8"?>
<MPD xmlns="urn:mpeg:dash:schema:mpd:2011" type="static" mediaPresentationDuration="PT60S">
  <Period id="1" start="PT0S">
    <AdaptationSet contentType="video" mimeType="video/mp4" codecs="avc1.64001f">
      <Representation id="v" bandwidth="1000" width="1280" height="720">
        <SegmentTemplate timescale="1" duration="2" startNumber="1" media="p1/$Number$.m4s" initialization="p1/init.mp4"/>
      </Representation>
    </AdaptationSet>
  </Period>
  <Period id="2" start="PT20S">
    <AdaptationSet contentType="video" mimeType="video/mp4" codecs="avc1.64001f">
      <Representation id="v" bandwidth="1000" width="1280" height="720">
        <SegmentTemplate timescale="1" duration="2" startNumber="1" media="p2/$Number$.m4s" initialization="p2/init.mp4"/>
      </Representation>
    </AdaptationSet>
  </Period>
</MPD>
"""


def _media_urls() -> list[str]:
    parser = DashParser("https://cdn.example/path/manifest.mpd", content=_MPD, quiet=True)
    parser.fetch_manifest()
    return [s.url for stream in parser.parse_streams() for s in stream.segments if s.seg_type == "media"]


def test_period_without_duration_ends_at_the_next_start():
    urls = _media_urls()
    assert sum("/p1/" in u for u in urls) == 10
    assert sum("/p2/" in u for u in urls) == 20
