import pytest
from textual.app import App
from textual.widgets import DataTable

from VibraVid.core.ui.tracker import download_tracker
from VibraVid.tui.screens.downloads import DownloadsScreen


@pytest.mark.anyio
async def test_completed_downloads_allow_duplicate_output_paths(monkeypatch):
    shared_path = "/tmp/episode.mkv"
    history = [
        {
            "id": "download-one",
            "title": "Episode",
            "site": "example",
            "status": "completed",
            "path": shared_path,
        },
        {
            "id": "download-two",
            "title": "Episode retry",
            "site": "example",
            "status": "completed",
            "path": shared_path,
        },
    ]

    monkeypatch.setattr(download_tracker, "get_active_downloads", lambda: [])
    monkeypatch.setattr(download_tracker, "get_history", lambda: history)

    class TestApp(App):
        def compose(self):
            yield DownloadsScreen()

    app = TestApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        completed_table = app.screen.query_one("#completed-table", DataTable)
        assert completed_table.row_count == 2


def _entry(did, status, **extra):
    return {"id": did, "title": did, "site": "example", "status": status, "end_time": 1, **extra}


@pytest.mark.anyio
async def test_clear_completed_keeps_failed_and_cancelled_entries(monkeypatch, tmp_path):
    """Clear Completed must not throw away the failed/cancelled entries and their Retry data."""
    import json

    history_file = tmp_path / "history.json"
    entries = [
        _entry("done-1", "completed"),
        _entry("failed-1", "failed", retry={"argv": ["x"]}),
        _entry("cancelled-1", "cancelled"),
    ]
    history_file.write_text(json.dumps(entries), encoding="utf-8")
    monkeypatch.setattr(download_tracker, "_django_enabled", lambda: False)
    monkeypatch.setattr(download_tracker, "_history_file_path", lambda: str(history_file))
    monkeypatch.setattr(download_tracker, "history", [dict(e) for e in entries])
    monkeypatch.setattr(download_tracker, "get_active_downloads", lambda: [])

    class TestApp(App):
        def compose(self):
            yield DownloadsScreen()

    app = TestApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        app.screen.query_one("#btn-clear").press()
        await pilot.pause()
        assert app.screen.query_one("#completed-table", DataTable).row_count == 0

    assert sorted(e["id"] for e in download_tracker.history) == ["cancelled-1", "failed-1"]
    assert download_tracker.history[0]["retry"] == {"argv": ["x"]}
    assert sorted(e["id"] for e in json.loads(history_file.read_text(encoding="utf-8"))) == ["cancelled-1", "failed-1"]


@pytest.mark.anyio
async def test_refresh_keeps_the_cursor_on_the_same_download(monkeypatch):
    """A row appearing above the cursor must not move Cancel onto another download."""
    active = [_entry("aaa", "downloading"), _entry("bbb", "downloading")]
    history = [_entry("c-1", "completed", path="/x/1.mkv"), _entry("c-2", "completed", path="/x/2.mkv")]
    monkeypatch.setattr(download_tracker, "get_active_downloads", lambda: list(active))
    monkeypatch.setattr(download_tracker, "get_history", lambda: list(history))
    stopped = []
    monkeypatch.setattr(download_tracker, "request_stop", stopped.append)

    class TestApp(App):
        def compose(self):
            yield DownloadsScreen()

    app = TestApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.query_one(DownloadsScreen)
        screen.query_one("#downloads-table", DataTable).move_cursor(row=1)
        screen.query_one("#completed-table", DataTable).move_cursor(row=1)
        await pilot.pause()

        active.insert(0, _entry("new", "downloading"))
        history.insert(0, _entry("c-0", "completed", path="/x/0.mkv"))
        screen._refresh_downloads()
        await pilot.pause()

        screen._on_cancel()
        assert stopped == ["bbb"]
        assert screen._get_selected_completed_path() == "/x/2.mkv"
