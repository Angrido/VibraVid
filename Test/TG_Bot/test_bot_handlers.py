# 21.11.26
# ruff: noqa: E402

import asyncio
import atexit
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest

pytest.importorskip("telethon")

_config_dir = tempfile.mkdtemp(prefix="vibravid_bot_tests_")
_state_dir = tempfile.mkdtemp(prefix="vibravid_bot_state_")
atexit.register(shutil.rmtree, _config_dir, ignore_errors=True)
atexit.register(shutil.rmtree, _state_dir, ignore_errors=True)
os.environ.setdefault("VIBRAVID_CONFIG", os.path.join(_config_dir, "config.toml"))
os.environ.setdefault("STATE_DIR", _state_dir)

from telethon import events

from docker.telegram_bot import common, handlers, loops, state


class _Event:
    """Just enough of a Telethon callback/message event: records answers, edits and replies."""

    def __init__(self, data: bytes = b"", chat_id: int = 1):
        self.data = data
        self.chat_id = chat_id
        self.sender_id = chat_id
        self.answers: list[str | None] = []
        self.edits: list[str] = []
        self.replies: list[str] = []

    async def answer(self, message=None, **kwargs):
        self.answers.append(message)

    async def edit(self, text, **kwargs):
        self.edits.append(text)
        return self

    async def respond(self, text, **kwargs):
        self.replies.append(text)


@pytest.fixture(autouse=True)
def _bot_state(monkeypatch):
    monkeypatch.setattr(handlers, "is_allowed", lambda event: True)
    monkeypatch.setattr(state, "_REMOTE", {"tok": [{"title": "Dune", "site": "s", "is_movie": True, "payload": {}}]})
    monkeypatch.setattr(state, "_STARTED", type(state._STARTED)())
    monkeypatch.setattr(state, "_pending", {})

    async def downgrade(event, caption):
        return event

    monkeypatch.setattr(common, "_downgrade_to_text", downgrade)


def _gui_post_recorder(monkeypatch, response):
    calls = []

    async def gui_post(path, payload, timeout=120):
        calls.append((path, payload))
        await asyncio.sleep(0.05)  # the second tap lands while the first one waits on the GUI
        return dict(response)

    monkeypatch.setattr(common, "gui_post", gui_post)
    return calls


# --- double taps must not start the same download twice ----------------------------------------------------------------------

@pytest.mark.parametrize(
    "handler, data",
    [
        (handlers.on_remote_pick, b"g:tok:0"),
        (handlers.on_season_all, b"sa:tok:0:1:8"),
        (handlers.on_episode_pick, b"se:tok:0:1:3"),
    ],
)
def test_a_double_tap_starts_the_download_once(monkeypatch, handler, data):
    calls = _gui_post_recorder(monkeypatch, {"download_id": "d1", "title": "Dune"})
    first, second = _Event(data), _Event(data)

    async def both():
        await asyncio.gather(handler(first), handler(second))

    asyncio.run(both())

    assert [path for path, _ in calls] == ["/api/bot/download/"]
    assert list(state._pending) == ["d1"]
    assert second.answers and second.answers[0]  # a short "already requested" toast instead of silence


def test_a_failed_start_can_be_tapped_again(monkeypatch):
    calls = _gui_post_recorder(monkeypatch, {"error": "busy"})
    asyncio.run(handlers.on_episode_pick(_Event(b"se:tok:0:1:3")))
    asyncio.run(handlers.on_episode_pick(_Event(b"se:tok:0:1:3")))

    assert len(calls) == 2


# --- GUI error answers (wrong/missing bot secret) must not read as "nothing to show" ------------------------------------------

def _gui_get_returning(monkeypatch, module, response):
    async def gui_get(path, timeout=30):
        return dict(response)

    monkeypatch.setattr(module, "gui_get", gui_get)


@pytest.mark.parametrize("command", [handlers.cmd_coda, handlers.cmd_stato])
def test_queue_and_status_report_a_gui_error(monkeypatch, command):
    _gui_get_returning(monkeypatch, handlers, {"error": "Unauthorized"})
    event = _Event()

    with pytest.raises(events.StopPropagation):
        asyncio.run(command(event))

    assert len(event.replies) == 1 and "Unauthorized" in event.replies[0]
    assert "No active" not in event.replies[0] and "reachable" not in event.replies[0]


def test_monitor_does_not_drop_pending_downloads_on_a_gui_error(monkeypatch):
    _gui_get_returning(monkeypatch, loops, {"error": "Forbidden"})
    msg = _Event()
    state._pending["d1"] = {"title": "Dune", "chat_id": 1, "ts": time.time() - 600, "msg": msg,
                            "last_text": "", "expected": 1, "was_active": False}
    real_sleep = asyncio.sleep
    rounds = []

    async def fake_sleep(seconds):
        rounds.append(seconds)
        if len(rounds) > 2:
            raise asyncio.CancelledError
        await real_sleep(0)

    monkeypatch.setattr(loops.asyncio, "sleep", fake_sleep)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(loops.download_monitor_loop())

    assert "d1" in state._pending and msg.edits == []


def test_monitor_asks_only_for_the_recent_history(monkeypatch):
    paths = []

    async def gui_get(path, timeout=30):
        paths.append(path)
        return {"active": [], "scheduled": [], "history": []}

    monkeypatch.setattr(loops, "gui_get", gui_get)
    state._pending["d1"] = {"title": "Dune", "chat_id": 1, "ts": time.time(), "msg": _Event(),
                            "last_text": "", "expected": 3, "was_active": False}
    real_sleep = asyncio.sleep
    rounds = []

    async def fake_sleep(seconds):
        rounds.append(seconds)
        if len(rounds) > 1:
            raise asyncio.CancelledError
        await real_sleep(0)

    monkeypatch.setattr(loops.asyncio, "sleep", fake_sleep)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(loops.download_monitor_loop())

    assert paths and paths[0].startswith("/api/get-downloads/?history=")


# --- cancel ------------------------------------------------------------------------------------------------------------------

def test_a_failed_cancel_keeps_following_the_download(monkeypatch):
    async def gui_post(path, payload, timeout=120):
        raise OSError("GUI down")

    monkeypatch.setattr(handlers, "gui_post", gui_post)
    monkeypatch.setattr(state, "_CANCEL_TOKENS", {"ctok": "d1"})
    state._pending["d1"] = {"title": "Dune", "chat_id": 1}

    asyncio.run(handlers.on_cancel_download(_Event(b"dc:ctok")))

    assert "d1" in state._pending


def test_a_successful_cancel_forgets_the_download(monkeypatch):
    async def gui_post(path, payload, timeout=120):
        return {"ok": True}

    monkeypatch.setattr(handlers, "gui_post", gui_post)
    monkeypatch.setattr(state, "_CANCEL_TOKENS", {"ctok": "d1"})
    state._pending["d1"] = {"title": "Dune", "chat_id": 1}
    event = _Event(b"dc:ctok")

    asyncio.run(handlers.on_cancel_download(event))

    assert "d1" not in state._pending and "Dune" in event.edits[-1]
