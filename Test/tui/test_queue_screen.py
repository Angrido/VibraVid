# 01.08.26

import pytest
from textual.app import App
from textual.widgets import Button

from VibraVid.tui.screens.queue import QueueScreen


@pytest.mark.anyio
async def test_queue_actions_include_enqueue_button():
    class TestApp(App):
        def compose(self):
            yield QueueScreen()

    app = TestApp()
    async with app.run_test() as pilot:
        screen = app.screen
        add_command_btn = screen.query_one("#add-command-btn", Button)
        assert add_command_btn is not None
        await pilot.pause()


@pytest.mark.anyio
async def test_queue_actions_all_buttons_present():
    expected_ids = {
        "run-queue-btn",
        "add-command-btn",
        "remove-btn",
        "retry-btn",
        "clear-queue-btn",
        "queue-btn-clear",
    }

    class TestApp(App):
        def compose(self):
            yield QueueScreen()

    app = TestApp()
    async with app.run_test() as pilot:
        screen = app.screen
        actions = screen.query_one("#queue-actions")
        present_ids = {btn.id for btn in actions.query(Button)}
        assert expected_ids.issubset(present_ids)
        await pilot.pause()


def _queue_app(tmp_path, monkeypatch, statuses):
    import json

    from VibraVid.utils import config_manager

    monkeypatch.setattr(config_manager, "base_path", str(tmp_path))
    folder = tmp_path / ".cache" / "queue"
    folder.mkdir(parents=True)
    items = [{"id": f"q{i}", "argv": ["--help"], "status": status} for i, status in enumerate(statuses)]
    (folder / "queue_t.json").write_text(json.dumps({"version": 1, "items": items}), encoding="utf-8")

    class TestApp(App):
        def on_mount(self):
            self.push_screen(QueueScreen())

    return TestApp(), folder / "queue_t.json"


@pytest.mark.anyio
async def test_clear_completed_button_removes_the_done_items(tmp_path, monkeypatch):
    import json

    app, path = _queue_app(tmp_path, monkeypatch, ["done", "pending", "done"])
    async with app.run_test(size=(200, 50)) as pilot:
        await pilot.pause()
        await pilot.click("#queue-btn-clear")
        await pilot.pause()
        assert [it["id"] for it in json.loads(path.read_text(encoding="utf-8"))["items"]] == ["q1"]
        assert app.screen.query_one("#queue-table").row_count == 1


@pytest.mark.anyio
async def test_clear_queue_with_a_running_item_notifies_instead_of_exiting(tmp_path, monkeypatch):
    """clear() raises SystemExit when an item runs: the handler caught only Exception, so the TUI closed."""
    app, path = _queue_app(tmp_path, monkeypatch, ["running", "pending"])
    async with app.run_test(size=(200, 50)) as pilot:
        await pilot.pause()
        await pilot.click("#clear-queue-btn")
        await pilot.pause()
        assert app.is_running
        assert isinstance(app.screen, QueueScreen)
        assert path.exists()
        assert any(n.severity == "error" for n in app._notifications)


class _RunningProc:
    pid = 4242

    def poll(self):
        return None


def test_kill_child_stops_the_whole_process_group_on_posix(monkeypatch):
    """The child runs velora/ffmpeg: terminating only `python manual.py` would orphan them."""
    import signal

    from VibraVid.tui.screens import queue as queue_screen

    killed = []
    monkeypatch.setattr(queue_screen.sys, "platform", "linux")
    monkeypatch.setattr(queue_screen.os, "killpg", lambda pgid, sig: killed.append((pgid, sig)), raising=False)
    screen = QueueScreen()
    screen._proc = _RunningProc()

    screen._kill_child()

    assert killed == [(4242, signal.SIGTERM)]


def test_the_child_gets_its_own_process_group(monkeypatch, tmp_path):
    from VibraVid.tui.screens import queue as queue_screen

    seen = {}

    class _Proc:
        def __init__(self, cmd, **kwargs):
            seen.update(kwargs)

        def wait(self):
            screen._stop.set()  # leave right after this job: the end-of-run notice needs a running app
            return 0

    claims = iter([({"id": "q1", "argv": ["--help"]}, "queue.json"), (None, None)])
    monkeypatch.setattr(queue_screen, "_claim_next_any", lambda paths, ids: next(claims))
    monkeypatch.setattr(queue_screen, "_finish_item", lambda *args: None)
    monkeypatch.setattr(queue_screen, "_all_queue_paths", lambda: [])
    monkeypatch.setattr(QueueScreen, "_log_path", staticmethod(lambda item_id, create=False: str(tmp_path / "q.log")))
    monkeypatch.setattr(QueueScreen, "_ui", lambda self, fn, *a, **k: None)
    monkeypatch.setattr(queue_screen.subprocess, "Popen", _Proc)
    monkeypatch.setattr(queue_screen.sys, "platform", "linux")
    screen = QueueScreen()

    QueueScreen._run_queue_worker.__wrapped__(screen)

    assert seen.get("start_new_session") is True


def test_leaving_the_screen_does_not_wait_for_taskkill(monkeypatch):
    import threading
    import time

    from VibraVid.tui.screens import queue as queue_screen

    release, done = threading.Event(), threading.Event()

    def slow_taskkill(*args, **kwargs):
        release.wait(5)
        done.set()

    monkeypatch.setattr(queue_screen.sys, "platform", "win32")
    monkeypatch.setattr(queue_screen.subprocess, "run", slow_taskkill)
    screen = QueueScreen()
    screen._proc = _RunningProc()
    screen._is_worker_running = True

    started = time.monotonic()
    screen.on_unmount()
    assert time.monotonic() - started < 1
    release.set()
    assert done.wait(5)
