# 21.11.26

from VibraVid.core.downloader import hls, mp4


class _Tracker:
    """Records the GUI tracker lifecycle of one download."""

    def __init__(self):
        self.started: list[str] = []
        self.completed: list[tuple[str, bool, str | None]] = []

    def start_download(self, download_id, *_a, **_k):
        self.started.append(download_id)

    def update_status(self, *_a, **_k):
        pass

    def is_stopped(self, _download_id):
        return False

    def complete_download(self, download_id, success=True, error=None, path=None):
        self.completed.append((download_id, success, error))


class _Response:
    status_code = 200
    content = b"<html>blocked</html>"

    def __init__(self, content_type):
        self.headers = {"content-type": content_type}

    def raise_for_status(self):
        pass


class _HtmlClient:
    def head(self, _url):
        return _Response("text/html; charset=utf-8")

    def get(self, _url, **_k):
        return _Response("text/html; charset=utf-8")

    def close(self):
        pass


class _Bars:
    def add_prebuilt_tasks(self, _tasks):
        pass


def _mp4(tmp_path, url="https://example.test/video.mp4"):
    return mp4.MP4FileDownloader(url=url, path=str(tmp_path / "video.mp4"), download_id="dl-1", bar_mgr=_Bars())


def test_html_content_type_fails_and_closes_the_tracker_entry(tmp_path, monkeypatch):
    tracker = _Tracker()
    monkeypatch.setattr(mp4, "download_tracker", tracker)
    monkeypatch.setattr(mp4, "create_client", lambda **_k: _HtmlClient())

    path, stopped, error = _mp4(tmp_path).download()

    assert (path, stopped) == (None, True)
    assert error
    assert tracker.started == ["dl-1"]
    assert tracker.completed == [("dl-1", False, error)]


def test_invalid_url_is_a_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(mp4, "download_tracker", _Tracker())

    path, stopped, error = _mp4(tmp_path, url="ftp://example.test/video.mp4").download()

    assert (path, stopped) == (None, True)
    assert error


def test_existing_file_is_still_not_a_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(mp4, "download_tracker", _Tracker())
    (tmp_path / "video.mp4").write_bytes(b"done")

    assert _mp4(tmp_path).download() == (None, False, None)


def test_hls_without_a_manifest_is_a_failure(tmp_path, monkeypatch):
    tracker = _Tracker()
    monkeypatch.setattr(hls, "download_tracker", tracker, raising=False)
    monkeypatch.setattr("VibraVid.core.downloader.base.download_tracker", tracker)

    result = hls.HLS_Downloader(output_path=str(tmp_path / "video.mp4")).start()

    assert result.stopped is True
    assert result.error == "No HLS manifest URL (source unavailable)"
