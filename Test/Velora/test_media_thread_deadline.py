# 21.11.26

"""A VOD track still downloading at the hard deadline is stopped and reported as a failure, never merged half-written."""

import threading
import time

from VibraVid.core.velora.downloader import MediaDownloader
from VibraVid.core.velora.util._stream_helpers import join_interruptible


def _downloader():
    d = object.__new__(MediaDownloader)
    d._abort_event = threading.Event()
    d._stop_event = threading.Event()
    d._active_loops = []
    d._loops_lock = threading.Lock()
    d.download_id = None
    return d


def test_join_interruptible_says_when_the_deadline_expired():
    never_stops = threading.Event()
    worker = threading.Thread(target=lambda: never_stops.wait(5), daemon=True)
    worker.start()
    try:
        assert join_interruptible([worker], threading.Event(), poll=0.01, hard_timeout=0.05) is True
    finally:
        never_stops.set()
    worker.join()
    assert join_interruptible([worker], threading.Event(), poll=0.01, hard_timeout=0.05) is False


def test_expired_deadline_stops_the_tracks_and_fails():
    d = _downloader()
    worker = threading.Thread(target=lambda: d._stop_event.wait(5), daemon=True)
    worker.start()

    assert d._join_media_threads([worker], hard_timeout=0.05) is False
    assert d._stop_event.is_set() and d._abort_event.is_set()
    assert not worker.is_alive()


def test_tracks_finishing_in_time_are_left_alone():
    d = _downloader()
    worker = threading.Thread(target=lambda: time.sleep(0.02), daemon=True)
    worker.start()

    assert d._join_media_threads([worker], hard_timeout=5.0) is True
    assert not d._stop_event.is_set() and not d._abort_event.is_set()
